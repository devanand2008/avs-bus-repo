"""Synthetic end-to-end tank/GPS regressions; no production data or vendor calls."""
from datetime import date, timedelta
from decimal import Decimal
import pytest
from fleet.models import TankReading, Vehicle, Mileage, GPSPoint, DailySnapshot
from fleet.calculations import day_start, geodesic_km, D
from fleet.services import summarise_bus, rebuild
from test_workflows import request, add_fill, decision

DAY = date(2026, 9, 1)
START = day_start(DAY) + timedelta(hours=9)


def reading(e, litres=38, at=START, stable=True, verified=True):
    with e['db']() as db:
        r = TankReading(vehicle_id=e['vehicle'], occurred_at=at, litres=litres,
            quality='measured', source='dip', stable=stable, reason='Synthetic supervised dip reading',
            created_by=e['users']['DATA_ADMIN'], verified_by=e['users']['TRANSPORT_VERIFIER'] if verified else None)
        db.add(r); db.commit(); return r.id


def telemetry(e, gap=False):
    # 80 km over 80 minutes, supplied out of order to exercise sorting.
    degree_km = geodesic_km(0, 78, 0, 79)
    points = [{'provider':'test_provider', 'device_id':'DEVICE-007', 'event_id':f'TANK-{i}',
        'fix_at':(START+timedelta(minutes=i)).isoformat(), 'lat':'0',
        'lon':str((D(78)+D(i)/degree_km).quantize(D('.0000001'))),
        'speed':60, 'source_unit':'kmh', 'ignition':True} for i in range(81) if not gap or i not in range(20, 31)]
    result = request(e, 'POST', '/gps/ingest', json=points[::-1])
    assert result.status_code == 200, result.text
    return points


def summary(e, monkeypatch, at):
    monkeypatch.setattr('fleet.services.now', lambda: at)
    r = request(e, 'GET', '/dashboard?start=2026-09-01&end=2026-09-02', 'CORRESPONDENT')
    assert r.status_code == 200, r.text
    return r.json(), r.json()['buses'][0]


def post(e, obj):
    r = decision(e, f"/fuel/{obj['id']}/submit", obj, 'FUELLER'); assert r.status_code == 200, r.text
    r = decision(e, f"/fuel/{obj['id']}/verify", r.json()); assert r.status_code == 200, r.text
    return r.json()


def test_daily_gps_tank_estimate_refill_dashboard_and_bus_agree(fleet, monkeypatch):
    anchor = reading(fleet); points = telemetry(fleet)
    at = START+timedelta(minutes=80, seconds=1)
    data, bus = summary(fleet, monkeypatch, at)
    assert abs(D(bus['gps_km'])-80) < D('.001')
    assert abs(D(bus['expected_l'])-20) < D('.001')
    assert abs(D(bus['stock_l'])-18) < D('.001')
    assert abs(D(bus['top_up_l'])-82) < D('.001')
    assert bus['stock_quality'] == 'estimated'
    assert bus['stock_anchor']['id'] == anchor
    assert len(bus['stock_source_ids']['gps']) == 81
    assert data['contributors']['stock_l'] == 1
    detail = request(fleet, 'GET', f"/buses/{fleet['vehicle']}/detail?start=2026-09-01&end=2026-09-02", 'CORRESPONDENT').json()['summary']
    assert detail['stock_l'] == bus['stock_l'] and detail['gps_km'] == bus['gps_km']
    # Replay cannot increase daily km or tank consumption.
    r = request(fleet, 'POST', '/gps/ingest', json=points)
    assert r.json()['duplicate'] == 81
    assert summary(fleet, monkeypatch, at)[1]['stock_l'] == bus['stock_l']
    fill_at = START+timedelta(minutes=85)
    obj, _ = add_fill(fleet, occurred_at=fill_at.isoformat(), litres='82', pre_stock_l='18', post_stock_l='100', stock_quality='measured')
    assert summary(fleet, monkeypatch, fill_at+timedelta(seconds=1))[1]['latest_refill'] is None
    posted = post(fleet, obj)
    _, bus = summary(fleet, monkeypatch, fill_at+timedelta(seconds=1))
    assert bus['delivered_l'] == '82.000' and bus['refill_count'] == 1
    assert bus['stock_l'] == '100.000' and bus['top_up_l'] == '0.000'
    assert bus['stock_quality'] == 'measured'
    assert D(bus['latest_refill']['pre_stock_l']) == 18
    assert D(bus['latest_refill']['post_stock_l']) == 100
    assert bus['latest_refill']['id'] == posted['id']
    # Reversal removes the snapshot as well as the delivered quantity.
    r = decision(fleet, f"/fuel/{obj['id']}/reverse", posted, 'CORRESPONDENT')
    assert r.status_code == 200, r.text
    _, bus = summary(fleet, monkeypatch, fill_at+timedelta(seconds=1))
    assert bus['latest_refill'] is None and bus['refill_count'] == 0


