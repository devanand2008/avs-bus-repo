"""Create a reproducible source-only handoff; never package credentials or private data."""
from pathlib import Path
import hashlib
import os
import zipfile

root = Path(__file__).resolve().parents[1]
output = root / 'output' / 'college-fleet-command-source.zip'
output.parent.mkdir(exist_ok=True)
excluded = {'node_modules', '__pycache__', 'legacy-ui', '.next', '.cfc-next', '.cfc-qa', '.cfc-vercel-check', '.cfc-next-tank',
            '.expo', 'dist', 'private-evidence', '.pytest_cache', 'venv', '.venv', 'uploads'}
files = []
for folder in ['backend/fleet', 'backend/alembic', 'backend/tests_command', 'frontend', 'mobile', 'shared', 'scripts', 'docs', 'logo']:
    for current, directories, names in os.walk(root / folder):
        directories[:] = [name for name in directories if name not in excluded
                          and Path(current, name) != root / 'frontend' / 'frontend']
        for name in names:
            path = Path(current, name)
            if name.startswith('.env') and name != '.env.example':
                continue
            if path.suffix in {'.db', '.sqlite3', '.pyc', '.log', '.tsbuildinfo'}:
                continue
            files.append(path)
for relative in ['README.md', '.gitignore', '.dockerignore', 'docker-compose.yml',
                 'start_college_fleet_command.bat', 'RUN_COLLEGE_FLEET.bat', 'run_tests.bat', 'backend/app/__init__.py',
                 'backend/app/main.py', 'backend/requirements.txt', 'backend/alembic.ini',
                 'backend/Dockerfile', 'backend/.dockerignore', 'backend/.env.example', 'backend/pytest.ini', 'vercel.json', '.vercelignore', 'backend/.python-version']:
    path = root / relative
    if path.is_file():
        files.append(path)
with zipfile.ZipFile(output, 'w', compression=zipfile.ZIP_DEFLATED) as archive:
    for path in sorted(set(files)):
        archive.write(path, path.relative_to(root).as_posix())
print(f'Source package: {len(set(files))} files; {output.stat().st_size:,} bytes')
print('SHA256:', hashlib.sha256(output.read_bytes()).hexdigest())
