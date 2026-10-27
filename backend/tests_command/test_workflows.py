import io
from datetime import date,datetime,timedelta,timezone
from decimal import Decimal
from concurrent.futures import ThreadPoolExecutor
import pytest
from fleet.models import *
from fleet.calculations import *
from fleet.services import rebuild,summarise_bus,assignment_at,dashboard
from fleet.db import engine

PERIOD='start=2026-09-01&end=2026-09-03'
def request(e,method,path,role='SYSTEM_ADMIN',**kw):return e['client'].request(method,'/api/v2'+path,headers=e['headers'][role],**kw)
def add_fill(e,**extra):
    data={'vehicle_id':e['vehicle'],'occurred_at':'2026-09-01T07:00:00+05:30','litres':'50','supplier':'Test Pump','invoice':'TEST-1','idempotency_key':'TEST-REQUEST-001','evidence_id':e['evidence']};data.update(extra)
    r=request(e,'POST','/fuel','FUELLER',json=data);assert r.status_code==201,r.text;return r.json(),data
def decision(e,path,obj,role='TRANSPORT_VERIFIER',reason='Verified supporting evidence'):
    return request(e,'POST',path,role,json={'version':obj['version'],'reason':reason})

def test_empty_start_and_real_auth(env):
    e=env;r=request(e,'GET','/dashboard?'+PERIOD,'CORRESPONDENT');assert r.status_code==200;assert r.json()['metrics']['total_buses']==0
    assert e['client'].get('/api/v2/resources/vehicles').status_code==401
    r=e['client'].post('/api/v2/auth/login',json={'email':'data_admin@example.com','password':'test-password-123'});assert r.status_code==200
    assert 'HttpOnly' in r.headers['set-cookie'] and 'access_token' not in r.json()
    assert e['client'].post('/api/v2/auth/login',headers={'Origin':'http://localhost:3000'},json={'email':'data_admin@example.com','password':'wrong'}).status_code==401

def test_admin_only_bus_entry_leading_zeros_and_archive(env):
    e=env;p={'bus_number':'0009','registration':'TEST-009','tank_capacity_l':180,'safe_fill_l':160,'operating_target_l':100}
    for role in ('CORRESPONDENT','FUELLER','DRIVER','AUDITOR','ACCOUNTS','TRANSPORT_VERIFIER'):
        assert request(e,'POST','/resources/vehicles',role,json=p).status_code==403
    r=request(e,'POST','/resources/vehicles','DATA_ADMIN',json=p);assert r.status_code==201
    v=r.json();assert v['bus_number']=='0009' and len(v['id'])==36
    assert decision(e,f"/resources/vehicles/{v['id']}/archive",v,'DATA_ADMIN').status_code==200
    assert request(e,'GET',f"/buses/{v['id']}/detail?{PERIOD}",'CORRESPONDENT').status_code==200

def test_capacity_validation(env):
    p={'bus_number':'01','registration':'TEST-01','tank_capacity_l':100,'safe_fill_l':120,'operating_target_l':90}
    assert request(env,'POST','/resources/vehicles','DATA_ADMIN',json=p).status_code==422

def test_refill_idempotency_duplicate_invoice_and_posting(fleet):
    e=fleet;obj,p=add_fill(e)
    assert request(e,'POST','/fuel','FUELLER',json=p).json()['id']==obj['id']
    assert request(e,'POST','/fuel','FUELLER',json={**p,'litres':60}).status_code==409
    assert request(e,'POST','/fuel','FUELLER',json={**p,'idempotency_key':'TEST-REQUEST-002'}).status_code==409
    before=request(e,'GET','/dashboard?'+PERIOD,'CORRESPONDENT').json();assert D(before['metrics']['delivered_l'])==0
    submit=decision(e,f"/fuel/{obj['id']}/submit",obj,'FUELLER');assert submit.status_code==200
    posted=decision(e,f"/fuel/{obj['id']}/verify",submit.json());assert posted.status_code==200
    after=request(e,'GET','/dashboard?'+PERIOD,'CORRESPONDENT').json();assert D(after['metrics']['delivered_l'])==50 and D(after['metrics']['refill_count'])==1
    assert decision(e,f"/fuel/{obj['id']}/verify",submit.json()).status_code==409

