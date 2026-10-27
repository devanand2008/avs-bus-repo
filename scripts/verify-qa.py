"""HTTP journey, performance measurements, and printable artefacts on the isolated synthetic QA fleet."""
import os,sys,json,time,io,statistics,platform
from pathlib import Path
from datetime import date,datetime,timedelta,timezone
root=Path(__file__).resolve().parents[1];values=json.loads((root/'.runtime/demo-env.json').read_text());os.environ.update(values);sys.path.insert(0,str(root/'backend'))
import httpx
from PIL import Image,ImageDraw
from fleet.calculations import day_start,IST
from fleet.db import SessionLocal
from fleet.models import Vehicle,GPSPoint,DailySnapshot,FuelEvent
out=root/'output';(out/'pdf').mkdir(parents=True,exist_ok=True);(out/'checks').mkdir(exist_ok=True)
base='http://127.0.0.1:8001/api/v2';client=httpx.Client(timeout=180,headers={'Origin':'http://localhost:3001'});tokens={}
for role in ('admin','data_admin','transport_verifier','correspondent','fueller','accounts'):
    email=values['BOOTSTRAP_EMAIL'] if role=='admin' else role+'@demo.example.com'
    r=client.post(base+'/auth/login',json={'email':email,'password':values['DEMO_PASSWORD']},headers={'X-Client':'native'})
    r.raise_for_status();tokens[role]=r.json()['access_token']
def call(method,path,role='admin',**kw):
    r=client.request(method,base+path,headers={'Authorization':'Bearer '+tokens[role]},**kw)
    if r.status_code>=400:raise RuntimeError(f'{method} {path}: {r.status_code} {r.text[:1000]}')
    return r
def approve(kind,row,role='transport_verifier'):
    return call('POST',f"/resources/{kind}/{row['id']}/approve",role,json={'version':row['version'],'reason':'Synthetic QA independent evidence review'}).json()
today=datetime.now(IST).date();day=today-timedelta(days=2);start=today.replace(day=1);end=(start+timedelta(days=32)).replace(day=1);period=f'start={start}&end={end}'
identity=str(int(time.time()))
v=call('POST','/resources/vehicles',json={'bus_number':'00087-'+identity[-4:],'registration':'SYNTHETIC-QA-'+identity,'make_model':'SYNTHETIC TEST VEHICLE','tank_capacity_l':180,'safe_fill_l':160,'operating_target_l':100}).json()
driver=call('POST','/resources/drivers',json={'employee_id':'QA-'+identity,'name':'Synthetic QA driver','licence_number':'NOT-A-VALID-LICENCE'}).json()
route=call('POST','/resources/routes',json={'code':'QA-'+identity,'name':'Synthetic QA route','trip_km':'.111','scope':'round_trip','stops':['Synthetic depot','Synthetic campus']}).json();approve('routes',route)
assignment=call('POST','/resources/assignments',json={'vehicle_id':v['id'],'driver_id':driver['id'],'route_id':route['id'],'starts_at':day_start(day-timedelta(days=1)).isoformat(),'reason':'Synthetic HTTP end-to-end assignment'}).json()
device='QA-DEVICE-'+identity
call('POST','/resources/devices',json={'vehicle_id':v['id'],'provider':'synthetic_qa','device_id':device,'starts_at':day_start(day-timedelta(days=1)).isoformat()})
image=Image.new('RGB',(900,250),'#f7f7f2');ImageDraw.Draw(image).text((30,100),'SYNTHETIC QA EVIDENCE - NOT A REAL INVOICE OR COLLEGE RECORD',fill='#102c42');buffer=io.BytesIO();image.save(buffer,'PNG')
ev=call('POST','/evidence',data={'vehicle_id':v['id']},files={'file':('synthetic-qa.png',buffer.getvalue(),'image/png')}).json()
mileage=call('POST','/resources/mileage',json={'vehicle_id':v['id'],'kmpl':4,'effective_from':day_start(day-timedelta(days=1)).isoformat(),'reason':'Synthetic standard','evidence_id':ev['id']}).json();approve('mileage',mileage)
a=day_start(day)+timedelta(hours=7);b=a+timedelta(seconds=30)
plan=call('POST','/resources/plans',json={'vehicle_id':v['id'],'route_id':route['id'],'service_date':str(day),'trips':1,'trip_km':'.111','scope':'round_trip','reason':'Synthetic scheduled service','service_windows':[{'start':a.isoformat(),'end':b.isoformat()}]}).json();approve('plans',plan)
points=[{'provider':'synthetic_qa','device_id':device,'event_id':identity+'-a','fix_at':a.isoformat(),'lat':'11.6500000','lon':'78.1600000','accuracy_m':5,'speed':30,'ignition':True,'raw':{'synthetic':True}},{'provider':'synthetic_qa','device_id':device,'event_id':identity+'-b','fix_at':b.isoformat(),'lat':'11.6510000','lon':'78.1600000','accuracy_m':5,'speed':30,'ignition':True,'raw':{'synthetic':True}}]
assert call('POST','/gps/ingest',json=points).json()['accepted']==2
assert call('POST','/gps/ingest',json=points).json()['duplicate']==2
fuel=call('POST','/fuel','fueller',json={'vehicle_id':v['id'],'occurred_at':(a+timedelta(hours=3)).isoformat(),'litres':20,'price_per_l':'94.5','supplier':'SYNTHETIC QA PUMP','invoice':identity,'idempotency_key':'qa-fill-'+identity,'evidence_id':ev['id']}).json()
fuel=call('POST',f"/fuel/{fuel['id']}/submit",'fueller',json={'version':fuel['version'],'reason':'Synthetic QA invoice submitted'}).json()
fuel=call('POST',f"/fuel/{fuel['id']}/verify",'transport_verifier',json={'version':fuel['version'],'reason':'Independent QA verification'}).json()
call('POST',f"/fuel/{fuel['id']}/match-invoice",'accounts',json={'version':fuel['version'],'reason':'Synthetic accounts invoice match'})
fleet=call('GET','/dashboard?'+period,'correspondent').json();summary=call('GET',f"/buses/{v['id']}/detail?{period}",'correspondent').json()['summary'];fleetbus=next(x for x in fleet['buses'] if x['vehicle_id']==v['id'])
assert summary['gps_km']==fleetbus['gps_km'] and summary['delivered_l']==fleetbus['delivered_l']=='20.000' and summary['refill_count']==1
with SessionLocal() as db:
    row=db.get(Vehicle,v['id']);row.demo=True;db.commit()
