"""Serve the explicit localhost synthetic QA database; never a live deployment."""
import argparse
import json
import os
import sys
from pathlib import Path
from sqlalchemy.engine import make_url
parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
config=json.loads(Path(parser.parse_args().config).read_text(encoding='utf-8-sig'))
url=make_url(config['MYSQL_DATABASE_URL'])
if url.host not in ('127.0.0.1','localhost') or not url.database.endswith('_demo') or url.username=='root':
    raise SystemExit('Only a dedicated localhost synthetic database is allowed.')
os.environ.update({k:str(v) for k,v in config.items()})
sys.path.insert(0,str(Path(__file__).resolve().parents[1]/'backend'))
import uvicorn
uvicorn.run('app.main:app',host='127.0.0.1',port=8001)
