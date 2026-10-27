"""Explicit bootstrap and opt-in demonstration commands. Never auto-seed a live database."""
import argparse
import os
from pathlib import Path
from datetime import timedelta
from decimal import Decimal
from fleet.config import settings
from fleet.db import SessionLocal,engine
from fleet.models import *
from fleet.auth import password_hash,ROLES
from fleet.calculations import *
from fleet.services import rebuild,audit

def bootstrap():
    from pydantic import TypeAdapter,EmailStr
    email=settings.BOOTSTRAP_EMAIL.lower();password=settings.BOOTSTRAP_PASSWORD
    TypeAdapter(EmailStr).validate_python(email)
    if len(password)<12:raise RuntimeError('Set BOOTSTRAP_EMAIL and BOOTSTRAP_PASSWORD (at least 12 characters) in backend/.env. No default admin password is shipped.')
    with SessionLocal() as db:
        if not db.query(College).first():db.add(College(name=settings.COLLEGE_NAME,short_name=settings.COLLEGE_SHORT_NAME))
        if not db.query(User).filter_by(email=email).first():
            db.add(User(email=email,name='College Administrator',role='SYSTEM_ADMIN',password_hash=password_hash(password)))
        db.commit();print('Bootstrap complete. Empty fleet; use the administrator account configured in backend/.env.')

