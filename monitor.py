"""Read-only lodging availability monitor. Exit 1: vacancy; exit 2: check error."""
import argparse
from datetime import date, datetime, timedelta
import json
import os
from pathlib import Path
import re
import sys
from urllib.parse import urlencode, urljoin
from zoneinfo import ZoneInfo

from bs4 import BeautifulSoup
import requests
from requests.adapters import HTTPAdapter
from urllib3.util.retry import Retry

RAICHO = 'https://www.tenawan.ne.jp/lodgment/rec/007/602/pcr.asp'
MIKURI = 'https://d-reserve.jp/GSEA002F01400/GSEA002A01'
PLANS = [('PL00008095', 'RM00003893'), ('PL00008151', 'RM00003906'),
         ('PL00044720', 'RM00013017')]
DEFAULT_DATES = (date(2026, 10, 11),)


def mikuri_url(target, plan, room):
    return MIKURI + '?' + urlencode(dict(
        hotelCode='0000001203', pl=plan, ci=target.strftime('%Y%m%d'),
        co=(target + timedelta(days=1)).strftime('%Y%m%d'), rmcd001=room,
        rm001=1, lt001='0_1_2_3_4', lnum001='1_0_0_0_0', sumrm=1,
        way=1, cinon='true', dpck='false', DPCheckEnable='false'))


def parse_raicho(html, target):
    soup = BeautifulSoup(html, 'html.parser')
    tables = [t for t in soup.select('table.caltbl')
              if (h := t.select_one('th.month')) and re.search(
                  rf'{target.year}年.*?\s{target.month}月', h.get_text())]
    if len(tables) != 1:
        raise ValueError('雷鳥莊：找不到唯一的目標月份')
    days = [b for b in tables[0].select('b') if b.get_text(strip=True) == str(target.day)]
    if len(days) != 1:
        raise ValueError('雷鳥莊：找不到唯一的目標日期')
    day = days[0].find_parent('td')
    labels = day.find_parent('tr').select('td.room td')
    cells = day.select('div.roomtbl td')
    if len(labels) != 5 or len(cells) != 5:
        raise ValueError('雷鳥莊：房型日曆格式改變')
    result = []
    for label, cell in zip(labels, cells):
        mark = cell.get_text(strip=True)
        anchor = cell.find('a', href=True)
        count = re.fullmatch(r'(\d+)室', mark)
        available = bool(count and int(count[1]) > 0 and anchor)
        if not available and mark != '×':
            raise ValueError(f'雷鳥莊：無法識別空位狀態 {mark!r}')
        room = label.get_text(strip=True)
        result.append(dict(hotel='雷鳥莊', room=room,
                           room_display='個室（非單人）' if room == '個室' else room,
                           available=available, status=mark,
                           url=urljoin(RAICHO, anchor['href']) if available else RAICHO))
    return result


def parse_mikuri(html, target, plan, room):
    match = re.search(r'Object\.assign\(\s*data_ve\s*,\s*', html)
    if not match:
        raise ValueError('みくりが池温泉：找不到日曆資料')
    data, _ = json.JSONDecoder().raw_decode(html[match.end():])
    expected = dict(hotelCode='0000001203', pl=plan, rmcd001=room,
                    ci=target.strftime('%Y%m%d'),
                    co=(target + timedelta(days=1)).strftime('%Y%m%d'))
    if any(data.get(k) != v for k, v in expected.items()):
        raise ValueError('みくりが池温泉：回傳日期或方案不符')
    if data.get('lnum001') != '1_0_0_0_0' or data.get('sumrm') != 1:
        raise ValueError('みくりが池温泉：回傳入住人數不符')
    if any(data.get(k) for k in ('displayMessage', 'searchResultMessage', 'calendarMessage')):
        raise ValueError('みくりが池温泉：網站回傳搜尋訊息，需人工檢查')
    days = [d for m in data.get('calendarSalesYearList') or []
            if m['calendarSalesYear'] == target.strftime('%Y%m')
            for d in m['roomPriceCalendarList']
            if d['roomSalesDate'] == target.strftime('%d')]
    if len(days) != 1:
        raise ValueError('みくりが池温泉：缺少目標日期日曆')
    mark = days[0]['roomSalesStatusKbn']
    if mark not in ('○', '△', '×', '－'):
        raise ValueError(f'みくりが池温泉：無法識別空位狀態 {mark!r}')
    available = mark in ('○', '△')
    if available and not days[0].get('roomPrice'):
        raise ValueError('みくりが池温泉：有空位標記但缺少有效價格')
    return dict(hotel='みくりが池温泉', room=data['planName'],
                available=available, status=mark, price_yen=days[0]['roomPrice'],
                url=mikuri_url(target, plan, room))


