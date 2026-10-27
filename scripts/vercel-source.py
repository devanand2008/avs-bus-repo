"""Emit only reviewed deployment source for the authenticated Vercel connector.

No local configuration, databases, uploaded evidence, native signing files or
runtime directories are eligible. Redirect output to a private local file if needed.
"""
from pathlib import Path
import base64
import json

root=Path(__file__).resolve().parents[1]
paths=[]
for name in ('frontend/src','frontend/public','shared','backend/fleet','backend/alembic'):
    for path in (root/name).rglob('*'):
        if path.is_file() and '__pycache__' not in path.parts and path.suffix not in ('.pyc','.log'):
            paths.append(path)
for name in ('vercel.json','frontend/package.json','frontend/package-lock.json','frontend/next.config.js',
             'frontend/next-env.d.ts','frontend/tsconfig.json','frontend/postcss.config.js','frontend/tailwind.config.ts',
             'backend/app/__init__.py','backend/app/main.py','backend/requirements.txt','backend/alembic.ini','backend/.python-version'):
    path=root/name
    if path.exists():paths.append(path)
files=[]
for path in sorted(set(paths)):
    if path.name.startswith('.env') or path.suffix in ('.db','.sqlite3'):raise RuntimeError('Private file in source manifest.')
    files.append({'file':path.relative_to(root).as_posix(),'data':base64.b64encode(path.read_bytes()).decode(),'encoding':'base64'})
print(json.dumps(files,separators=(',',':')))