def test_self_approval_is_forbidden(fleet):
    e=fleet
    with e['db']() as db:
        user=db.get(User,e['users']['TRANSPORT_VERIFIER']);obj=FuelEvent(vehicle_id=e['vehicle'],occurred_at=day_start(date(2026,9,1)),litres=20,supplier='self',invoice='SELF',idempotency_key='SELF-APPROVAL',created_by=user.id,status='submitted',evidence_id=e['evidence']);db.add(obj);db.commit();id=obj.id
    r=decision(e,f'/fuel/{id}/verify',{'version':1});assert r.status_code==403

def test_driver_object_access_and_pii(fleet):
    e=fleet
    add_fill(e)
    r=request(e,'GET','/resources/drivers','DRIVER');assert r.status_code==200 and 'mobile' not in r.json()['items'][0]
    with e['db']() as db:
        other=Vehicle(bus_number='008',registration='TEST-008',tank_capacity_l=100,safe_fill_l=90,operating_target_l=80);db.add(other);db.commit();id=other.id
    assert request(e,'GET',f'/buses/{id}/detail?{PERIOD}','DRIVER').status_code==404
    assert request(e,'GET','/evidence/'+e['evidence']+'/download','DRIVER').status_code==200
    assert request(e,'GET','/resources/vehicles/export','DRIVER').status_code==403

def test_private_upload_and_integrity(fleet):
    e=fleet;r=request(e,'POST','/evidence','DATA_ADMIN',data={'vehicle_id':e['vehicle']},files={'file':('proof.png',e['image'],'image/png')});assert r.status_code==201,r.text
    evidence=r.json();assert 'storage_key' not in evidence
    assert e['client'].get('/api/v2/evidence/'+evidence['id']+'/download').status_code==401
    assert request(e,'POST','/evidence','DATA_ADMIN',data={'vehicle_id':e['vehicle']},files={'file':('evil.png',b'<script>bad</script>','image/png')}).status_code==422

def test_stock_carry_forward_missing_not_zero(fleet):
    e=fleet
    with e['db']() as db:
        for d,litres in [(1,40),(2,60),(3,0)]:db.add(TankReading(vehicle_id=e['vehicle'],occurred_at=day_start(date(2026,9,d)),litres=litres,quality='measured',source='dip',stable=True,reason='Test boundary',evidence_id=e['evidence'],created_by=e['users']['DATA_ADMIN'],verified_by=e['users']['TRANSPORT_VERIFIER']))
        db.commit();v=db.get(Vehicle,e['vehicle']);a=summarise_bus(db,v,date(2026,9,1),date(2026,9,2));b=summarise_bus(db,v,date(2026,9,2),date(2026,9,3));missing=summarise_bus(db,v,date(2026,9,3),date(2026,9,4))
        assert a['closing_l']==b['opening_l']=='60.000';assert b['closing_l']=='0.000';assert missing['closing_l'] is None and missing['disappearance_l'] is None

def gps(e,event,t,lat):return {'provider':'test_provider','device_id':'DEVICE-007','event_id':event,'fix_at':t,'lat':lat,'lon':'78.1600000','speed':30,'source_unit':'kmh','accuracy_m':5,'ignition':True}

def test_gps_dedup_gaps_late_revisions_and_matching_reports(fleet):
    e=fleet;points=[gps(e,'a','2026-09-01T07:00:00+05:30','11.6500000'),gps(e,'b','2026-09-01T07:00:30+05:30','11.6510000')]
    r=request(e,'POST','/gps/ingest',json=points);assert r.status_code==200,r.text;assert r.json()['accepted']==2
    assert request(e,'POST','/gps/ingest',json=points).json()['duplicate']==2
    data=request(e,'GET','/dashboard?'+PERIOD,'CORRESPONDENT').json();bus=request(e,'GET',f"/buses/{e['vehicle']}/detail?{PERIOD}",'CORRESPONDENT').json()['summary'];assert data['metrics']['gps_km']==bus['gps_km']
    report=request(e,'POST','/reports/freeze?'+PERIOD+'&kind=monthly&provisional=true','TRANSPORT_VERIFIER');assert report.status_code==201,report.text
    r=report.json();csv=request(e,'GET',f"/reports/{r['id']}/export?format=csv",'CORRESPONDENT');assert csv.status_code==200 and b'007' in csv.content
    pdf=request(e,'GET',f"/reports/{r['id']}/export?format=pdf",'CORRESPONDENT');assert pdf.status_code==200 and pdf.content.startswith(b'%PDF')
    import pypdf
    reader=pypdf.PdfReader(io.BytesIO(pdf.content));assert len(reader.pages)>=3
    late=gps(e,'c','2026-09-01T07:01:00+05:30','11.6520000');assert request(e,'POST','/gps/ingest',json=[late]).status_code==200
    with e['db']() as db:frozen=db.get(Report,r['id']);assert frozen.needs_revision;assert frozen.payload==r['payload']
    assert decision(e,f"/reports/{r['id']}/sign",r,'CORRESPONDENT').status_code==409

