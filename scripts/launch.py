"""Windows-friendly local launcher. Never seeds demo data or switches databases."""
from pathlib import Path
import argparse
import json
import os
import shutil
import socket
import subprocess
import sys
import time
import urllib.request
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
RUNTIME = ROOT / '.runtime'


def listening(port):
    try:
        with socket.create_connection(('127.0.0.1', port), timeout=1): return True
    except OSError: return False


def healthy(port):
    try:
        with urllib.request.urlopen(f'http://127.0.0.1:{port}/api/health', timeout=5) as response:
            data = json.load(response)
        return data.get('app') == 'College Fleet Command' and data.get('status') == 'healthy'
    except (OSError, ValueError): return False


def wait_for(check, label, child=None, seconds=90):
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if child is not None and child.poll() is not None:
            raise RuntimeError(f'{label} exited. See .runtime/launcher-{label}.log.')
        if check(): return
        time.sleep(1)
    raise RuntimeError(f'{label} did not become ready. See the logs in .runtime.')


def start(label, args, cwd, env=None):
    with (RUNTIME / f'launcher-{label}.log').open('ab') as log:
        child = subprocess.Popen(args, cwd=cwd, env=env, stdin=subprocess.DEVNULL,
                                 stdout=log, stderr=subprocess.STDOUT,
                                 creationflags=getattr(subprocess, 'CREATE_NO_WINDOW', 0))
    return child


def checked(args, cwd):
    # Database command output may contain connection strings on failure. Keep it private.
    with (RUNTIME / 'launcher-setup.log').open('ab') as log:
        result = subprocess.run(args, cwd=cwd, stdout=log, stderr=subprocess.STDOUT)
    if result.returncode:
        raise RuntimeError('Setup failed. Inspect .runtime/launcher-setup.log locally; it may contain private configuration.')


def scheduler_running():
    pid_file = RUNTIME / 'scheduler.pid'
    if not pid_file.exists(): return False
    try:
        pid = int(pid_file.read_text(encoding='utf-8-sig').strip())
        if os.name != 'nt': return False
        # Read only process inspection; never kill a process based on a recycled PID.
        command = f"(Get-CimInstance Win32_Process -Filter 'ProcessId = {pid}').CommandLine"
        result = subprocess.run(['powershell.exe', '-NoProfile', '-Command', command],
                                capture_output=True, text=True, timeout=10)
        return '-m fleet.scheduler' in result.stdout
    except (OSError, ValueError, subprocess.TimeoutExpired): return False


def launch(no_browser=False):
    if sys.version_info < (3, 11): raise RuntimeError('Install Python 3.11 or newer.')
    if not (ROOT / 'backend/.env').is_file():
        raise RuntimeError('Configure backend/.env using backend/.env.example first. Select Supabase or MySQL explicitly.')
    node = shutil.which('node')
    if not node: raise RuntimeError('Install Node.js 20.9+ (Node 22/24 recommended), then reopen this launcher.')
    next_bin = ROOT / 'frontend/node_modules/next/dist/bin/next'
    if not next_bin.exists():
        raise RuntimeError('Install web dependencies first: cd frontend && npm ci. See README for first-time setup.')
    sys.path.insert(0, str(ROOT / 'backend'))
    try:
        from fleet.config import settings
        from sqlalchemy.engine import make_url
    except ImportError:
        raise RuntimeError('Install backend dependencies first: python -m pip install -r backend/requirements.txt') from None
    if settings.DATABASE_MODE == 'mysql':
        url = make_url(settings.MYSQL_DATABASE_URL)
        if url.host in ('127.0.0.1', 'localhost') and url.port == 3307 and not listening(3307):
            base = RUNTIME / 'mysql-8.4.13-winx64'
            binary = base / 'bin/mysqld.exe'
            data = RUNTIME / 'mysql-data'
            if not binary.exists() or not data.is_dir():
                raise RuntimeError('Configured MySQL is unavailable. Start your database; no fallback will be used.')
            print('Starting the configured local MySQL database...', flush=True)
            child = start('mysql', [str(binary), f'--basedir={base}', f'--datadir={data}',
                                   '--port=3307', '--bind-address=127.0.0.1', '--mysqlx=0',
                                   f'--log-error={RUNTIME / "mysql-error.log"}'], ROOT)
            wait_for(lambda: listening(3307), 'mysql', child)
    for port in (8000, 3000):
        if listening(port) and not healthy(port):
            # Next may be compiling its first request. Retry before declaring a conflict.
            try: wait_for(lambda: healthy(port), f'port-{port}', seconds=20)
            except RuntimeError:
                raise RuntimeError(f'Port {port} is occupied but is not a healthy College Fleet Command service. Check its logs or close the conflicting app; no process was stopped.') from None
    if not listening(8000):
        print('Checking database and applying migrations...', flush=True)
        for command in (['fleet.cli', 'check-db'], ['alembic', 'upgrade', 'head'], ['fleet.cli', 'bootstrap']):
            checked([sys.executable, '-m', *command], ROOT / 'backend')
        child = start('api', [sys.executable, '-m', 'uvicorn', 'app.main:app', '--host', '127.0.0.1', '--port', '8000'], ROOT / 'backend')
        wait_for(lambda: healthy(8000), 'api', child)
    if not listening(3000):
        print('Starting the web app...', flush=True)
        env = os.environ.copy()
        env.update(API_INTERNAL_URL='http://127.0.0.1:8000', CFC_DIST_DIR='.cfc-next')
        child = start('web', [node, str(next_bin), 'dev', '--hostname', '127.0.0.1', '--port', '3000'], ROOT / 'frontend', env)
        wait_for(lambda: healthy(3000), 'web', child, seconds=120)
    # A healthy proxy alone does not prove the login page renders.
    with urllib.request.urlopen('http://127.0.0.1:3000/login', timeout=90) as response:
        if response.status != 200: raise RuntimeError('The login page did not render successfully.')
    if not scheduler_running():
        child = start('scheduler', [sys.executable, '-m', 'fleet.scheduler'], ROOT / 'backend')
        time.sleep(1)
        if child.poll() is not None: raise RuntimeError('Scheduler failed. See .runtime/launcher-scheduler.log.')
        (RUNTIME / 'scheduler.pid').write_text(str(child.pid))
    print('Ready: http://localhost:3000\nDatabase connected; web, API and scheduler available. No demo records added.', flush=True)
    if not no_browser: webbrowser.open('http://localhost:3000')


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--no-browser', action='store_true')
    args = parser.parse_args()
    RUNTIME.mkdir(exist_ok=True)
    # OS releases this lock even after a crash; repeated double clicks cannot race startup.
    with (RUNTIME / 'launcher.lock').open('a+b') as lock:
        if os.name == 'nt':
            import msvcrt
            lock.seek(0); lock.write(b'0'); lock.flush(); lock.seek(0)
            try: msvcrt.locking(lock.fileno(), msvcrt.LK_NBLCK, 1)
            except OSError:
                print('Another launcher is already starting the app. Please wait.'); return 0
        try:
            launch(args.no_browser)
            return 0
        except Exception as error:
            # Avoid accidentally printing environment credentials from third-party exceptions.
            print(f'Startup failed: {error}' if isinstance(error, RuntimeError) else
                  f'Startup failed ({type(error).__name__}). Check configuration and .runtime logs.')
            return 1


if __name__ == '__main__':
    raise SystemExit(main())
