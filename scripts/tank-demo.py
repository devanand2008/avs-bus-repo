"""Opt-in, disposable local MySQL data for visual tank/refill verification.

Usage: python scripts/tank-demo.py --config .runtime/tank-demo-env.json
The config must name an EMPTY localhost database ending in _demo. Never connects
to Supabase or a production database. Passwords remain in the private config.
"""
import argparse
import os
import sys
import json
from pathlib import Path
from datetime import timedelta
from sqlalchemy.engine import make_url

root = Path(__file__).resolve().parents[1]
args = argparse.ArgumentParser()
args.add_argument('--config', required=True)
config = json.loads(Path(args.parse_args().config).read_text(encoding='utf-8-sig'))
url = make_url(config['MYSQL_DATABASE_URL'])
if url.host not in ('127.0.0.1', 'localhost') or not url.database.endswith('_demo') or url.username == 'root':
    raise SystemExit('Only a dedicated, non-root localhost *_demo database is allowed.')
os.environ.update({k:str(v) for k,v in config.items()})
sys.path.insert(0, str(root/'backend'))
from fleet.db import Base, engine, SessionLocal
from fleet.models import *
from fleet.auth import password_hash
from fleet.calculations import *
from fleet.services import rebuild, summarise_bus

Base.metadata.create_all(engine)
with SessionLocal() as db:
    if db.query(Vehicle).first() or db.query(User).first():
        raise SystemExit('Requires an empty synthetic database; existing records were not changed.')
    db.add(College(name='AVS Engineering College · SYNTHETIC QA',short_name='AVSEC QA',demo=True))
    users={}
    for role in ('SYSTEM_ADMIN','CORRESPONDENT','TRANSPORT_VERIFIER','FUELLER'):
        u=User(email=role.lower()+'@tank-demo.example.com',name='Synthetic '+role,role=role,
               password_hash=password_hash(config['BOOTSTRAP_PASSWORD']),demo=True)
        db.add(u);db.flush();users[role]=u.id
    admin=users['SYSTEM_ADMIN']; verifier=users['TRANSPORT_VERIFIER']
    day=now().astimezone(IST).date()-timedelta(days=1)
    start=day_start(day); end=start+timedelta(days=1)
    window_start=start+timedelta(hours=9);window_end=window_start+timedelta(minutes=80)
    route=Route(code='SYNTHETIC-80',name='Synthetic 80 km QA route',trip_km=80,scope='one_way',created_by=admin,approved_by=verifier,demo=True)
    db.add(route);db.flush()
    driver=Driver(employee_id='SYNTHETIC-QA',name='Synthetic QA Driver',demo=True);db.add(driver);db.flush()
    ids=[]
    for n in range(1,4):
        v=Vehicle(bus_number=f'QA-{n:03}',registration=f'SYNTHETIC-TANK-{n:03}',tank_capacity_l=220,safe_fill_l=200,operating_target_l=100,demo=True)
        db.add(v);db.flush();ids.append(v.id)
        db.add(Assignment(vehicle_id=v.id,driver_id=driver.id,route_id=route.id,starts_at=start,reason='Synthetic QA assignment'))
        db.add(DeviceMapping(vehicle_id=v.id,provider='synthetic_qa',device_id=f'QA-{n}',starts_at=start,cadence_seconds=60))
        db.add(Mileage(vehicle_id=v.id,kmpl=4,effective_from=start,reason='Synthetic 4 km/L model',created_by=admin,approved_by=verifier))
        db.add(PlannedTrip(vehicle_id=v.id,route_id=route.id,service_date=day,trips=1,trip_km=80,scope='one_way',service_windows=[{'start':window_start.isoformat(),'end':window_end.isoformat()}],created_by=admin,approved_by=verifier))
        if n==3:
            continue # No reading/no telemetry: all tank recommendations stay unknown.
        db.add(TankReading(vehicle_id=v.id,occurred_at=start,litres=38,quality='measured',source='dip',stable=True,reason='Synthetic verified opening',created_by=admin,verified_by=verifier))
        degree_km=geodesic_km(0,78,0,79)
        for i in range(81):
            db.add(GPSPoint(vehicle_id=v.id,provider='synthetic_qa',device_id=f'QA-{n}',event_id=f'QA-{n}-{i}',fix_at=window_start+timedelta(minutes=i),lat=0,lon=q(D(78)+D(i)/degree_km,'.0000001'),speed=60,speed_kph=60,source_unit='kmh',ignition=True,raw={'synthetic':True}))
        if n==2:
            db.add(FuelEvent(vehicle_id=v.id,occurred_at=window_end+timedelta(hours=1),litres=50,
                supplier='SYNTHETIC QA PUMP',invoice='SYNTHETIC-50',idempotency_key='SYNTHETIC-TANK-50',
                status='posted',pre_stock_l=18,post_stock_l=68,stock_quality='measured',created_by=users['FUELLER'],verified_by=verifier))
            db.add(TankReading(vehicle_id=v.id,occurred_at=end,litres=68,quality='measured',source='dip',stable=True,reason='Synthetic verified closing after partial fill',created_by=admin,verified_by=verifier))
    db.flush()
    for vid in ids:rebuild(db,vid,day,day+timedelta(days=1))
    db.commit()
    rows=[summarise_bus(db,db.get(Vehicle,vid),day,day+timedelta(days=1)) for vid in ids]
    assert abs(D(rows[0]['stock_l'])-18)<D('.001') and abs(D(rows[0]['top_up_l'])-82)<D('.001')
    assert D(rows[1]['stock_l'])==68 and D(rows[1]['top_up_l'])==32
    assert rows[2]['stock_l'] is None and rows[2]['top_up_l'] is None
    print(json.dumps({'synthetic_only':True,'start':str(day),'end':str(day+timedelta(days=1)),
        'buses':[{'vehicle_id':b['vehicle_id'],'bus_number':b['bus_number'],'gps_km':b['gps_km'],
                  'stock_l':b['stock_l'],'stock_quality':b['stock_quality'],'top_up_l':b['top_up_l']} for b in rows]},indent=2))
