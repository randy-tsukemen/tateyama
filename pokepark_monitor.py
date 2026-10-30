"""Mac-only, headed Chrome monitor. No login, checkout, or ticket reservation.

Calendar stock covers all ticket types. Only the verified Elite card can trigger
an alert. Browser challenges require manual handling; no challenge bypasses.
"""
import argparse
from datetime import date, datetime
import fcntl
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import subprocess
import time
import uuid
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup

ROOT = Path(__file__).resolve().parent
DATA = Path.home() / 'Library/Application Support/PokeParkMonitor'
HOME = 'https://www.pokepark-kanto.co.jp/ppark/ticket/dateSelect/index'
REPO = 'randy-tsukemen/tateyama'
WORKFLOW = 'pokepark-notify.yml'
JST = ZoneInfo('Asia/Tokyo')
INTERVAL = 120
LOG = logging.getLogger('pokepark')


def parse_calendar(data, month, today):
    if data.get('result') != 'OK' or data.get('nextMonthFlg') not in (0, 1):
        raise ValueError('Calendar result or pagination changed')
    rows = data.get('dates')
    if not isinstance(rows, list) or not rows:
        raise ValueError('Calendar dates missing')
    seen, statuses, candidates = set(), {}, []
    for row in rows:
        day = date.fromisoformat(row['date'])
        if day.strftime('%Y-%m') != month or day in seen:
            raise ValueError('Calendar date mismatch or duplicate')
        seen.add(day)
        if day < today:
            continue
        for flag in ('linkFlg', 'closedFlg'):
            if row.get(flag) not in (0, 1):
                raise ValueError('Unknown calendar flag')
        if row['closedFlg'] or not row['linkFlg'] or not row.get('pattern'):
            statuses[str(day)] = False
            continue
        stock = row.get('stockCount')
        if type(stock) is not int or stock < 0:
            raise ValueError('Invalid calendar stock')
        if stock > 0:
            candidates.append(str(day))
        else:
            statuses[str(day)] = False
    return statuses, candidates, bool(data['nextMonthFlg'])


def parse_elite(html, target):
    soup = BeautifulSoup(html, 'html.parser')
    selected = soup.select_one('.ticket-select-date .date')
    day = date.fromisoformat(target)
    if not selected or not selected.get_text(strip=True).startswith(
            f'{day.year}年{day.month}月{day.day}日'):
        raise ValueError('Ticket page date mismatch')
    fields = soup.select('input[name="selectTicketTypeArray"][value="3"]')
    if len(fields) != 1:
        raise ValueError('Elite ticket field missing or duplicated')
    field = fields[0]
    label = soup.find('label', attrs={'for': field.get('id')})
    if not label or label.get_text(strip=True) != 'エリートトレーナーズパス':
        raise ValueError('Elite product identity changed')
    card = field.find_parent(class_='ticket-type-card')
    stock = card.select_one('.ticket-stock') if card else None
    if not stock:
        raise ValueError('Elite stock missing')
    mark = stock.get_text(strip=True)
    enabled = not field.has_attr('disabled')
    if mark in ('残り○', '残り△') and enabled:
        return True
    if mark == '残り×' and not enabled:
        return False
    raise ValueError('Unknown or contradictory Elite stock')


def next_month(month):
    year, number = map(int, month.split('-'))
    return f'{year + (number == 12):04}-{number % 12 + 1:02}'


def scan(page):
    today = datetime.now(JST).date()
    page.goto(HOME, wait_until='domcontentloaded', timeout=30000)
    page.locator('form#ticketPurchaseCommand[action="/ppark/ticket/dateSelect/next"]').wait_for(
        state='attached', timeout=20000)
    statuses, candidates, months = {}, [], []
    month = today.strftime('%Y-%m')
    for _ in range(24):
        data = page.evaluate('''async month => {
          const r = await fetch('/ppark/ticket/dateSelect/select?yearMonth=' + month + '&isScheduleRequest=0',
                                {cache:'no-store', signal:AbortSignal.timeout(20000)});
          if (!r.ok || !r.headers.get('content-type')?.includes('application/json'))
            throw new Error('Calendar unavailable');
          return await r.json();
        }''', month)
        known, pending, more = parse_calendar(data, month, today)
        statuses.update(known)
        candidates.extend(pending)
        months.append(month)
        if not more:
            break
        month = next_month(month)
        time.sleep(0.3)
    else:
        raise ValueError('Calendar pagination exceeded safety limit')
    errors = []
    for target in candidates:
        try:
            response = page.evaluate('''async target => {
              const reset = await fetch('/ppark/ticket/dateSelect/reselect',
                                        {cache:'no-store', signal:AbortSignal.timeout(20000)});
              if (!reset.ok) throw new Error('Date reselection unavailable');
              const doc = new DOMParser().parseFromString(await reset.text(), 'text/html');
              const f = doc.querySelector('#ticketPurchaseCommand');
              const action = f && new URL(f.getAttribute('action'), location.origin);
              if (!f || action.pathname !== '/ppark/ticket/dateSelect/next')
                throw new Error('Date selection form changed');
              const body = new URLSearchParams(new FormData(f));
              body.set('selectDate', target);
              const r = await fetch(action.href, {method:'POST', body, signal:AbortSignal.timeout(20000)});
              if (!r.ok || new URL(r.url).pathname !== '/ppark/ticket/typeSelect/index')
                throw new Error('Ticket detail unavailable');
              return await r.text();
            }''', target)
            statuses[target] = parse_elite(response, target)
        except Exception as exc:
            errors.append(target)
            LOG.warning('Ticket check failed for %s (%s)', target, type(exc).__name__)
        time.sleep(0.35)
    return {'checked_at': datetime.now(JST).isoformat(), 'months': months,
            'statuses': statuses, 'errors': errors, 'candidate_count': len(candidates)}


