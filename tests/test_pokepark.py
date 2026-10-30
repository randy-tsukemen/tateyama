from datetime import date
import json
import os
from pathlib import Path
import unittest
from unittest.mock import patch

from pokepark_monitor import parse_calendar, parse_elite, process_report
import pokepark_notify

HTML = (Path(__file__).parent / 'fixtures/pokepark-sold-out.html').read_text()


class StockTests(unittest.TestCase):
    def test_sold_out_elite_even_with_other_tickets(self):
        self.assertFalse(parse_elite(HTML, '2026-11-17'))

    def test_available_requires_both_enabled_and_positive_stock(self):
        available = HTML.replace('disabled="disabled"', '').replace('残り×', '残り△')
        self.assertTrue(parse_elite(available, '2026-11-17'))
        with self.assertRaises(ValueError):
            parse_elite(HTML.replace('残り×', '残り△'), '2026-11-17')
        with self.assertRaises(ValueError):
            parse_elite(HTML, '2026-11-18')
        with self.assertRaises(ValueError):
            parse_elite(HTML.replace('エリート', '別の'), '2026-11-17')

    def test_calendar_stock_is_only_a_candidate(self):
        data = {'result': 'OK', 'nextMonthFlg': 0, 'dates': [
            {'date': '2026-11-17', 'closedFlg': 0, 'linkFlg': 1, 'pattern': '1', 'stockCount': 4},
            {'date': '2026-11-18', 'closedFlg': 0, 'linkFlg': 1, 'pattern': '1', 'stockCount': 0}]}
        known, candidates, more = parse_calendar(data, '2026-11', date(2026, 10, 30))
        self.assertEqual(known, {'2026-11-18': False})
        self.assertEqual(candidates, ['2026-11-17'])
        self.assertFalse(more)
        data['dates'][0]['stockCount'] = '4'
        with self.assertRaises(ValueError):
            parse_calendar(data, '2026-11', date(2026, 10, 30))

    def test_restock_dedup_and_failures(self):
        state, sent = {}, []
        report = {'statuses': {'2099-01-01': True}, 'errors': []}
        process_report(report, state, sent.append)
        process_report(report, state, sent.append)
        self.assertEqual(len(sent), 1)
        with self.assertRaises(RuntimeError):
            process_report({'statuses': {}, 'errors': ['2099-01-01']}, state, sent.append)
        process_report(report, state, sent.append)
        self.assertEqual(len(sent), 1)
        process_report({'statuses': {'2099-01-01': False}, 'errors': []}, state, sent.append)
        process_report(report, state, sent.append)
        self.assertEqual(len(sent), 2)

    def test_delivery_failure_does_not_mark_available_as_notified(self):
        state = {}
        def fail(payload):
            raise RuntimeError('Failed')
        with self.assertRaises(RuntimeError):
            process_report({'statuses': {'2099-01-01': True}, 'errors': []}, state, fail)
        self.assertFalse(state['statuses'].get('2099-01-01'))


class PrivateNotificationTests(unittest.TestCase):
    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '12345', 'TELEGRAM_GROUP_ID': '-100999',
                             'POKEPARK_PAYLOAD': json.dumps({'kind': 'started'})})
    @patch('pokepark_notify.api')
    def test_group_never_contacted(self, api):
        api.return_value = {'type': 'private'}
        pokepark_notify.main()
        self.assertEqual(api.call_count, 2)
        self.assertTrue(all(c.args[1]['chat_id'] == '12345' for c in api.call_args_list))
        self.assertEqual(api.call_args_list[1].kwargs['allow_migration'], False)

    @patch.dict(os.environ, {'TELEGRAM_CHAT_ID': '12345',
                             'POKEPARK_PAYLOAD': json.dumps({'kind': 'started'})})
    @patch('pokepark_notify.api')
    def test_reject_non_private_chat(self, api):
        api.return_value = {'type': 'supergroup'}
        with self.assertRaises(RuntimeError):
            pokepark_notify.main()
        self.assertEqual(api.call_count, 1)


if __name__ == '__main__':
    unittest.main()
