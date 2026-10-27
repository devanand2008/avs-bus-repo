"""Rebuild only synthetic QA records after calculation/schema changes."""
import os,sys,json
from pathlib import Path
root=Path(__file__).resolve().parents[1];os.environ.update(json.loads((root/'.runtime/demo-env.json').read_text()));sys.path.insert(0,str(root/'backend'))
from alembic.config import Config
from alembic import command
os.chdir(root/'backend');command.upgrade(Config('alembic.ini'),'head')
from fleet.db import SessionLocal
from fleet.models import PlannedTrip,Vehicle,GPSPoint,now
from fleet.calculations import day_start,IST
from fleet.services import rebuild
from datetime import timedelta
with SessionLocal() as db:
    for p in db.query(PlannedTrip).filter_by(demo=True).all():
        if p.kind=='holiday':p.service_windows=[];continue
        p.service_windows=[{'start':(day_start(p.service_date)+timedelta(hours=h)).isoformat(),'end':(day_start(p.service_date)+timedelta(hours=h,seconds=max(2,int(p.trip_km/2))*240)).isoformat()} for h in (7,16)]
    db.commit();end=now().astimezone(IST).date()+timedelta(days=1)
    for v in db.query(Vehicle).filter_by(demo=True).all():rebuild(db,v.id,end-timedelta(days=61),end);db.commit()
print('Synthetic QA summaries refreshed; operational database untouched.')
