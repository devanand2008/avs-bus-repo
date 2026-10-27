from datetime import date,timedelta,datetime,timezone
from fleet.calculations import *
from fleet.models import *
from fleet.services import summarise_bus,rebuild
from test_workflows import request,decision,add_fill,PERIOD

def test_examples_are_server_calculated_and_nonpersistent(env):
    e=env;r=e['client'].get('/api/v2/public/calculation-examples');assert r.status_code==200
    d=r.json();assert d['persisted'] is False and d['weekly']['residual_l']=='0' and d['monthly']['residual_l']=='40'
    assert request(e,'GET','/resources/vehicles').json()['total']==0

def test_unknown_preview_and_exact_topup(env):
    assert request(env,'GET','/tools/refill-preview?target=100&stock=18&quality=measured').json()['top_up_l']=='82'
    assert request(env,'GET','/tools/refill-preview?target=100&stock=18&quality=unknown').json()['top_up_l'] is None

def test_late_evidence_does_not_change_signed_payload(fleet):
    e=fleet;report=request(e,'POST','/reports/freeze?'+PERIOD+'&provisional=true','DATA_ADMIN').json()
    assert decision(e,f"/reports/{report['id']}/sign",report,'CORRESPONDENT').status_code==422
    report=decision(e,f"/reports/{report['id']}/verify",report,'TRANSPORT_VERIFIER').json()
    signed=decision(e,f"/reports/{report['id']}/sign",report,'CORRESPONDENT');assert signed.status_code==200
    assert decision(e,f"/reports/{report['id']}/sign",signed.json(),'CORRESPONDENT').status_code==409
    assert request(e,'GET',f"/reports/{report['id']}/export?format=csv",'AUDITOR').status_code==200
    assert request(e,'GET',f"/reports/{report['id']}/export?format=csv",'DRIVER').status_code==403

def test_assignment_window_scope(fleet):
    e=fleet
    with e['db']() as db:a=db.query(Assignment).filter_by(vehicle_id=e['vehicle']).first();a.ends_at=day_start(date(2026,9,2));db.commit()
    assert request(e,'GET',f"/buses/{e['vehicle']}/detail?{PERIOD}",'DRIVER').status_code==403
    assert request(e,'GET','/dashboard?'+PERIOD,'DRIVER').json()['metrics']['total_buses']==0

def test_mileage_self_approval_and_immutable_approved(fleet):
    e=fleet;m=request(e,'POST','/resources/mileage','DATA_ADMIN',json={'vehicle_id':e['vehicle'],'kmpl':5,'effective_from':'2026-10-01T00:00:00+05:30','reason':'Test change','evidence_id':e['evidence']}).json()
    assert decision(e,f"/resources/mileage/{m['id']}/approve",m,'DATA_ADMIN').status_code==403
    assert decision(e,f"/resources/mileage/{m['id']}/approve",m,'TRANSPORT_VERIFIER').status_code==409
    assert request(e,'PUT',f"/resources/mileage/{e['mileage']}?version=1&reason=Test%20edit",'DATA_ADMIN',json={'vehicle_id':e['vehicle'],'kmpl':5,'effective_from':'2026-09-01T00:00:00+05:30','reason':'test'}).status_code==409

def test_gps_coverage_requires_approved_time_windows(fleet):
    e=fleet
    with e['db']() as db:
        day=date(2026,9,1);a=day_start(day)+timedelta(hours=7)
        for i in range(3):db.add(GPSPoint(vehicle_id=e['vehicle'],provider='test_provider',device_id='DEVICE-007',event_id=f'coverage-{i}',fix_at=a+timedelta(seconds=30*i),lat=D('11.65')+D(i)/1000,lon=D('78.16'),speed_kph=30))
        plan=PlannedTrip(vehicle_id=e['vehicle'],route_id=e['route'],service_date=day,trips=1,trip_km=1,scope='round_trip',reason='approved fixture',created_by=e['users']['DATA_ADMIN'],approved_by=e['users']['TRANSPORT_VERIFIER']);db.add(plan);db.flush();rebuild(db,e['vehicle'],day,day+timedelta(days=1));db.commit()
        row=db.query(DailySnapshot).filter_by(vehicle_id=e['vehicle'],service_date=day).first();assert row.data['coverage_pct'] is None
        plan.service_windows=[{'start':a.isoformat(),'end':(a+timedelta(seconds=60)).isoformat()}];db.flush();rebuild(db,e['vehicle'],day,day+timedelta(days=1));db.commit();assert D(row.data['coverage_pct'])==100

