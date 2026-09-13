import unittest
from unittest.mock import patch, Mock
import requests
import telegram_notify as t

class TelegramTests(unittest.TestCase):
    def test_group_discovery_requires_title_command_and_owner(self):
        good = {'message': {'text': '/start@bot', 'from': {'id': 123},
                           'chat': {'id': -99, 'type': 'supergroup', 'title': 'Trip'}}}
        self.assertEqual(t.discover_group([good, good], 'Trip', 'bot', '123'), '-99')
        for title, bot, owner in [('Other', 'bot', '123'), ('Trip', 'other', '123'),
                                  ('Trip', 'bot', '456')]:
            with self.assertRaises(RuntimeError):
                t.discover_group([good], title, bot, owner)

    @patch.dict(t.os.environ, {'TELEGRAM_CHAT_ID': '123', 'TELEGRAM_GROUP_ID': '-99'})
    @patch.object(t, 'api')
    def test_both_destinations_are_attempted_on_private_failure(self, api):
        api.side_effect = [RuntimeError('failed'), {'message_id': 1}]
        with self.assertRaises(RuntimeError):
            t.send('test')
        self.assertEqual([c.args[1]['chat_id'] for c in api.call_args_list], ['123', '-99'])

    @patch.dict(t.os.environ, {'TELEGRAM_CHAT_ID': '123', 'TELEGRAM_GROUP_ID': '123'})
    @patch.object(t, 'api')
    def test_duplicate_destination_only_sent_once(self, api):
        t.send('test')
        self.assertEqual(api.call_count, 1)

    def test_discover_only_unique_private_start(self):
        updates = [{'message': {'text': '/start', 'chat': {'id': 123, 'type': 'private'}}}]
        self.assertEqual(t.discover_chat(updates * 2), '123')
        for invalid in [[], updates + [{'message': {'text': '/start', 'chat': {'id': 456, 'type': 'private'}}}]]:
            with self.assertRaises(RuntimeError):
                t.discover_chat(invalid)

    def test_quiet_when_full_and_distinct_errors(self):
        report = {'dates': ['2026-10-10', '2026-10-11'], 'results': [], 'errors': []}
        self.assertEqual(t.messages(report), [])
        report['errors'] = ['timeout']
        self.assertIn('不是空位通知', t.messages(report)[0])
        report['results'] = [{'date': '2026-10-11', 'available': True, 'hotel': '雷鳥莊',
                              'room': '相部屋', 'status': '1室', 'url': 'https://example.com'}]
        self.assertEqual(len(t.messages(report)), 2)
        self.assertIn('https://example.com', t.messages(report)[0])
        self.assertIn('2026-10-11', t.messages(report)[0])

    @patch.dict(t.os.environ, {'TELEGRAM_BOT_TOKEN': '123:super-secret'})
    @patch.object(t.time, 'sleep')
    @patch.object(t.requests, 'post')
    def test_network_error_redacted_and_retried(self, post, sleep):
        post.side_effect = requests.ConnectionError('https://api.telegram.org/bot123:super-secret/sendMessage')
        with self.assertRaises(RuntimeError) as error:
            t.api('sendMessage', {})
        self.assertNotIn('123:super-secret', str(error.exception))
        self.assertEqual(post.call_count, 3)

    @patch.dict(t.os.environ, {'TELEGRAM_BOT_TOKEN': '123:secret'})
    @patch.object(t.time, 'sleep')
    @patch.object(t.requests, 'post')
    def test_rate_limit_then_success(self, post, sleep):
        post.side_effect = [Mock(status_code=429, json=lambda: {'parameters': {'retry_after': 3}}),
                            Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 1}})]
        self.assertEqual(t.api('sendMessage', {}), {'message_id': 1})
        sleep.assert_called_once_with(3)