def exit_code(results, errors):
    return 1 if any(r['available'] for r in results) else 2 if errors else 0


def add_date(rows, target):
    for row in rows:
        row['date'] = str(target)
    return rows


def check_dates(session, targets):
    """Return normalized results and errors for every active target date."""
    results, errors = [], []
    try:
        response = session.get(RAICHO, timeout=(15, 45))
        response.raise_for_status()
        raicho_html = response.content.decode('cp932')
    except Exception as exc:
        for target in targets:
            errors.append(f'{target} 雷鳥莊：{exc}')
    else:
        for target in targets:
            try:
                results.extend(add_date(parse_raicho(raicho_html, target), target))
            except Exception as exc:
                errors.append(f'{target} 雷鳥莊：{exc}')

    for target in targets:
        for plan, room in PLANS:
            try:
                response = session.get(mikuri_url(target, plan, room), timeout=(15, 45))
                response.raise_for_status()
                row = parse_mikuri(response.content.decode('utf-8'), target, plan, room)
                results.extend(add_date([row], target))
            except Exception as exc:
                errors.append(f'{target} みくりが池温泉 {plan}：{exc}')
    return results, errors


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--date', action='append', dest='dates', type=date.fromisoformat,
                        help='check-in date; repeat to monitor more than one date')
    args = parser.parse_args()
    targets = sorted(set(args.dates or DEFAULT_DATES))
    now = datetime.now(ZoneInfo('Asia/Tokyo'))
    targets = [target for target in targets if now.date() <= target]
    if not targets:
        print('所有入住日期皆已過，停止查詢。請停用 workflow 以停止排程。')
        return 0
    session = requests.Session()
    session.headers.update({'User-Agent': 'TateyamaAvailabilityMonitor/1.0',
                            'Cache-Control': 'no-cache'})
    session.mount('https://', HTTPAdapter(max_retries=Retry(
        total=2, backoff_factor=2, status_forcelist=[429, 500, 502, 503, 504],
        allowed_methods=['GET'])))
    results, errors = check_dates(session, targets)
    code = exit_code(results, errors)
    title = '發現空位' if code == 1 else '監控異常' if code == 2 else '目前沒有空位'
    date_label = '、'.join(map(str, targets))
    lines = [f'# {date_label} 立山住宿：{title}', f'檢查時間：{now.isoformat()}',
             '各住 1 晚。みくりが池温泉查詢 1 位成人；雷鳥莊包含非單人個室，依網站房型庫存通知。', '']
    for r in results:
        room_display = r.get('room_display', r['room'])
        lines.append(f"- {r['date']} {'有空位' if r['available'] else '無可訂空位'}：{r['hotel']} / {room_display} — {r['status']} [訂房頁]({r['url']})")
        if r['available']:
            print(f"::error title=發現空位::{r['date']} {r['hotel']} {room_display} {r['status']} {r['url']}")
    for error in errors:
        lines.append(f'- 監控異常：{error}')
        print(f'::error title=監控異常（非空位通知）::{error}')
    report = '\n'.join(lines) + '\n'
    print(report)
    Path('results.json').write_text(json.dumps(dict(
        dates=list(map(str, targets)), queried_at=now.isoformat(),
        query={'nights': 1, 'hotels': {
            '雷鳥莊': {'room_types': 'all', 'include_non_single_private_room': True},
            'みくりが池温泉': {'adults': 1}}},
        results=results, errors=errors,
        limitations=['空位是查詢當下的網站狀態，不代表保留或完成訂房。',
                     '雷鳥莊依網站房型庫存通知；非單人個室與其他房型的人數、價格需在訂房頁確認。']),
        ensure_ascii=False, indent=2), encoding='utf-8')
    if os.environ.get('GITHUB_STEP_SUMMARY'):
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a', encoding='utf-8') as f:
            f.write(report)
    return code


if __name__ == '__main__':
    sys.exit(main())
