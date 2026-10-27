"""Repeat the local checks without relying on PowerShell execution policy."""
from pathlib import Path
import shutil
import subprocess
import sys

root = Path(__file__).resolve().parents[1]
npm = shutil.which('npm.cmd') or shutil.which('npm')
if not npm:
    raise SystemExit('Node.js/npm is required for web and mobile checks.')
checks = [
    (root, [sys.executable, 'scripts/test_launcher.py']),
    (root / 'backend', [sys.executable, '-m', 'pytest', 'tests_command', '-q']),
    (root / 'frontend', [npm, 'run', 'build']),
    (root / 'mobile', [npm, 'run', 'typecheck']),
    (root / 'mobile', [npm, 'run', 'export']),
]
for folder, command in checks:
    print(f'Checking {folder.name}: {" ".join(command[1:])}', flush=True)
    result = subprocess.run(command, cwd=folder)
    if result.returncode: raise SystemExit(result.returncode)
print('All local automated checks passed. Vendor and physical-device validation are separate.')
