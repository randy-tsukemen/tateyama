"""Fixed-format, private-only Telegram relay for the local PokéPark monitor."""
import json
import os
from datetime import date

from telegram_notify import api

URL = 'https://www.pokepark-kanto.co.jp/ppark/ticket/dateSelect/index'


def message(payload):
    kind = payload['kind']
    if kind == 'started':
        return ('✅ 寶可夢精英票監控已啟動\n這台 Mac 每 2 分鐘檢查所有開放販售日期。\n'
                '只傳私人對話；發現新釋出票或售罄後重新有票時通知。\n'
                '請保持 Mac 開機且不休眠。這是啟動通知，不代表有票。')
    if kind == 'error':
        return ('⚠️ 寶可夢監控暫時無法完成檢查（不是有票通知）\n'
                '請查看這台 Mac 的監控紀錄與專用 Chrome 視窗；可能需要人工完成網站驗證。')
    if kind == 'recovered':
        return '✅ 寶可夢精英票監控已恢復正常檢查。'
    if kind != 'available':
        raise ValueError('Unknown notification kind')
    dates = payload.get('dates')
    if not isinstance(dates, list) or not 1 <= len(dates) <= 366:
        raise ValueError('Invalid dates')
    days = sorted({date.fromisoformat(day).isoformat() for day in dates})
    return ('🎫 寶可夢精英訓練家通行證有票\nエリートトレーナーズパス\n'
            '可售入園日期：\n' + '\n'.join(days) + '\n' + URL +
            '\n官網票種頁顯示可選購；未保留票券，請盡快確認。')


def main():
    text = message(json.loads(os.environ['POKEPARK_PAYLOAD']))
    chat = os.environ['TELEGRAM_CHAT_ID'].strip()
    if not chat.isdecimal() or int(chat) <= 0:
        raise RuntimeError('Private Telegram destination required')
    if api('getChat', {'chat_id': chat}).get('type') != 'private':
        raise RuntimeError('Refusing non-private Telegram destination')
    # Never use send(), which also supports the unrelated legacy group setting.
    for offset in range(0, len(text), 3900):
        api('sendMessage', {'chat_id': chat, 'text': text[offset:offset + 3900],
                            'link_preview_options': {'is_disabled': True}},
            allow_migration=False)
    print('Telegram accepted private PokéPark notification.')


if __name__ == '__main__':
    main()
