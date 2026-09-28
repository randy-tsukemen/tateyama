from copy import deepcopy
from datetime import datetime
import json
from pathlib import Path
import unittest
from unittest.mock import Mock
from zoneinfo import ZoneInfo

from ticket_monitor import PRODUCTS, check_tickets, parse_schedule, validate_product
from telegram_notify import messages


def fixture(name='standard'):
    return json.loads((Path(__file__).parent / 'fixtures' / f'ticket_{name}.json').read_text())


class TicketTests(unittest.TestCase):
    def test_live_fixtures_and_cutoff(self):
        for name, code, count in [('standard', 'IT26000074', 14), ('bus', 'IT26000083', 4)]:
            data = fixture(name)
            rows = parse_schedule(data, code)
            self.assertEqual(len(rows), count)
            self.assertFalse(any(r['available'] for r in rows))
            self.assertTrue(all(r['departure'] < '10:00' for r in rows))

    def test_available_states_and_other_dates_do_not_leak(self):
        data = fixture()
        marks = data['weekInfoList'][0]['classNames'].split(',')
        marks[:6] = ['type1', 'type2', 'type3', 'type4', 'type5', 'type6']
        marks[14] = 'type1'  # 10:00 must be excluded.
        data['weekInfoList'][0]['classNames'] = ','.join(marks)
        data['weekInfoList'][1]['classNames'] = ','.join(['type1'] * len(marks))
        rows = parse_schedule(data, 'IT26000074')
        self.assertEqual([r['departure'] for r in rows if r['available']],
                         ['06:40', '06:50', '07:00'])
        alerts = messages(dict(results=rows, errors=[]))
        self.assertEqual(len(alerts), 1)
        self.assertIn('06:40、06:50、07:00 JST', alerts[0])
        self.assertIn('Standard WEB Ticket', alerts[0])
        self.assertNotIn('入住', alerts[0])

    def test_wrong_identity_and_broken_schema_fail(self):
        changes = [dict(resultCode='1'), dict(itemCode='other'), dict(webDirectionDiv='00'),
                   dict(weekBaseDate='20261012'), dict(labelWeekList=[]),
                   dict(weekSchedules=''), dict(weekSchedules='99:00'),
                   dict(weekInfoList=[{'classNames': 'unknown'}] * 3)]
        for change in changes:
            with self.subTest(change=change), self.assertRaises(ValueError):
                parse_schedule({**fixture(), **change}, 'IT26000074')
        data = deepcopy(fixture())
        data['labelWeekList'][0]['labelDate'] = '10/12'
        with self.assertRaises(ValueError):
            parse_schedule(data, 'IT26000074')

    def test_product_titles_and_partial_failure(self):
        html = ''.join(f'<div role="tabpanel"><h3 class="ticket-title">{title}</h3>'
                       f'<input class="itemCode" value="{code}"></div>'
                       for code, (title, _) in PRODUCTS.items())
        validate_product(html, 'IT26000074')
        with self.assertRaises(ValueError):
            validate_product(html.replace('スタンダード', 'different'), 'IT26000074')
        session = Mock()
        session.get.return_value.content = html.encode()
        response = Mock()
        response.json.return_value = fixture('bus')
        session.post.side_effect = [ValueError('unavailable'), response]
        now = datetime(2026, 9, 28, tzinfo=ZoneInfo('Asia/Tokyo'))
        rows, errors = check_tickets(session, now)
        self.assertEqual(len(rows), 4)
        self.assertEqual(len(errors), 1)
        self.assertIn('Standard WEB Ticket', errors[0])

    def test_expired_target_does_not_query(self):
        session = Mock()
        for now in [datetime(2026, 10, 11, 10), datetime(2026, 10, 12)]:
            self.assertEqual(check_tickets(session, now), ([], []))
        session.get.assert_not_called()
