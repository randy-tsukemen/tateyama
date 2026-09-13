from datetime import date, timedelta
import json
import unittest
from urllib.parse import parse_qs, urlparse
from monitor import RAICHO, check_dates, parse_raicho, parse_mikuri, exit_code

TARGET = date(2026, 10, 10)


def calendar(mark='×', day=None, month=None, target=TARGET,
             plan='PL00008095', room='RM00003893'):
    day = day or target.strftime('%d')
    month = month or target.strftime('%Y%m')
    data = dict(hotelCode='0000001203', pl=plan, rmcd001=room,
                ci=target.strftime('%Y%m%d'),
                co=(target + timedelta(days=1)).strftime('%Y%m%d'),
                lnum001='1_0_0_0_0', sumrm=1,
                planName='男女共用', calendarSalesYearList=[dict(calendarSalesYear=month,
                roomPriceCalendarList=[dict(roomSalesDate=day, roomSalesStatusKbn=mark,
                                           roomPrice=14050 if mark in ('○', '△') else 0)])])
    return 'Object.assign(data_ve, ' + json.dumps(data) + ');'


def raicho(mark='×', days=(10,)):
    labels = ''.join(f'<tr><td>房型{i}</td></tr>' for i in range(5))
    cells = ''.join(f'<tr><td>{mark if i == 2 else "×"}</td></tr>' for i in range(5))
    day_cells = ''.join(f'''<td><b>{day}</b>
    <div class="roomtbl"><table>{cells}</table></div></td>''' for day in days)
    return f'''<table class="caltbl"><tr><th class="month">2026年(令和8年)　10月</th></tr>
    <tr><td class="room"><table>{labels}</table></td>{day_cells}</tr></table>'''


class Response:
    def __init__(self, content):
        self.content = content

    def raise_for_status(self):
        pass


class Session:
    def __init__(self):
        self.urls = []

    def get(self, url, timeout):
        self.urls.append(url)
        if url == RAICHO:
            return Response(raicho(days=(10, 11)).encode('cp932'))
        query = parse_qs(urlparse(url).query)
        target = date.fromisoformat(
            f"{query['ci'][0][:4]}-{query['ci'][0][4:6]}-{query['ci'][0][6:]}")
        return Response(calendar(target=target, plan=query['pl'][0],
                                 room=query['rmcd001'][0]).encode())


class MonitorTests(unittest.TestCase):
    def test_two_dates_are_checked_with_one_raicho_request(self):
        session = Session()
        results, errors = check_dates(session, [TARGET, TARGET + timedelta(days=1)])
        self.assertEqual(errors, [])
        self.assertEqual(len(results), 16)
        self.assertEqual({row['date'] for row in results},
                         {'2026-10-10', '2026-10-11'})
        self.assertEqual(session.urls.count(RAICHO), 1)
        self.assertEqual(len(session.urls), 7)

    def test_mikuri_statuses(self):
        for mark, expected in [('○', True), ('△', True), ('×', False), ('－', False)]:
            with self.subTest(mark=mark):
                self.assertEqual(parse_mikuri(calendar(mark), TARGET, 'PL00008095',
                                             'RM00003893')['available'], expected)

    def test_mikuri_wrong_date_and_unknown_fail(self):
        for html in [calendar(day='11'), calendar(month='202609'), calendar('?'),
                     calendar().replace('20261010', '20260910'), '<html>Maintenance</html>']:
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_mikuri(html, TARGET, 'PL00008095', 'RM00003893')

    def test_raicho_full(self):
        self.assertFalse(any(r['available'] for r in parse_raicho(raicho(), TARGET)))

    def test_raicho_vacancy_link_and_room(self):
        result = parse_raicho(raicho('<a href="reserve.asp?date=20261010">2室</a>'), TARGET)
        self.assertEqual([r['room'] for r in result if r['available']], ['房型2'])
        self.assertTrue(result[2]['url'].endswith('reserve.asp?date=20261010'))

    def test_raicho_unknown_or_missing_fail(self):
        for html in [raicho('?'), raicho().replace('10月', '9月'), '<html>Error</html>']:
            with self.subTest(html=html), self.assertRaises(ValueError):
                parse_raicho(html, TARGET)

    def test_exit_codes_and_partial_failure(self):
        self.assertEqual(exit_code([{'available': False}], []), 0)
        self.assertEqual(exit_code([{'available': True}], []), 1)
        self.assertEqual(exit_code([], ['timeout']), 2)
        self.assertEqual(exit_code([{'available': True}], ['timeout']), 1)


if __name__ == '__main__':
    unittest.main()