def gh(args, payload=None):
    result = subprocess.run(['/opt/homebrew/bin/gh', *args],
                            input=json.dumps(payload) if payload is not None else None,
                            capture_output=True, text=True, timeout=40, cwd=ROOT)
    if result.returncode:
        raise RuntimeError('GitHub notification relay request failed')
    return json.loads(result.stdout) if result.stdout.strip() else None


def notify(payload):
    ident = str(uuid.uuid4())
    gh(['api', f'repos/{REPO}/actions/workflows/{WORKFLOW}/dispatches',
        '--method', 'POST', '--input', '-'],
       {'ref': 'main', 'inputs': {'notification_id': ident,
                                 'payload': json.dumps(payload, ensure_ascii=False)}})
    # Confirm Telegram API success, not merely that GitHub accepted a dispatch.
    deadline = time.monotonic() + 110
    while time.monotonic() < deadline:
        time.sleep(5)
        runs = gh(['api', f'repos/{REPO}/actions/workflows/{WORKFLOW}/runs?event=workflow_dispatch&per_page=20'])
        match = next((r for r in runs['workflow_runs'] if ident in r['display_title']), None)
        if match and match['status'] == 'completed':
            if match['conclusion'] != 'success':
                raise RuntimeError('Private Telegram delivery failed')
            LOG.info('Private Telegram delivery confirmed: %s', payload['kind'])
            return
    raise RuntimeError('Private Telegram delivery not yet confirmed')


def save(path, value):
    temporary = path.with_suffix('.tmp')
    temporary.write_text(json.dumps(value, ensure_ascii=False, indent=2))
    temporary.replace(path)


def process_report(report, state, send=notify):
    previous = state.setdefault('statuses', {})
    new = [day for day, available in report['statuses'].items()
           if available and not previous.get(day, False)]
    if new:
        send({'kind': 'available', 'dates': sorted(new)})
    previous.update(report['statuses'])
    # Missing/failed dates retain previous status rather than becoming sold out.
    today = datetime.now(JST).date().isoformat()
    state['statuses'] = {day: value for day, value in previous.items() if day >= today}
    if report['errors']:
        raise RuntimeError('Some ticket dates could not be checked')


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--once', action='store_true', help='Check only; no Telegram or persistent state updates')
    args = parser.parse_args()
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(DATA, 0o700)
    lock = (DATA / 'monitor.lock').open('w')
    try:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError:
        raise SystemExit('Monitor already running')
    handler = RotatingFileHandler(DATA / 'monitor.log', maxBytes=2_000_000, backupCount=3)
    logging.basicConfig(level=logging.INFO, handlers=[handler, logging.StreamHandler()],
                        format='%(asctime)s %(levelname)s %(message)s')
    from playwright.sync_api import sync_playwright
    state_path = DATA / 'state.json'
    state = json.loads(state_path.read_text()) if state_path.exists() else {}
    with sync_playwright() as playwright:
        context = playwright.chromium.launch_persistent_context(
            str(DATA / 'browser'), channel='chrome', headless=False, chromium_sandbox=True,
            locale='ja-JP', timezone_id='Asia/Tokyo')
        page = context.pages[0] if context.pages else context.new_page()
        while True:
            started = time.monotonic()
            try:
                report = scan(page)
                save(DATA / 'latest.json', report)
                available = [day for day, value in report['statuses'].items() if value]
                LOG.info('Checked %s; %d dates, %d detail pages; Elite available: %s; errors: %d',
                         ','.join(report['months']), len(report['statuses']), report['candidate_count'],
                         ','.join(available) or 'none', len(report['errors']))
                if args.once:
                    print(json.dumps(report, ensure_ascii=False))
                    context.close()
                    return
                process_report(report, state)
                if not state.get('started_notice'):
                    notify({'kind': 'started'})
                    state['started_notice'] = True
                elif state.get('error_notice'):
                    notify({'kind': 'recovered'})
                state['error_notice'] = False
                state['last_success'] = report['checked_at']
                state.pop('last_error', None)
            except Exception as exc:
                LOG.error('Scan/delivery incomplete (%s): %s', type(exc).__name__, str(exc).splitlines()[0][:160])
                if args.once:
                    context.close()
                    raise
                state['last_error'] = datetime.now(JST).isoformat()
                if not state.get('error_notice'):
                    try:
                        notify({'kind': 'error'})
                        state['error_notice'] = True
                    except Exception:
                        LOG.error('Error notification delivery unconfirmed')
                if page.is_closed():
                    # Exit for launchd to relaunch a fresh dedicated browser.
                    raise RuntimeError('Monitor browser closed')
            save(state_path, state)
            remaining = max(0, INTERVAL - (time.monotonic() - started))
            if not remaining:
                LOG.warning('Cycle exceeded 120 seconds; next check starts without catch-up requests')
            time.sleep(remaining)


if __name__ == '__main__':
    main()
