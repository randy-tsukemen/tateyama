"""Bounded GitHub-only dispatcher; one controller at a time via workflow concurrency."""
from datetime import datetime, timezone
import json
import math
import os
import subprocess
import time

INTERVAL = 300
# Stop at midnight JST after the requested stay's check-in day.
STOP_AT = datetime(2026, 10, 10, 15, tzinfo=timezone.utc).timestamp()
CONTROLLER = 'dispatcher.yml'
MONITOR = 'availability.yml'


def api(path, payload=None):
    command = ['gh', 'api', path]
    if payload is not None:
        command += ['--method', 'POST', '--input', '-']
    response = subprocess.run(command, input=json.dumps(payload) if payload is not None else None,
                              text=True, capture_output=True, timeout=45)
    if response.returncode:
        # No automatic POST retries: an ambiguous response could duplicate a run.
        raise RuntimeError(f'GitHub API failed ({response.returncode}): {response.stderr.strip()}')
    return json.loads(response.stdout) if response.stdout.strip() else None


def enabled(repo):
    return all(api(f'repos/{repo}/actions/workflows/{name}')['state'] == 'active'
               for name in (CONTROLLER, MONITOR))


def wait_until(target, repo, clock=time.time, sleep=time.sleep, active=None):
    active = active or (lambda: enabled(repo))
    while clock() < STOP_AT:
        if not active():
            return False
        remaining = target - clock()
        if remaining <= 0:
            return True
        sleep(min(30, remaining, STOP_AT - clock()))
    return False


def next_tick(previous, now):
    # Skip missed ticks instead of sending a burst of catch-up requests.
    return max(previous + INTERVAL, now + INTERVAL)


def dispatch(repo, workflow, inputs=None):
    payload = {'ref': 'main'}
    if inputs:
        payload['inputs'] = inputs
    api(f'repos/{repo}/actions/workflows/{workflow}/dispatches', payload)


def main():
    repo = os.environ['GITHUB_REPOSITORY']
    if os.environ.get('NOTIFICATION_TEST') == 'true':
        dispatch(repo, MONITOR, {'test_notification': 'true'})
        print('Dispatched notification test; no continuation.', flush=True)
        return
    cycles = int(os.environ.get('DISPATCH_CYCLES') or '12')
    if not 1 <= cycles <= 12:
        raise ValueError('cycles must be between 1 and 12')
    now = time.time()
    due = float(os.environ.get('NEXT_AT') or now)
    if not math.isfinite(due) or due > now + INTERVAL + 60:
        raise ValueError('next_at is too far in the future')
    for _ in range(cycles):
        if not wait_until(due, repo):
            print('Stopped: target date expired or a workflow was disabled.', flush=True)
            return
        dispatch(repo, MONITOR)
        stamp = datetime.now(timezone.utc).isoformat()
        print(f'{stamp}: dispatched {MONITOR}', flush=True)
        with open(os.environ['GITHUB_STEP_SUMMARY'], 'a') as summary:
            summary.write(f'- {stamp}: dispatched `{MONITOR}`\n')
        due = next_tick(due, time.time())
    if due < STOP_AT and enabled(repo):
        dispatch(repo, CONTROLLER, {'next_at': str(due), 'cycles': '12'})
        print(f'Continuation requested; next check due at {due}.', flush=True)
    else:
        print('No continuation: disabled or target date expired.', flush=True)


if __name__ == '__main__':
    main()