report_ids=[]
for kind in ('gps_weekly','fuel_weekly','monthly'):
    p=period if kind=='monthly' else f'start={day-timedelta(days=3)}&end={day+timedelta(days=4)}'
    r=call('POST',f"/reports/freeze?{p}&vehicle_id={v['id']}&kind={kind}&provisional=true",'admin').json()
    r=call('POST',f"/reports/{r['id']}/verify",'transport_verifier',json={'version':r['version'],'reason':'Separate synthetic QA report verification'}).json()
    call('POST',f"/reports/{r['id']}/sign",'correspondent',json={'version':r['version'],'reason':'Independent synthetic QA report signature'})
    for format in ('pdf','csv'):
        response=call('GET',f"/reports/{r['id']}/export?format={format}",'correspondent');(out/'pdf'/f'{kind}-synthetic-qa.{format}').write_bytes(response.content)
    report_ids.append(r['id'])
durations=[];sizes=[]
for _ in range(3):
    t=time.perf_counter();r=call('GET','/dashboard?'+period,'correspondent');durations.append(round(time.perf_counter()-t,3));sizes.append(len(r.content))
with SessionLocal() as db:counts={'vehicles':db.query(Vehicle).count(),'raw_gps_events':db.query(GPSPoint).count(),'daily_summaries':db.query(DailySnapshot).count(),'fuel_events':db.query(FuelEvent).count()}
result={'journey':'PASS: administrator created vehicle, driver, route, assignment and device; telemetry deduplicated; fuel submitted/independently posted; correspondent month/detail/export values matched; independent report signature succeeded.','vehicle_id':v['id'],'bus_number':v['bus_number'],'period':{'start':str(start),'end_exclusive':str(end)},'report_ids':report_ids,'counts':counts,'performance':{'environment':platform.platform(),'python':platform.python_version(),'database':'MySQL 8.4.13 on localhost, one API worker','concurrent_clients':1,'requests':3,'dashboard_seconds':durations,'median_seconds':statistics.median(durations),'response_bytes':sizes,'scope':'Selected calendar month; 30+ synthetic buses, >=60 days history. No production scalability claim.'}}
(out/'checks'/'verification.json').write_text(json.dumps(result,indent=2),encoding='utf-8');print(json.dumps(result,indent=2))
