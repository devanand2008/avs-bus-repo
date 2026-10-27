from datetime import date, timedelta
from decimal import Decimal
import pytest
from pydantic import ValidationError
from fleet.schemas import RouteInput, CollegeInput
from fleet.models import Vehicle, Case, Assignment, Mileage, Route, GPSPoint
from fleet.calculations import day_start
from fleet.services import rebuild, summarise_bus
from test_workflows import request, add_fill, decision
from fleet.models import TankReading, DailySnapshot, Transfer, Evidence, PlannedTrip


@pytest.mark.parametrize('coordinates', [None, [None, None], [['x', 11], [78, 11]], [[True, 11], [78, 11]], [[181, 11], [78, 11]]])
def test_malformed_geometry_is_validation_error(coordinates):
    with pytest.raises(ValidationError):
        RouteInput(code='R1', name='Test route', trip_km=80,
                   geometry={'type': 'LineString', 'coordinates': coordinates})


@pytest.mark.parametrize('value', ['NaN', 'Infinity', 'abc', None, {}, True, 0, -1])
def test_malformed_rule_is_validation_error(value):
    with pytest.raises(ValidationError):
        CollegeInput(name='Test college', short_name='Test', rules={'gps_gap_seconds': value})


@pytest.mark.parametrize('changes', [
    {'post_stock_l': 221, 'stock_quality': 'measured'},
    {'pre_stock_l': 10, 'stock_quality': 'unknown'},
    {'post_stock_l': 10, 'stock_quality': 'unknown'},
])
def test_edit_cannot_bypass_fuel_constraints(fleet, changes):
    obj, payload = add_fill(fleet)
    response = request(fleet, 'PUT', f"/fuel/{obj['id']}?version={obj['version']}", 'FUELLER', json={**payload, **changes})
    assert response.status_code == 422, response.text


def test_edit_correction_requires_reversed_same_bus(fleet):
    obj, payload = add_fill(fleet)
    response = request(fleet, 'PUT', f"/fuel/{obj['id']}?version={obj['version']}", 'FUELLER', json={**payload, 'correction_of': obj['id']})
    assert response.status_code == 422


def test_posting_rechecks_changed_capacity(fleet):
    obj, _ = add_fill(fleet)
    submitted = decision(fleet, f"/fuel/{obj['id']}/submit", obj, 'FUELLER').json()
    with fleet['db']() as db:
        bus = db.get(Vehicle, fleet['vehicle'])
        bus.tank_capacity_l = 40; bus.safe_fill_l = 35; bus.operating_target_l = 30
        db.commit()
    response = decision(fleet, f"/fuel/{obj['id']}/verify", submitted)
    assert response.status_code == 422


def test_case_explanation_rejects_stale_version(fleet):
    with fleet['db']() as db:
        case = Case(vehicle_id=fleet['vehicle'], rule='test', explanation='Synthetic case', inputs={}, fingerprint='TEST-CASE')
        db.add(case); db.commit(); case_id = case.id
    path = f'/cases/{case_id}/explanation'
    assert decision(fleet, path, {'version': 1}, 'DRIVER').status_code == 200
    assert decision(fleet, path, {'version': 1}, 'DRIVER').status_code == 409


def test_route_mileage_changes_inside_gps_interval(fleet):
    day = date(2026, 9, 1); start = day_start(day) + timedelta(hours=8)
    with fleet['db']() as db:
        previous = db.query(Assignment).filter_by(vehicle_id=fleet['vehicle']).one()
        previous.ends_at = start + timedelta(seconds=30)
        other = Route(code='R2', name='Other route', trip_km=80, scope='round_trip', created_by=fleet['users']['DATA_ADMIN'], approved_by=fleet['users']['TRANSPORT_VERIFIER'])
        db.add(other); db.flush()
        db.add(Assignment(vehicle_id=fleet['vehicle'], driver_id=fleet['driver'], route_id=other.id, starts_at=previous.ends_at, reason='Synthetic substitution'))
        db.add(Mileage(vehicle_id=fleet['vehicle'], route_id=other.id, kmpl=8, effective_from=day_start(day), reason='Route-specific standard', created_by=fleet['users']['DATA_ADMIN'], approved_by=fleet['users']['TRANSPORT_VERIFIER'], evidence_id=fleet['evidence']))
        for i in range(2):
            db.add(GPSPoint(vehicle_id=fleet['vehicle'], provider='test_provider', device_id='DEVICE-007', event_id=f'CUT-{i}', fix_at=start+timedelta(seconds=60*i), lat=11.65, lon=78.1+0.001*i, speed=10, source_unit='kmh', speed_kph=10))
        db.flush(); rebuild(db, fleet['vehicle'], day, day+timedelta(days=1)); db.flush()
        summary = summarise_bus(db, db.get(Vehicle, fleet['vehicle']), day, day+timedelta(days=1))
        expected = Decimal(str(summary['gps_km'])) * Decimal('0.1875')
        assert abs(Decimal(str(summary['expected_l']))-expected) < Decimal('0.01')