def demo(acknowledge):
    if not acknowledge:raise RuntimeError('Demo requires --synthetic-only. Use a separate database. This creates fabricated demonstration records.')
    with SessionLocal() as db:
        if db.query(Vehicle).first():raise RuntimeError('Demo requires an empty fleet database; it will not add data to an operational fleet.')
        admin=db.query(User).filter_by(role='SYSTEM_ADMIN').first()
        if not admin:raise RuntimeError('Bootstrap first.')
        password=os.environ.get('DEMO_PASSWORD','')
        if len(password)<12:raise RuntimeError('Set DEMO_PASSWORD to at least 12 characters; it is used for synthetic role accounts.')
        users={}
        for role in sorted(ROLES-{'SYSTEM_ADMIN'}):
            u=User(email=f'{role.lower()}@demo.example.com',name=f'Synthetic {role.replace("_"," ").title()}',role=role,password_hash=password_hash(password),demo=True);db.add(u);db.flush();users[role]=u
        reviewer=users['TRANSPORT_VERIFIER'];correspondent=users['CORRESPONDENT'];today=now().astimezone(IST).date();start=today-timedelta(days=60)
        routes=[]
        for i,name in enumerate(['Salem North','Attur Corridor','Omalur','Rasipuram','Mettur','Sankagiri']):
            route=Route(code=f'DEMO-R{i+1:02}',name=f'Synthetic {name}',trip_km=D(30+i*5),scope='round_trip',stops=['Synthetic depot','Synthetic stop','Campus'],geometry={'type':'LineString','coordinates':[[78.16,11.65],[78.16,11.70]]},created_by=admin.id,approved_by=reviewer.id,demo=True);db.add(route);db.flush();routes.append(route)
        for i in range(30):
            v=Vehicle(bus_number=f'{i+1:03}',registration=f'DEMO-TN-30-{i+1:04}',make_model='Synthetic Ashok Leyland / Tata',status='maintenance' if i==28 else 'active',tank_capacity_l=220,safe_fill_l=200,operating_target_l=180,odometer_km=40000+i*1500,depot='Synthetic Salem depot',demo=True);db.add(v);db.flush()
            driver=Driver(employee_id=f'DEMO-D{i+1:03}',name=f'Synthetic Driver {i+1:02}',mobile=None,licence_number='SYNTHETIC-NOT-VALID',licence_expiry=today+timedelta(days=365),demo=True);db.add(driver);db.flush()
            if i==0:users['DRIVER'].driver_id=driver.id
            route=routes[i%len(routes)]
            db.add(Assignment(vehicle_id=v.id,driver_id=driver.id,route_id=route.id,starts_at=day_start(start),ends_at=day_start(start+timedelta(days=30)) if i==0 else None,reason='Synthetic historical assignment',demo=True))
            if i==0:
                sub=Driver(employee_id='DEMO-SUB',name='Synthetic Substitute Driver',demo=True);db.add(sub);db.flush();db.add(Assignment(vehicle_id=v.id,driver_id=sub.id,route_id=route.id,starts_at=day_start(start+timedelta(days=30)),reason='Synthetic substitution preserving history',demo=True))
            db.add(DeviceMapping(vehicle_id=v.id,provider='synthetic_demo',device_id=f'DEMO-{i+1:03}',starts_at=day_start(start),cadence_seconds=300,supports_ignition=True,health='synthetic',demo=True))
            # Private synthetic evidence file, never a real invoice or photograph.
            import hashlib
            from PIL import Image,ImageDraw
            import io
            img=Image.new('RGB',(640,200),'#e4f0eb');ImageDraw.Draw(img).text((20,70),'SYNTHETIC DEMONSTRATION EVIDENCE - NOT A REAL INVOICE',fill='#173b3e');out=io.BytesIO();img.save(out,format='PNG');raw=out.getvalue();key=uid()+'.png';root=Path(settings.PRIVATE_STORAGE_DIR);root.mkdir(parents=True,exist_ok=True);(root/key).write_bytes(raw)
            evidence=Evidence(vehicle_id=v.id,uploaded_by=admin.id,filename='SYNTHETIC-EVIDENCE.png',mime='image/png',size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),storage_key=key,demo=True);db.add(evidence);db.flush()
            mileage=D('3.8')+D(i%5)/10
            db.add(Mileage(vehicle_id=v.id,kmpl=mileage,effective_from=day_start(start),reason='Synthetic demonstration standard',created_by=admin.id,approved_by=reviewer.id,evidence_id=evidence.id,demo=True))
            if i<6:db.add(Survey(route_id=route.id,date=start,b1_km=route.trip_km-1,b2_km=route.trip_km,b3_km=route.trip_km+1,scope=route.scope,created_by=admin.id,approved_by=reviewer.id,evidence_id=evidence.id,demo=True))
            stock=D(120)
            for n in range(61):
                d=start+timedelta(days=n);holiday=d.weekday()==6;outage=i==3 and n%9==0;trip_km=route.trip_km;planned=ZERO if holiday else trip_km*2
                db.add(TankReading(vehicle_id=v.id,occurred_at=day_start(d),litres=q(stock),quality='measured',source='dip',stable=True,uncertainty_l=1,evidence_id=evidence.id,reason='Synthetic verified midnight boundary',created_by=admin.id,verified_by=reviewer.id,demo=True))
                if n==60:break
                windows=[] if holiday else [{'start':(day_start(d)+timedelta(hours=hour)).isoformat(),'end':(day_start(d)+timedelta(hours=hour,seconds=max(2,int(trip_km/2))*240)).isoformat()} for hour in (7,16)]
                db.add(PlannedTrip(vehicle_id=v.id,route_id=route.id,service_date=d,trips=0 if holiday else 2,trip_km=trip_km,scope=route.scope,kind='holiday' if holiday else ('detour' if n==12 else 'service'),reason='Synthetic Sunday holiday' if holiday else ('Synthetic authorised detour' if n==12 else 'Synthetic service schedule'),created_by=admin.id,approved_by=reviewer.id,service_windows=windows,demo=True))
                fuel=ZERO
                if not holiday and stock<100:
                    fuel=D(60) if n%4 else D(40)
                    f=FuelEvent(vehicle_id=v.id,occurred_at=day_start(d)+timedelta(hours=6),litres=fuel,price_per_l=D('94.5'),price_verified=True,supplier='synthetic supplier',invoice=f'DEMO-{i}-{n}',idempotency_key=f'DEMO-REQUEST-{i}-{n}',status='posted',stock_quality='measured',pre_stock_l=stock,post_stock_l=stock+fuel,evidence_id=evidence.id,created_by=users['FUELLER'].id,verified_by=reviewer.id,demo=True);db.add(f)
                # Generate coherent out-and-back geodesic points with <=300s gaps, distance-derived stock.
                km=ZERO
                if not holiday and not outage:
                    for trip_index,hour in enumerate((7,16)):
                        count=max(2,int(trip_km/2));lat0=D('11.65');step=trip_km/D(count)/D('111.19508')
                        previous=None
                        for j in range(count+1):
                            lat=q(lat0+step*min(j,count-j),'0.0000001')
                            if previous is not None:km+=geodesic_km(previous,D('78.16'),lat,D('78.16'))
                            previous=lat
                            db.add(GPSPoint(vehicle_id=v.id,provider='synthetic_demo',device_id=f'DEMO-{i+1:03}',event_id=f'DEMO:{i}:{n}:{trip_index}:{j}',fix_at=day_start(d)+timedelta(hours=hour,seconds=j*240),received_at=day_start(d)+timedelta(hours=hour,seconds=j*240+2),lat=lat,lon=D('78.16'),speed=30,source_unit='kmh',speed_kph=30,ignition=True,accuracy_m=5,raw={'synthetic':True},demo=True))
                # Outages still consume fuel physically; recorded GPS remains missing.
                consumed=(planned if outage else km)/mileage
                stock=q(stock+fuel-consumed)
                if stock<0:raise RuntimeError('Synthetic stock generator underflow.')
            db.flush();rebuild(db,v.id,start,today+timedelta(days=1));db.commit();print(f'Synthetic bus {i+1}/30 generated',flush=True)
        print('Opt-in synthetic demonstration loaded. All fleet records are labelled DEMO. No real people or student data.')

def main():
    parser=argparse.ArgumentParser();parser.add_argument('command',choices=['bootstrap','demo','check-db','rebuild']);parser.add_argument('--synthetic-only',action='store_true');args=parser.parse_args()
    if args.command=='bootstrap':bootstrap()
    elif args.command=='demo':demo(args.synthetic_only)
    elif args.command=='check-db':
        from sqlalchemy import text
        with engine.connect() as c:print({'database_mode':settings.DATABASE_MODE,'connected':c.execute(text('SELECT 1')).scalar()==1})
    else:
        with SessionLocal() as db:
            end=now().astimezone(IST).date()+timedelta(days=1)
            for v in db.query(Vehicle).all():rebuild(db,v.id,end-timedelta(days=60),end)
            db.commit()

if __name__=='__main__':main()