def test_calendar_period_additivity(fleet):
    e=fleet;obj,_=add_fill(e);submitted=decision(e,f"/fuel/{obj['id']}/submit",obj,'FUELLER').json();decision(e,f"/fuel/{obj['id']}/verify",submitted)
    with e['db']() as db:
        v=db.get(Vehicle,e['vehicle']);a=summarise_bus(db,v,date(2026,9,1),date(2026,9,2));b=summarise_bus(db,v,date(2026,9,2),date(2026,9,3));full=summarise_bus(db,v,date(2026,9,1),date(2026,9,3))
        assert D(a['delivered_l'])+D(b['delivered_l'])==D(full['delivered_l']) and a['refill_count']+b['refill_count']==full['refill_count']

def test_sensor_calibration_and_stability_gates(fleet):
    e=fleet;p={'vehicle_id':e['vehicle'],'occurred_at':'2026-09-01T00:00:00+05:30','litres':20,'quality':'measured','source':'sensor','stable':True,'reason':'Sensor fixture'}
    assert request(e,'POST','/resources/tank-readings','DATA_ADMIN',json=p).status_code==422
    assert request(e,'POST','/resources/tank-readings','DATA_ADMIN',json={**p,'source':'manual_estimate'}).status_code==422

def test_evidence_object_scope(fleet):
    e=fleet
    assert request(e,'GET','/evidence/'+e['evidence']+'/download','DRIVER').status_code==403
    assert request(e,'GET','/resources/audit','DRIVER').status_code==403

def test_server_role_does_not_follow_client_claim(fleet):
    e=fleet
    assert request(e,'POST','/auth/login','DRIVER',json={'email':'driver@example.com','password':'test-password-123','role':'SYSTEM_ADMIN'}).status_code==422

def test_fuel_period_filter(fleet):
    e=fleet;add_fill(e)
    assert request(e,'GET','/resources/fuel?start=2026-10-01&end=2026-11-01','CORRESPONDENT').json()['total']==0
    assert request(e,'GET','/resources/fuel?'+PERIOD,'CORRESPONDENT').json()['total']==1

def test_privileged_mfa_enforcement_and_enrolment(env,monkeypatch):
    from fleet.config import settings
    import pyotp
    monkeypatch.setattr(settings,'MFA_REQUIRED',True)
    assert request(env,'GET','/dashboard?'+PERIOD).status_code==403
    setup=request(env,'POST','/auth/mfa/enrol');assert setup.status_code==200
    token=pyotp.TOTP(setup.json()['secret']).now()
    result=request(env,'POST','/auth/mfa/confirm',data={'otp':token});assert result.status_code==200
    assert request(env,'GET','/dashboard?'+PERIOD).status_code==200

def test_case_decisions_need_independent_financial_approval(fleet):
    e=fleet
    with e['db']() as db:
        c=Case(vehicle_id=e['vehicle'],rule='test_review',explanation='Synthetic test discrepancy',inputs={'source':'test'});db.add(c);db.commit();id=c.id
    p={'version':1,'reason':'Independent investigation started','state':'Investigating'}
    r=request(e,'POST',f'/cases/{id}/decision','TRANSPORT_VERIFIER',json=p);assert r.status_code==200
    p.update(version=r.json()['version'],state='Confirmed discrepancy',approved_amount=100)
    assert request(e,'POST',f'/cases/{id}/decision','TRANSPORT_VERIFIER',json=p).status_code==403
    r=request(e,'POST',f'/cases/{id}/decision','CORRESPONDENT',json=p);assert r.status_code==200
    result=decision(e,f'/cases/{id}/match-accounts',r.json(),'ACCOUNTS');assert result.status_code==200
