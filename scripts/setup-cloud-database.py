"""Initialise a dedicated cloud database using private configuration, never seed buses."""
from pathlib import Path
import argparse
import json
import os
import subprocess
import sys

root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser(description=__doc__)
parser.add_argument('--config',required=True,help='Private JSON containing DATABASE_URL, BOOTSTRAP_EMAIL, BOOTSTRAP_PASSWORD and SECRET_KEY')
args=parser.parse_args()
values=json.loads(Path(args.config).read_text(encoding='utf-8'))
required=('DATABASE_URL','BOOTSTRAP_EMAIL','BOOTSTRAP_PASSWORD','SECRET_KEY')
if any(not values.get(key) for key in required):raise SystemExit('Private configuration is missing required fields. No secrets were printed.')
os.environ.update({key:str(value) for key,value in values.items()})
os.environ.update(DATABASE_MODE='supabase',ENVIRONMENT='production',SERVERLESS='true',EVIDENCE_STORAGE='database')
sys.path.insert(0,str(root/'backend'))
from sqlalchemy import inspect,text
from fleet.db import engine
from fleet.cli import bootstrap
if engine.url.host in (None,'localhost','127.0.0.1','::1') or engine.url.database.endswith('_test'):
    raise SystemExit('Refusing a local/test destination. Choose the dedicated fleet cloud database.')
schema=values.get('DATABASE_SCHEMA') or None
tables=inspect(engine).get_table_names(schema=schema)
if tables and 'cfc_college' not in tables:
    # Managed Supabase projects can have system tables in public; unrelated app
    # tables indicate this is not the dedicated empty fleet project.
    if any(not name.startswith(('spatial_ref_sys','geography_columns','geometry_columns')) for name in tables):
        raise SystemExit('Target public schema is populated by another application. Refusing to initialise it.')
log=root/'.runtime/cloud-database-setup.log';log.parent.mkdir(exist_ok=True)
with log.open('ab') as output:
    result=subprocess.run([sys.executable,'-m','alembic','upgrade','head'],cwd=root/'backend',stdout=output,stderr=subprocess.STDOUT)
if result.returncode:raise SystemExit('Migration failed. Inspect the private setup log locally.')
bootstrap()
with engine.begin() as connection:
    for name in inspect(connection).get_table_names(schema=schema):
        if not name.startswith('cfc_'):continue
        quote=connection.dialect.identifier_preparer.quote
        quoted=(quote(schema)+'.' if schema else '')+quote(name)
        connection.execute(text(f'ALTER TABLE {quoted} ENABLE ROW LEVEL SECURITY'))
        for role in ('PUBLIC','anon','authenticated'):
            connection.execute(text(f'REVOKE ALL ON {quoted} FROM {role}'))
    count=connection.execute(text('SELECT count(*) FROM cfc_vehicles')).scalar()
    connection.execute(text('SELECT 1'))
print(f'Cloud migrations/admin/settings ready; vehicle count {count}. No operational records seeded.')