@pytest.mark.parametrize('stable,verified', [(False, True), (True, False)])
def test_untrusted_reading_is_not_tank_balance(fleet, monkeypatch, stable, verified):
    reading(fleet, stable=stable, verified=verified)
    _, bus = summary(fleet, monkeypatch, START+timedelta(seconds=1))
    assert bus['stock_l'] is None and bus['top_up_l'] is None


def test_gps_gap_and_stale_data_block_exact_refill(fleet, monkeypatch):
    reading(fleet); telemetry(fleet, gap=True)
    _, bus = summary(fleet, monkeypatch, START+timedelta(minutes=80, seconds=1))
    assert bus['gps_km'] is not None # Accepted portions remain visible.
    assert bus['stock_l'] is None and bus['top_up_l'] is None
    assert 'gap' in bus['stock_reason'].lower()


@pytest.mark.parametrize('pre,delivered,post_stock,expected,quality', [
    ('18','50','68','68','measured'), ('18','50',None,'68','estimated'), ('0','50','50','50','measured')])
def test_partial_fill_pre_only_and_zero_are_preserved(fleet, monkeypatch, pre, delivered, post_stock, expected, quality):
    obj, _ = add_fill(fleet, occurred_at=START.isoformat(), litres=delivered,
                      pre_stock_l=pre, post_stock_l=post_stock, stock_quality='measured')
    post(fleet, obj)
    _, bus = summary(fleet, monkeypatch, START+timedelta(seconds=1))
    assert D(bus['stock_l']) == D(expected)
    assert D(bus['top_up_l']) == 100-D(expected)
    assert bus['stock_quality'] == quality
    assert D(bus['latest_refill']['pre_stock_l']) == D(pre)


def test_mileage_change_applies_to_stock_and_daily_engine_identically(fleet, monkeypatch):
    reading(fleet, litres=100)
    with fleet['db']() as db:
        old=db.get(Mileage,fleet['mileage']);old.effective_to=START+timedelta(minutes=40)
        db.add(Mileage(vehicle_id=fleet['vehicle'],kmpl=8,effective_from=old.effective_to,
            reason='Synthetic effective change',created_by=fleet['users']['DATA_ADMIN'],
            approved_by=fleet['users']['TRANSPORT_VERIFIER'],evidence_id=fleet['evidence']))
        db.commit()
    telemetry(fleet)
    _, bus=summary(fleet,monkeypatch,START+timedelta(minutes=80,seconds=1))
    assert abs(D(bus['expected_l'])-15)<D('.001')
    assert abs(D(bus['stock_l'])-85)<D('.001')
    assert len(bus['stock_source_ids']['mileage'])==2


def test_missing_mileage_unknown_not_zero_and_missing_stock_does_not_sum(fleet, monkeypatch):
    reading(fleet)
    with fleet['db']() as db:
        db.get(Mileage,fleet['mileage']).approved_by=None
        db.add(Vehicle(bus_number='008',registration='QA-008',tank_capacity_l=220,safe_fill_l=200,operating_target_l=100,demo=True));db.commit()
    telemetry(fleet)
    data,bus=summary(fleet,monkeypatch,START+timedelta(minutes=80,seconds=1))
    assert bus['expected_l'] is None and bus['stock_l'] is None and bus['top_up_l'] is None
    assert data['metrics']['stock_l'] is None and data['contributors']['stock_l']==0
    assert 'mileage' in bus['stock_reason'].lower()


def test_refill_at_exclusive_midnight_not_in_previous_period(fleet, monkeypatch):
    at=day_start(DAY+timedelta(days=1))
    obj,_=add_fill(fleet,occurred_at=at.isoformat(),litres='50',pre_stock_l='18',post_stock_l='68',stock_quality='measured')
    post(fleet,obj)
    _,bus=summary(fleet,monkeypatch,at+timedelta(seconds=1))
    assert bus['refill_count']==0 and bus['latest_refill'] is None
    assert bus['stock_l'] is None


def test_stale_reading_and_incomplete_daily_coverage_stop_estimates(fleet, monkeypatch):
    reading(fleet, at=day_start(DAY))
    with fleet['db']() as db:
        db.add(DailySnapshot(vehicle_id=fleet['vehicle'],service_date=DAY,calculation_version='test',
            input_hash='incomplete',data={'expected_l':'20','gps_km':'80','coverage_pct':'80','status':'provisional'}));db.commit()
    _,bus=summary(fleet,monkeypatch,day_start(DAY+timedelta(days=1)))
    assert bus['stock_l'] is None and bus['top_up_l'] is None


def test_measured_zero_is_not_unknown_and_explanation_has_anchor(fleet, monkeypatch):
    anchor=reading(fleet,litres=0)
    _,bus=summary(fleet,monkeypatch,START+timedelta(seconds=1))
    assert D(bus['stock_l'])==0 and D(bus['top_up_l'])==100
    r=request(fleet,'GET',f"/explain/stock_l?start=2026-09-01&end=2026-09-02&vehicle_id={fleet['vehicle']}",'CORRESPONDENT')
    assert r.status_code==200 and r.json()['sources'][0]['stock_anchor']['id']==anchor
    assert fleet['client'].get('/api/v2/dashboard?start=2026-09-01&end=2026-09-02').status_code==401