@pytest.mark.parametrize('missing,consumption,expected', [(False, 10, '70'), (True, 10, None), (False, 100, None)])
def test_estimated_stock_requires_complete_history_and_accounts_for_transfers(fleet, missing, consumption, expected):
    with fleet['db']() as db:
        first = date(2026, 9, 1)
        db.add(TankReading(vehicle_id=fleet['vehicle'], occurred_at=day_start(first), litres=100, quality='measured', source='dip', stable=True, reason='Test boundary', created_by=fleet['users']['DATA_ADMIN'], verified_by=fleet['users']['TRANSPORT_VERIFIER']))
        other = Vehicle(bus_number='TEST-OTHER', registration='TEST-TRANSFER', tank_capacity_l=220, safe_fill_l=200, operating_target_l=100)
        db.add(other); db.flush()
        db.add(Transfer(from_vehicle_id=fleet['vehicle'], to_vehicle_id=other.id, occurred_at=day_start(first)+timedelta(hours=2), litres=10, reason='Test approved transfer', created_by=fleet['users']['DATA_ADMIN'], approved_by=fleet['users']['TRANSPORT_VERIFIER']))
        for offset in range(1 if missing else 0, 2):
            db.add(DailySnapshot(vehicle_id=fleet['vehicle'], service_date=first+timedelta(days=offset), calculation_version='test', input_hash='test', data={'expected_l':str(consumption), 'coverage_pct':'100', 'status':'provisional'}))
        db.flush()
        # Selected period starts after the reading. The estimate must include both days.
        result = summarise_bus(db, db.get(Vehicle, fleet['vehicle']), first+timedelta(days=1), first+timedelta(days=2))
        if expected is None:
            assert result['stock_l'] is None and result['top_up_l'] is None
        else:
            assert Decimal(str(result['stock_l'])) == Decimal(expected)
            assert result['stock_quality'] == 'estimated'


def test_driver_cannot_list_unrelated_evidence(fleet):
    obj, _ = add_fill(fleet)
    with fleet['db']() as db:
        hidden = Evidence(vehicle_id=fleet['vehicle'], uploaded_by=fleet['users']['DATA_ADMIN'], filename='unrelated-private.png', mime='image/png', size=1, sha256='0'*64, storage_key='not-downloaded.png')
        db.add(hidden); db.commit(); hidden_id=hidden.id
    response = request(fleet, 'GET', f"/buses/{fleet['vehicle']}/detail?start=2026-09-01&end=2026-09-03", 'DRIVER')
    assert response.status_code == 200
    evidence = response.json()['history']['evidence']
    assert [row['id'] for row in evidence] == [fleet['evidence']]
    assert request(fleet, 'GET', f'/evidence/{hidden_id}/download', 'DRIVER').status_code == 403


def test_future_plan_approval_builds_selected_date(fleet):
    from fleet.models import now
    from fleet.calculations import IST
    day = now().astimezone(IST).date()+timedelta(days=10)
    response = request(fleet, 'POST', '/resources/plans', 'DATA_ADMIN', json={'vehicle_id':fleet['vehicle'], 'route_id':fleet['route'], 'service_date':str(day), 'trips':2, 'trip_km':80, 'scope':'round_trip', 'reason':'Approved future test schedule'})
    assert response.status_code == 201, response.text
    plan = response.json()
    assert decision(fleet, f"/resources/plans/{plan['id']}/approve", plan).status_code == 200
    with fleet['db']() as db:
        result = summarise_bus(db, db.get(Vehicle, fleet['vehicle']), day, day+timedelta(days=1))
        assert Decimal(str(result['planned_km'])) == 160


def test_historical_rebuild_is_not_truncated_after_one_year(fleet, monkeypatch):
    from fleet import resources
    from fleet.models import now
    from fleet.calculations import IST
    today = now().astimezone(IST).date()
    calls=[]; invalidations=[]
    monkeypatch.setattr(resources, 'rebuild', lambda db, vid, a, b: calls.append((a,b)))
    monkeypatch.setattr(resources, 'invalidate_reports', lambda db, vid, a, b: invalidations.append((a,b)))
    with fleet['db']() as db:
        mileage = db.get(Mileage, fleet['mileage'])
        mileage.effective_from = day_start(today-timedelta(days=800))
        resources.affected(db, mileage)
    assert calls[0][0] == today-timedelta(days=800)
    assert calls[-1][1] == today+timedelta(days=1)
    assert all(a[1] == b[0] for a,b in zip(calls,calls[1:]))
    assert invalidations[0][1] == day_start(today+timedelta(days=1))
