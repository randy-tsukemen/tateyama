"""Install/start/stop/status for the current macOS user's local monitor."""
import argparse
import json
import os
from pathlib import Path
import plistlib
import subprocess
import sys

ROOT = Path(__file__).resolve().parents[1]
DATA = Path.home() / 'Library/Application Support/PokeParkMonitor'
LABEL = 'jp.pokepark.elite-monitor'
PLIST = Path.home() / 'Library/LaunchAgents' / f'{LABEL}.plist'
DOMAIN = f'gui/{os.getuid()}'


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument('action', choices=['start', 'stop', 'status'])
    action = parser.parse_args().action
    if action == 'stop':
        subprocess.run(['launchctl', 'disable', DOMAIN + '/' + LABEL], check=True)
        result = subprocess.run(['launchctl', 'bootout', DOMAIN + '/' + LABEL], capture_output=True)
        if result.returncode:
            print('Service is not loaded, or launchctl could not stop it.')
        else:
            print('Monitor stopped and login restart disabled. Run start to resume.')
        return
    if action == 'status':
        result = subprocess.run(['launchctl', 'print', DOMAIN + '/' + LABEL], capture_output=True, text=True)
        print('Service loaded' if result.returncode == 0 else 'Service not loaded')
        for line in result.stdout.splitlines():
            if any(key in line for key in ('state =', 'pid =', 'last exit code =')):
                print(line.strip())
        for name in ('state.json', 'latest.json'):
            path = DATA / name
            if path.exists():
                data = json.loads(path.read_text())
                print(name, json.dumps({k: v for k, v in data.items() if k != 'statuses'}, ensure_ascii=False))
        return
    DATA.mkdir(parents=True, exist_ok=True, mode=0o700)
    PLIST.parent.mkdir(parents=True, exist_ok=True)
    if subprocess.run(['launchctl', 'print', DOMAIN + '/' + LABEL], capture_output=True).returncode == 0:
        print('Monitor already loaded; use status to inspect it.')
        return
    config = {
        'Label': LABEL,
        'ProgramArguments': [str(ROOT / '.venv/bin/python'), '-u', str(ROOT / 'pokepark_monitor.py')],
        'WorkingDirectory': str(ROOT),
        'RunAtLoad': True,
        'KeepAlive': True,
        'ThrottleInterval': 120,
        'ProcessType': 'Background',
        'EnvironmentVariables': {'PATH': '/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin:/usr/sbin:/sbin'},
        'StandardOutPath': '/dev/null',
        'StandardErrorPath': str(DATA / 'service-errors.log'),
    }
    PLIST.write_bytes(plistlib.dumps(config))
    os.chmod(PLIST, 0o600)
    subprocess.run(['launchctl', 'enable', DOMAIN + '/' + LABEL], check=True)
    subprocess.run(['launchctl', 'bootstrap', DOMAIN, str(PLIST)], check=True)
    print('Local monitor started. Keep this Mac awake and connected to the Internet.')


if __name__ == '__main__':
    main()
