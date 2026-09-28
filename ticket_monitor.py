"""Read the same public availability endpoint used by the ticket home page.

The POST only queries stock; it does not start a reservation or require login.
"""
from datetime import date, time
import re

from bs4 import BeautifulSoup

HOME = 'https://tateyama-kurobe-webservice.jp/AlpenTour/html/VW001W0010.html'
API = 'https://tateyama-kurobe-webservice.jp/AlpenTour/bizrule/json/BR001W0020'
TARGET = date(2026, 10, 11)
BEFORE = time(10)
PRODUCTS = {
    'IT26000074': ('スタンダード WEBきっぷ', 'Standard WEB Ticket'),
    'IT26000083': ('室堂直行バス（10/10-11）', 'Murodo Direct Bus (Oct 10–11)'),
}
STATUSES = {'type1': '残席あり', 'type2': '残席あり', 'type3': '残りわずか',
            'type4': '残席なし', 'type5': '次回以降発売予定', 'type6': '設定なし'}


def validate_product(html, code):
    soup = BeautifulSoup(html, 'html.parser')
    matches = soup.select(f'input.itemCode[value="{code}"]')
    if len(matches) != 1:
        raise ValueError('Ticket product missing or duplicated on home page')
    panel = matches[0].find_parent(attrs={'role': 'tabpanel'})
    title = panel.select_one('.ticket-title') if panel else None
    if not title or title.get_text(strip=True) != PRODUCTS[code][0]:
        raise ValueError('Ticket product code/title changed')


def parse_schedule(data, code, target=TARGET, before=BEFORE):
    expected = dict(resultCode='0', itemCode=code, webDirectionDiv='05',
                    ridingTimeDesignnatedFlg='1', weekBaseDate=target.strftime('%Y%m%d'))
    if any(data.get(key) != value for key, value in expected.items()):
        raise ValueError('Ticket API returned an error or wrong product/date/direction')
    labels, days = data.get('labelWeekList'), data.get('weekInfoList')
    if not isinstance(labels, list) or not isinstance(days, list) or len(labels) != len(days):
        raise ValueError('Ticket timetable date columns missing or mismatched')
    if not labels or labels[0].get('labelDate') != f'{target.month:02}/{target.day:02}':
        raise ValueError('Ticket timetable target date missing')
    times = data.get('weekSchedules', '').split(',')
    marks = days[0].get('classNames', '').split(',')
    if not times or len(times) != len(marks) or len(set(times)) != len(times):
        raise ValueError('Ticket timetable time/status columns mismatched')
    rows = []
    for departure, mark in zip(times, marks):
        if not re.fullmatch(r'[0-2][0-9]:[0-5][0-9]', departure) or mark not in STATUSES:
            raise ValueError('Unknown ticket departure time or availability status')
        if time.fromisoformat(departure) >= before:
            continue
        rows.append(dict(kind='ticket', date=str(target), product_code=code,
                         hotel='立山黑部阿爾卑斯路線', room=PRODUCTS[code][1],
                         departure=departure, origin='Tateyama',
                         available=mark in ('type1', 'type2', 'type3'),
                         status=STATUSES[mark], url=HOME))
    if not rows:
        raise ValueError('No timetable entries before cutoff; manual verification required')
    return rows


def check_tickets(session, now):
    if now.date() > TARGET or (now.date() == TARGET and now.time() >= BEFORE):
        return [], []
    results, errors = [], []
    try:
        response = session.get(HOME, timeout=(15, 45))
        response.raise_for_status()
        html = response.content.decode('utf-8')
    except Exception as exc:
        return [], [f'{TARGET} WEB Ticket：{exc}']
    for code, (_, name) in PRODUCTS.items():
        try:
            validate_product(html, code)
            response = session.post(API, data=dict(
                itemCode=code, webDirectionDiv='05', ridingTimeDesignnatedFlg='1',
                baseDate=TARGET.strftime('%Y%m01'), weekBaseDate=TARGET.strftime('%Y%m%d'),
                layoutDiv='0', calendarInfoFlg='0'), timeout=(15, 45))
            response.raise_for_status()
            rows = parse_schedule(response.json(), code)
            results.extend(r for r in rows if now.date() < TARGET or
                           time.fromisoformat(r['departure']) > now.time())
        except Exception as exc:
            errors.append(f'{TARGET} {name}：{exc}')
    return results, errors
