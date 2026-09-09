from datetime import date
import json
import unittest
from monitor import parse_raicho, parse_mikuri, exit_code

TARGET = date(2026, 10, 10)


def calendar(mark='×', day='10', month='202610'):
    data = dict(hotelCode='0000001203', pl='PL00008095', rmcd001='RM00003893',
                ci='20261010', co='20261011', lnum001='1_0_0_0_0', sumrm=1,
                planName='男女共用', calendarSalesYearList=[dict(calendarSalesYear=month,
                roomPriceCalendarList=[dict(roomSalesDate=day, roomSalesStatusKbn=mark,
                                           roomPrice=14050 if mark in ('○', '△') else 0)])])
    return 'Object.assign(data_ve, ' + json.dumps(data) + ');'


def raicho(mark='×'):
    labels = ''.join(f'<tr><td>房型{i}</td></tr>' for i in range(5))
    cells = ''.join(f'<tr><td>{mark if i == 2 else "×"}</td></tr>' for i in range(5))
    return f'''<table class="caltbl"><tr><th class="month">2026年(令和8年)　10月</th></tr>
    <tr><td class="room"><table>{labels}</table></td><td><b>10</b>
    <div class="roomtbl"><table>{cells}</table></div></td></tr></table>'''


class MonitorTests(unittest.TestCase):
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
