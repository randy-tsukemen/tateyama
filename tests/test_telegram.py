import unittest
from unittest.mock import patch, Mock
import requests
import telegram_notify as t

class TelegramTests(unittest.TestCase):
    def test_discover_only_unique_private_start(self):
        updates = [{'message': {'text': '/start', 'chat': {'id': 123, 'type': 'private'}}}]
        self.assertEqual(t.discover_chat(updates * 2), '123')
        for invalid in [[], updates + [{'message': {'text': '/start', 'chat': {'id': 456, 'type': 'private'}}}]]:
            with self.assertRaises(RuntimeError):
                t.discover_chat(invalid)

    def test_quiet_when_full_and_distinct_errors(self):
        report = {'date': '2026-10-10', 'results': [], 'errors': []}
        self.assertEqual(t.messages(report), [])
        report['errors'] = ['timeout']
        self.assertIn('不是空位通知', t.messages(report)[0])
        report['results'] = [{'available': True, 'hotel': '雷鳥莊', 'room': '相部屋', 'status': '1室', 'url': 'https://example.com'}]
        self.assertEqual(len(t.messages(report)), 2)
        self.assertIn('https://example.com', t.messages(report)[0])

    @patch.dict(t.os.environ, {'TELEGRAM_BOT_TOKEN': 'super-secret'})
    @patch.object(t.time, 'sleep')
    @patch.object(t.requests, 'post')
    def test_network_error_redacted_and_retried(self, post, sleep):
        post.side_effect = requests.ConnectionError('https://api.telegram.org/botsuper-secret/sendMessage')
        with self.assertRaises(RuntimeError) as error:
            t.api('sendMessage', {})
        self.assertNotIn('super-secret', str(error.exception))
        self.assertEqual(post.call_count, 3)

    @patch.dict(t.os.environ, {'TELEGRAM_BOT_TOKEN': 'secret'})
    @patch.object(t.time, 'sleep')
    @patch.object(t.requests, 'post')
    def test_rate_limit_then_success(self, post, sleep):
        post.side_effect = [Mock(status_code=429, json=lambda: {'parameters': {'retry_after': 3}}),
                            Mock(status_code=200, json=lambda: {'ok': True, 'result': {'message_id': 1}})]
        self.assertEqual(t.api('sendMessage', {}), {'message_id': 1})
        sleep.assert_called_once_with(3)
