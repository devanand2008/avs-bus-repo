"""Shortage figures are gated review quantities, never delivery-based accusations."""
import csv
import io
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fleet.calculations import shortage_metrics, D, day_start
from fleet.models import TankReading, DailySnapshot, Mileage, Vehicle
from test_workflows import request, add_fill, decision


@pytest.mark.parametrize('actual,consumed,expected,km,diesel', [
    (720,200,180,80,20), (720,180,180,0,0), (840,200,210,0,0), (0,0,0,0,0),
    (7600,1940,1900,160,40)])
def test_stock_adjusted_shortage_examples(actual,consumed,expected,km,diesel):
    r=shortage_metrics(actual,800,consumed,expected,4,gps_complete=True,plan_complete=True,fuel_eligible=True)
    assert D(r['km_shortage_km'])==km and D(r['diesel_shortage_l'])==diesel
    assert D(r['route_shortage_km'])==max(0,800-actual)


def test_unknown_and_multiple_models_do_not_invent_shortages():
    r=shortage_metrics(720,800,None,180,4,gps_complete=True,plan_complete=True,fuel_eligible=False)
    assert r['km_shortage_km'] is None and r['diesel_shortage_l'] is None and r['route_shortage_km']==80
    r=shortage_metrics(720,800,200,180,None,gps_complete=True,plan_complete=True,fuel_eligible=True)
    assert r['km_shortage_km'] is None and r['diesel_shortage_l']==20
    r=shortage_metrics(720,800,200,180,4,gps_complete=False,plan_complete=True,fuel_eligible=True)
    assert all(r[k] is None for k in ('km_shortage_km','diesel_shortage_l','route_shortage_km'))


def test_measurement_uncertainty_is_not_confirmed_loss():
    r=shortage_metrics(720,800,200,180,4,gps_complete=True,plan_complete=True,fuel_eligible=True,uncertainty=25)
    assert r['diesel_shortage_l']==20 and r['shortage_status']=='within_uncertainty'


def reconciled(e, *, closing=40, coverage='100', flags=None, include_closing=True):
    day=date(2026,9,1)
    obj,_=add_fill(e,litres='200')
    submitted=decision(e,f"/fuel/{obj['id']}/submit",obj,'FUELLER');assert submitted.status_code==200
    posted=decision(e,f"/fuel/{obj['id']}/verify",submitted.json());assert posted.status_code==200
    with e['db']() as db:
        for offset,litres in [(0,40)]+([(1,closing)] if include_closing else []):
            db.add(TankReading(vehicle_id=e['vehicle'],occurred_at=day_start(day+timedelta(days=offset)),litres=litres,quality='measured',source='dip',stable=True,uncertainty_l=1,reason='Synthetic shortage boundary',created_by=e['users']['DATA_ADMIN'],verified_by=e['users']['TRANSPORT_VERIFIER']))
        s=db.query(DailySnapshot).filter_by(vehicle_id=e['vehicle'],service_date=day).one()
        s.data={**s.data,'gps_km':'720.000','planned_km':'800.000','expected_l':'180.000','coverage_pct':coverage,'flags':flags or {},'status':'final'}
        db.commit()
    return posted.json()


