"""Add one coherent, explicitly synthetic shortage example to the local tank QA DB."""
import argparse,json,os,sys
from pathlib import Path
from datetime import timedelta
from sqlalchemy.engine import make_url
root=Path(__file__).resolve().parents[1]
parser=argparse.ArgumentParser();parser.add_argument('--config',required=True)
cfg=json.loads(Path(parser.parse_args().config).read_text(encoding='utf-8-sig'))
url=make_url(cfg['MYSQL_DATABASE_URL'])
if url.host not in ('127.0.0.1','localhost') or not url.database.endswith('_demo') or url.username=='root':
    raise SystemExit('Requires a dedicated non-root localhost *_demo database.')
os.environ.update({k:str(v) for k,v in cfg.items()});sys.path.insert(0,str(root/'backend'))
from fleet.db import SessionLocal
from fleet.models import *
from fleet.calculations import *
from fleet.services import rebuild,summarise_bus
with SessionLocal() as db:
    if not (c:=db.query(College).first()) or not c.demo:raise SystemExit('Requires the synthetic tank demo.')
    if db.query(Vehicle).filter_by(bus_number='QA-004').first():raise SystemExit('QA-004 already exists; no records changed.')
    prior=db.query(Vehicle).filter_by(bus_number='QA-001',demo=True).one()
    day=db.query(PlannedTrip).filter_by(vehicle_id=prior.id).first().service_date
    a=day_start(day);b=a+timedelta(days=1);first=a+timedelta(hours=9);last=first+timedelta(hours=8)
    users={u.role:u.id for u in db.query(User).all()};admin=users['SYSTEM_ADMIN'];verifier=users['TRANSPORT_VERIFIER']
    v=Vehicle(bus_number='QA-004',registration='SYNTHETIC-SHORTAGE',tank_capacity_l=300,safe_fill_l=280,operating_target_l=200,demo=True);db.add(v);db.flush()
    route=Route(code='QA-800',name='Synthetic range review route',trip_km=800,scope='day',created_by=admin,approved_by=verifier,demo=True);db.add(route);db.flush()
    db.add(Assignment(vehicle_id=v.id,route_id=route.id,starts_at=a,reason='Synthetic shortage review'))
    db.add(DeviceMapping(vehicle_id=v.id,provider='synthetic_qa',device_id='QA-4',starts_at=a,cadence_seconds=60))
    db.add(Mileage(vehicle_id=v.id,kmpl=4,effective_from=a,reason='Synthetic approved 4 km/L',created_by=admin,approved_by=verifier))
    db.add(PlannedTrip(vehicle_id=v.id,route_id=route.id,service_date=day,trips=1,trip_km=800,scope='day',service_windows=[{'start':first.isoformat(),'end':last.isoformat()}],created_by=admin,approved_by=verifier))
    for timestamp in (a,b):
        db.add(TankReading(vehicle_id=v.id,occurred_at=timestamp,litres=40,quality='measured',source='dip',stable=True,uncertainty_l=1,reason='Synthetic verified boundary',created_by=admin,verified_by=verifier))
    db.add(FuelEvent(vehicle_id=v.id,occurred_at=a+timedelta(hours=8),litres=200,pre_stock_l=40,post_stock_l=240,stock_quality='measured',supplier='SYNTHETIC QA',invoice='QA-SHORTAGE-200',idempotency_key='QA-SHORTAGE-200',status='posted',created_by=users['FUELLER'],verified_by=verifier))
    per_degree=geodesic_km(0,78,0,79)
    for i in range(481):
        db.add(GPSPoint(vehicle_id=v.id,provider='synthetic_qa',device_id='QA-4',event_id=f'QA-4-{i}',fix_at=first+timedelta(minutes=i),lat=0,lon=q(D(78)+D(i)*D('1.5')/per_degree,'.0000001'),speed=90,speed_kph=90,source_unit='kmh',ignition=True,raw={'synthetic':True}))
    db.flush();rebuild(db,v.id,day,day+timedelta(days=1));db.commit()
    summary=summarise_bus(db,v,day,day+timedelta(days=1))
    assert abs(D(summary['gps_km'])-720)<D('.001')
    assert abs(D(summary['km_shortage_km'])-80)<D('.001') and abs(D(summary['diesel_shortage_l'])-20)<D('.001')
    print(json.dumps({k:summary[k] for k in ('vehicle_id','bus_number','gps_km','planned_km','disappearance_l','expected_l','km_shortage_km','diesel_shortage_l','route_shortage_km','shortage_status')},indent=2))