def test_midnight_and_effective_mileage_versions(fleet):
    e=fleet
    with e['db']() as db:
        old=db.get(Mileage,e['mileage']);old.effective_to=day_start(date(2026,9,2));db.add(Mileage(vehicle_id=e['vehicle'],kmpl=5,effective_from=day_start(date(2026,9,2)),reason='New standard',created_by=e['users']['DATA_ADMIN'],approved_by=e['users']['TRANSPORT_VERIFIER'],evidence_id=e['evidence']));db.commit()
    points=[gps(e,'mid-a','2026-09-01T23:59:00+05:30','11.6500000'),gps(e,'mid-b','2026-09-02T00:01:00+05:30','11.6600000')]
    assert request(e,'POST','/gps/ingest',json=points).status_code==200
    with e['db']() as db:
        rows=db.query(DailySnapshot).filter(DailySnapshot.vehicle_id==e['vehicle'],DailySnapshot.service_date.in_([date(2026,9,1),date(2026,9,2)])).order_by(DailySnapshot.service_date).all();assert len(rows)==2
        assert abs(D(rows[0].data['gps_km'])-D(rows[1].data['gps_km']))<D('.002')
        assert abs(D(rows[0].data['expected_l'])*4-D(rows[1].data['expected_l'])*5)<D('.01')

def test_historical_driver_assignment(fleet):
    e=fleet
    with e['db']() as db:
        a=db.query(Assignment).filter_by(vehicle_id=e['vehicle']).first();boundary=day_start(date(2026,9,15));a.ends_at=boundary
        second=Driver(employee_id='D2',name='Synthetic substitute');db.add(second);db.flush();db.add(Assignment(vehicle_id=e['vehicle'],driver_id=second.id,route_id=e['route'],starts_at=boundary,reason='Substitution'));db.commit()
        assert assignment_at(db,e['vehicle'],boundary-timedelta(seconds=1)).driver_id==e['driver']
        assert assignment_at(db,e['vehicle'],boundary).driver_id==second.id

def test_reversals_corrections_and_optimistic_approval(fleet):
    e=fleet;obj,p=add_fill(e);submitted=decision(e,f"/fuel/{obj['id']}/submit",obj,'FUELLER').json();posted=decision(e,f"/fuel/{obj['id']}/verify",submitted).json()
    assert request(e,'PUT',f"/fuel/{obj['id']}?version={posted['version']}",'FUELLER',json=p).status_code==409
    reversed=decision(e,f"/fuel/{obj['id']}/reverse",posted,'CORRESPONDENT');assert reversed.status_code==200
    assert D(request(e,'GET','/dashboard?'+PERIOD,'CORRESPONDENT').json()['metrics']['refill_count'])==0
    p.update(invoice='TEST-CORRECTION',idempotency_key='TEST-CORRECTION-001',correction_of=obj['id']);assert request(e,'POST','/fuel','FUELLER',json=p).status_code==201
    assert decision(e,f"/fuel/{obj['id']}/reverse",posted,'CORRESPONDENT').status_code==409

def test_import_transaction_and_csv_formula_safety(env):
    e=env;content='bus_number,registration,tank_capacity_l,safe_fill_l,operating_target_l\n=BAD,TEST-A,100,90,80\n002,TEST-B,100,110,80\n'
    assert request(e,'POST','/resources/vehicles/import','DATA_ADMIN',files={'file':('buses.csv',content,'text/csv')}).status_code==422
    assert request(e,'GET','/resources/vehicles').json()['total']==0
    from fleet.reports import safe_cell
    assert safe_cell('=SUM(A1)')=="'=SUM(A1)"

@pytest.mark.skipif(engine.dialect.name!='mysql',reason='Requires independent MySQL connections; run TEST_DATABASE_URL suite.')
def test_actual_concurrent_verification_has_one_winner(fleet):
    e=fleet;obj,_=add_fill(e);submitted=decision(e,f"/fuel/{obj['id']}/submit",obj,'FUELLER').json()
    def approve(role):return decision(e,f"/fuel/{obj['id']}/verify",submitted,role).status_code
    with ThreadPoolExecutor(max_workers=2) as pool:results=list(pool.map(approve,['CORRESPONDENT','TRANSPORT_VERIFIER']))
    assert sorted(results)==[200,409]