def test_dashboard_bus_explain_and_exports_agree(fleet):
    reconciled(fleet)
    query='start=2026-09-01&end=2026-09-02'
    result=request(fleet,'GET','/dashboard?'+query,'CORRESPONDENT');assert result.status_code==200
    data=result.json();b=data['buses'][0]
    assert D(b['km_shortage_km'])==80 and D(b['diesel_shortage_l'])==20 and D(b['route_shortage_km'])==80
    assert D(b['reconciled_range_km'])==800 and b['shortage_status']=='review_required'
    for k in ('km_shortage_km','diesel_shortage_l','route_shortage_km'):
        assert data['metrics'][k]==b[k] and data['contributors'][k]==1
        explanation=request(fleet,'GET',f"/explain/{k}?{query}&vehicle_id={fleet['vehicle']}",'CORRESPONDENT').json()
        assert explanation['value']==b[k] and explanation['sources'][0][k]==b[k]
    detail=request(fleet,'GET',f"/buses/{fleet['vehicle']}/detail?{query}",'CORRESPONDENT').json()
    assert detail['summary']['diesel_shortage_l']==b['diesel_shortage_l']
    frozen=request(fleet,'POST','/reports/freeze?'+query+'&kind=monthly&provisional=true','CORRESPONDENT')
    assert frozen.status_code==201,frozen.text
    rid=frozen.json()['id']
    exported=request(fleet,'GET',f'/reports/{rid}/export?format=csv','CORRESPONDENT');assert exported.status_code==200
    rows=list(csv.reader(io.StringIO(exported.content.decode('utf-8-sig'))))
    header=next(i for i,r in enumerate(rows) if r and r[0]=='Bus number')
    assert D(rows[header+1][rows[header].index('Fuel-based km shortage')])==80
    assert D(rows[header+1][rows[header].index('Diesel shortage L (review)')])==20
    pdf=request(fleet,'GET',f'/reports/{rid}/export?format=pdf','CORRESPONDENT');assert pdf.status_code==200
    from pypdf import PdfReader
    text=' '.join(p.extract_text() for p in PdfReader(io.BytesIO(pdf.content)).pages)
    assert 'Fuel-based km shortage' in text and 'Diesel shortage / review variance' in text
    assert request(fleet,'GET',f'/reports/{rid}/export?format=csv','DRIVER').status_code==403


@pytest.mark.parametrize('coverage,flags,include_closing', [('80',{},True),('100',{'gaps':1},True),('100',{},False)])
def test_incomplete_inputs_never_show_a_zero_fuel_shortage(fleet,coverage,flags,include_closing):
    reconciled(fleet,coverage=coverage,flags=flags,include_closing=include_closing)
    b=request(fleet,'GET','/dashboard?start=2026-09-01&end=2026-09-02','CORRESPONDENT').json()['buses'][0]
    assert b['km_shortage_km'] is None and b['diesel_shortage_l'] is None


def test_multiple_mileage_versions_keep_litres_but_no_single_range(fleet):
    reconciled(fleet)
    with fleet['db']() as db:
        original=db.get(Mileage,fleet['mileage']);original.effective_to=day_start(date(2026,9,1))+timedelta(hours=12)
        db.add(Mileage(vehicle_id=fleet['vehicle'],kmpl=5,effective_from=original.effective_to,reason='Synthetic interval model',created_by=fleet['users']['DATA_ADMIN'],approved_by=fleet['users']['TRANSPORT_VERIFIER']))
        db.commit()
    b=request(fleet,'GET','/dashboard?start=2026-09-01&end=2026-09-02','CORRESPONDENT').json()['buses'][0]
    assert b['km_shortage_km'] is None and D(b['diesel_shortage_l'])==20


def test_fleet_never_offsets_one_bus_shortage_with_another_surplus(fleet):
    reconciled(fleet)
    with fleet['db']() as db:
        other=Vehicle(bus_number='008',registration='SYNTHETIC-SURPLUS',tank_capacity_l=220,safe_fill_l=200,operating_target_l=100,demo=True);db.add(other);db.flush()
        for offset,litres in [(0,220),(1,20)]:
            db.add(TankReading(vehicle_id=other.id,occurred_at=day_start(date(2026,9,1)+timedelta(days=offset)),litres=litres,quality='measured',source='dip',stable=True,reason='Synthetic surplus boundary',created_by=fleet['users']['DATA_ADMIN'],verified_by=fleet['users']['TRANSPORT_VERIFIER']))
        db.add(Mileage(vehicle_id=other.id,kmpl=4,effective_from=day_start(date(2026,9,1)),reason='Synthetic standard',created_by=fleet['users']['DATA_ADMIN'],approved_by=fleet['users']['TRANSPORT_VERIFIER']))
        db.add(DailySnapshot(vehicle_id=other.id,service_date=date(2026,9,1),calculation_version='test',input_hash='surplus',data={'gps_km':'840','planned_km':'800','expected_l':'210','coverage_pct':'100','status':'final'}));db.commit()
    data=request(fleet,'GET','/dashboard?start=2026-09-01&end=2026-09-02','CORRESPONDENT').json()
    assert D(data['metrics']['km_shortage_km'])==80 and D(data['metrics']['diesel_shortage_l'])==20
    assert data['contributors']['diesel_shortage_l']==2
