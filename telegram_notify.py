"""Telegram notifications. Never log request URLs, credentials, or API bodies."""
import argparse
import json
import os
import re
from pathlib import Path
import time
import requests


def api(method, payload, attempts=3, allow_migration=True):
    token = os.environ.get('TELEGRAM_BOT_TOKEN', '').strip()
    if not token:
        raise RuntimeError('Missing TELEGRAM_BOT_TOKEN secret')
    if not re.fullmatch(r'[0-9]+:[A-Za-z0-9_-]+', token):
        raise RuntimeError('TELEGRAM_BOT_TOKEN has invalid format; store only the complete numeric-ID:token value from BotFather')
    for attempt in range(attempts):
        delay = 2 ** (attempt + 1)
        try:
            response = requests.post(f'https://api.telegram.org/bot{token}/{method}',
                                     json=payload, timeout=(10, 20))
            body = response.json()
        except (requests.RequestException, ValueError):
            # Exception strings can contain the token-bearing URL.
            body = {}
            status = 0
        else:
            status = response.status_code
            if status == 200 and body.get('ok'):
                return body['result']
            migrated = body.get('parameters', {}).get('migrate_to_chat_id')
            if (status == 400 and allow_migration and method == 'sendMessage'
                    and isinstance(migrated, int) and migrated < 0):
                print('Telegram group migrated to supergroup; retrying with updated destination.')
                return api(method, {**payload, 'chat_id': str(migrated)},
                           attempts=attempts, allow_migration=False)
            if status == 429:
                delay = max(delay, int(body.get('parameters', {}).get('retry_after', 1)))
            elif 400 <= status < 500:
                # Only predefined diagnostic labels may enter public Actions logs.
                description = str(body.get('description', '')).lower()
                reason = 'check chat ID and bot permissions'
                for phrase in ('chat not found', 'bot was kicked', 'bot is not a member',
                               'not enough rights', 'bot was blocked', 'group chat was deleted'):
                    if phrase in description:
                        reason = phrase
                        break
                raise RuntimeError(f'Telegram rejected request (HTTP {status}; {reason})')
        if attempt + 1 < attempts and delay <= 30:
            time.sleep(delay)
        else:
            break
    raise RuntimeError('Telegram delivery unconfirmed after bounded retries; check Actions settings/logs')


def discover_chat(updates):
    ids = set()
    for update in updates:
        message = update.get('message', {})
        chat = message.get('chat', {})
        if chat.get('type') == 'private' and message.get('text', '').split(' ')[0] == '/start':
            ids.add(str(chat['id']))
    if len(ids) != 1:
        raise RuntimeError('Need exactly one private /start conversation; send /start to your Bot again or configure chat ID manually')
    return ids.pop()


def messages(report, run_url=''):
    result = []
    for row in report['results']:
        if row['available']:
            target = row.get('date') or report.get('date')
            result.append(f"🏔️ 立山住宿有空位\n入住：{target}（1 晚）\n"
                          f"{row['hotel']}｜{row.get('room_display', row['room'])}\n網站狀態：{row['status']}\n"
                          f"{row['url']}\n\n請至訂房頁確認，空位可能隨時售出。\n{run_url}")
    if report['errors']:
        result.append('⚠️ 立山監控異常（不是空位通知）\n' +
                      '\n'.join(report['errors'])[:2500] + '\n' + run_url)
    return result


def discover_group(updates, title, username, owner_id):
    ids = set()
    for update in updates:
        message = update.get('message', {})
        chat = message.get('chat', {})
        if (chat.get('type') in ('group', 'supergroup')
                and chat.get('title') == title
                and str(message.get('from', {}).get('id')) == str(owner_id)
                and message.get('text', '').strip() == f'/start@{username}'):
            ids.add(str(chat['id']))
    if len(ids) != 1:
        raise RuntimeError('Need one matching group command sent by the configured private-chat owner')
    return ids.pop()


def send(text):
    private = os.environ.get('TELEGRAM_CHAT_ID', '').strip()
    group = os.environ.get('TELEGRAM_GROUP_ID', '').strip()
    if not private:
        raise RuntimeError('Missing TELEGRAM_CHAT_ID secret')
    failures = []
    targets = [('private', private)]
    if group and group != private:
        targets.append(('group', group))
    for label, chat in targets:
        try:
            api('sendMessage', {'chat_id': chat, 'text': text[:4000],
                                'link_preview_options': {'is_disabled': True}})
            print(f'Telegram accepted notification ({label}).')
        except RuntimeError as exc:
            failures.append(f'{label}: {exc}')
    if failures:
        raise RuntimeError('Telegram delivery unconfirmed for: ' + ', '.join(failures))


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('--test', action='store_true')
    parser.add_argument('--results', default='results.json')
    args = parser.parse_args()
    run_url = (f"https://github.com/{os.environ['GITHUB_REPOSITORY']}/actions/runs/"
               f"{os.environ['GITHUB_RUN_ID']}" if os.environ.get('GITHUB_RUN_ID') else '')
    if args.test:
        send('✅ 立山空床監控 Telegram 通知測試\n這是測試，不代表有空位。\n'
             '監控日期：2026/10/11 入住，住 1 晚。\n'
             '之後有空位會直接傳送房型與訂房連結。\n' + run_url)
        return
    path = Path(args.results)
    if not path.exists():
        if os.environ.get('CHECK_OUTCOME') == 'failure':
            send('⚠️ 立山監控異常（不是空位通知）\n未能產生檢查結果，請查看執行紀錄。\n' + run_url)
        return
    report = json.loads(path.read_text())
    notifications = messages(report, run_url)
    for index, message in enumerate(notifications):
        if index:
            time.sleep(1.1)
        send(message)
    if not notifications:
        print('No vacancy or check error; no Telegram notification needed.')


if __name__ == '__main__':
    try:
        main()
    except RuntimeError as exc:
        print(f'::error::{exc}')
        raise SystemExit(1)
