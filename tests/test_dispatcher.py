import importlib.util
import unittest
from unittest.mock import patch

spec = importlib.util.spec_from_file_location('dispatcher', 'scripts/dispatch_monitor.py')
d = importlib.util.module_from_spec(spec)
spec.loader.exec_module(d)


class DispatcherTests(unittest.TestCase):
    def test_skips_missed_ticks(self):
        self.assertEqual(d.next_tick(100, 800), 1100)
        self.assertEqual(d.next_tick(100, 101), 401)

    def test_disable_stops_during_wait(self):
        times = iter([100, 100, 100, 130])
        with patch.object(d, 'STOP_AT', 1000):
            self.assertFalse(d.wait_until(400, 'owner/repo', clock=lambda: next(times),
                                         sleep=lambda _: None, active=iter([True, False]).__next__))

    def test_expiry_stops(self):
        with patch.object(d, 'STOP_AT', 100):
            self.assertFalse(d.wait_until(200, 'owner/repo', clock=lambda: 100,
                                         active=lambda: True))

    def test_handoff_and_monitor_dispatch(self):
        env = {'GITHUB_REPOSITORY': 'owner/repo', 'DISPATCH_CYCLES': '1',
               'NEXT_AT': '', 'GITHUB_STEP_SUMMARY': '/dev/null'}
        with patch.dict(d.os.environ, env), patch.object(d, 'wait_until', return_value=True), \
             patch.object(d, 'enabled', return_value=True), patch.object(d, 'dispatch') as send, \
             patch.object(d.time, 'time', return_value=100):
            d.main()
        self.assertEqual(send.call_args_list[0].args, ('owner/repo', d.MONITOR))
        self.assertEqual(send.call_args_list[1].args,
                         ('owner/repo', d.CONTROLLER, {'next_at': '400.0', 'cycles': '12'}))

    def test_monitor_failure_does_not_get_silently_ignored(self):
        with patch.object(d.subprocess, 'run') as run:
            run.return_value.returncode = 1
            run.return_value.stderr = 'API unavailable'
            with self.assertRaises(RuntimeError):
                d.dispatch('owner/repo', d.MONITOR)
            self.assertEqual(run.call_count, 1)
