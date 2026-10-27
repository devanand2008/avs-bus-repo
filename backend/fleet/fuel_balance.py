"""Traceable tank estimates. GPS estimates engine use; it never measures tank litres."""
from datetime import timedelta
from types import SimpleNamespace
from sqlalchemy import or_
from fleet.models import TankReading, FuelEvent, Transfer, GPSPoint, DeviceMapping, Mileage, Assignment, DailySnapshot
from fleet.calculations import D, ZERO, IST, utc, day_start, accepted_segments, split_interval, q


def mileage_context(db, vehicle_id):
    mileages = db.query(Mileage).filter(Mileage.vehicle_id == vehicle_id, Mileage.approved_by != None, Mileage.archived == False).all()
    assignments = db.query(Assignment).filter(Assignment.vehicle_id == vehicle_id, Assignment.archived == False).order_by(Assignment.starts_at.desc()).all()
    cuts = [t for obj in mileages + assignments for t in
            ((obj.effective_from, obj.effective_to) if isinstance(obj, Mileage) else (obj.starts_at, obj.ends_at)) if t]
    return mileages, assignments, cuts


def interval_use(mileages, assignments, start, end, km, p1, p2):
    assigned = next((a for a in assignments if utc(a.starts_at) <= start and (not a.ends_at or utc(a.ends_at) > start)), None)
    profiles = [m for m in mileages if utc(m.effective_from) <= start and (not m.effective_to or utc(m.effective_to) > start)
                and (not m.route_id or (assigned and m.route_id == assigned.route_id))]
    profiles.sort(key=lambda m: (m.route_id is not None, utc(m.effective_from)), reverse=True)
    m = profiles[0] if profiles else None
    if m is None:
        # Without an approved model, even stationary ignition may consume fuel.
        return None, ZERO, None
    idle = ZERO
    if not m.includes_idling and p1.ignition is True and p2.ignition is True and km == 0:
        idle = D(m.idle_lph) * D((end-start).total_seconds()) / 3600
    return km / D(m.kmpl) + idle, idle, m


def tank_balance(db, vehicle, at, rules):
    """Balance at a reporting cutoff, with anchor, coverage gates and source IDs.

    Refill post-readings are independently verified operational readings, not
    automatic sensor measurements. A pre-only refill can anchor an estimate.
    Exact closing tank readings may occur at the exclusive period boundary;
    fuel events at that boundary belong to the following period.
    """
    at = utc(at)
    result = {'stock_l': None, 'stock_quality': 'unknown', 'stock_as_of': None,
              'stock_reason': 'Add an independently verified stable tank reading or refill snapshot.',
              'stock_anchor': None, 'stock_source_ids': {'fuel': [], 'transfers': [], 'gps': [], 'mileage': []}}
    reading = db.query(TankReading).filter(TankReading.vehicle_id == vehicle.id, TankReading.occurred_at <= at,
        TankReading.verified_by != None, TankReading.quality.in_(['measured', 'estimated']), TankReading.stable == True).order_by(TankReading.occurred_at.desc(), TankReading.created_at.desc()).first()
    fill = db.query(FuelEvent).filter(FuelEvent.vehicle_id == vehicle.id, FuelEvent.occurred_at < at,
        FuelEvent.status == 'posted', FuelEvent.verified_by != None, FuelEvent.stock_quality.in_(['measured', 'estimated']),
        or_(FuelEvent.post_stock_l != None, FuelEvent.pre_stock_l != None)).order_by(FuelEvent.occurred_at.desc(), FuelEvent.created_at.desc()).first()
    # A stable reading wins a same-time tie: a refill reading may be before or after the pump.
    if reading and (not fill or utc(reading.occurred_at) >= utc(fill.occurred_at)):
        anchor, amount, quality = utc(reading.occurred_at), D(reading.litres), reading.quality
        kind, key = 'tank_reading', reading.id
    elif fill:
        anchor = utc(fill.occurred_at)
        amount = D(fill.post_stock_l) if fill.post_stock_l is not None else D(fill.pre_stock_l) + D(fill.litres)
        quality = fill.stock_quality if fill.post_stock_l is not None else 'estimated'
        kind, key = 'verified_refill', fill.id
    else:
        return result
    result['stock_anchor'] = {'type': kind, 'id': key, 'at': anchor.isoformat(), 'litres': str(q(amount)), 'quality': quality}
    result['stock_as_of'] = anchor.isoformat()
    sources = result['stock_source_ids']
    fills = db.query(FuelEvent).filter(FuelEvent.vehicle_id == vehicle.id, FuelEvent.status == 'posted',
        FuelEvent.occurred_at >= anchor, FuelEvent.occurred_at < at).all()
    # A refill anchor already includes its own delivered quantity. Other same-time
    # events have ambiguous ordering; refuse an exact balance instead of guessing.
    if any(utc(f.occurred_at) == anchor and f.id != key for f in fills):
        result['stock_reason'] = 'Same-time tank/refill records need an unambiguous post-fill reading.'
        return result
    fills = [f for f in fills if f.id != key]
    moves = db.query(Transfer).filter(or_(Transfer.from_vehicle_id == vehicle.id, Transfer.to_vehicle_id == vehicle.id),
        Transfer.approved_by != None, Transfer.occurred_at >= anchor, Transfer.occurred_at < at).all()
    sources['fuel'] = [f.id for f in fills]
    sources['transfers'] = [t.id for t in moves]
    movement = sum((D(t.litres) if t.to_vehicle_id == vehicle.id else -D(t.litres) for t in moves), ZERO)
    amount += sum((D(f.litres) for f in fills), ZERO) + movement
    use, computed_at = ZERO, anchor
    if at > anchor:
        # Completed midnight-to-midnight balances can use rebuildable summaries,
        # but only when every day has complete service-window coverage.
        if anchor == day_start(anchor.astimezone(IST).date()) and at == day_start(at.astimezone(IST).date()):
            rows = db.query(DailySnapshot).filter(DailySnapshot.vehicle_id == vehicle.id,
                DailySnapshot.service_date >= anchor.astimezone(IST).date(), DailySnapshot.service_date < at.astimezone(IST).date()).all()
            if len(rows) == (at-anchor).days and rows and all(r.data.get('expected_l') is not None and D(r.data.get('coverage_pct') or 0) == 100 for r in rows):
                use = sum((D(r.data['expected_l']) for r in rows), ZERO)
                sources['daily'] = [r.id for r in rows]
                computed_at = at
        if computed_at != at:
            gap = int(rules.get('gps_gap_seconds', 300))
            # Bound raw queries; older anchors need daily reconciliation/a fresh reading.
            if at-anchor > timedelta(days=7):
                result['stock_reason'] = 'A fresh verified reading is required; continuous GPS estimation is limited to seven days.'
                return result
            points = db.query(GPSPoint).filter(GPSPoint.vehicle_id == vehicle.id, GPSPoint.fix_at >= anchor-timedelta(seconds=gap), GPSPoint.fix_at <= at).all()
            mappings = db.query(DeviceMapping).filter_by(vehicle_id=vehicle.id).all()
            fields = ('id', 'fix_at', 'event_id', 'provider', 'device_id', 'accuracy_m', 'odometer_km', 'lat', 'lon', 'ignition', 'speed_kph')
            # Quality evaluation must not mutate persisted telemetry during a GET.
            points = [SimpleNamespace(**{k: getattr(p, k) for k in fields}) for p in points if any(m.provider == p.provider and m.device_id == p.device_id and utc(m.starts_at) <= utc(p.fix_at) and (not m.ends_at or utc(m.ends_at) > utc(p.fix_at)) for m in mappings)]
            segments, _ = accepted_segments(points, gap, float(rules.get('max_speed_kph', 120)))
            context = mileage_context(db, vehicle.id)
            cursor = anchor
            use = ZERO
            for a, b, km, p1, p2 in segments:
                if b <= anchor or a >= at:
                    continue
                for x, y, distance in split_interval(a, b, km, [anchor, at] + context[2]):
                    if x < anchor or y > at:
                        continue
                    if x != cursor:
                        result['stock_reason'] = 'GPS gap or rejected segment after the last stock reading; remaining diesel is unknown.'
                        return result
                    litres, _, model = interval_use(context[0], context[1], x, y, distance, p1, p2)
                    if litres is None:
                        result['stock_reason'] = 'An approved mileage version is missing after the stock reading.'
                        return result
                    use += litres
                    sources['gps'].extend([p1.id, p2.id]); sources['mileage'].append(model.id)
                    cursor = y
            if cursor == anchor and at-anchor <= timedelta(minutes=10) and not fills and not moves:
                # Display a recent verified snapshot at its own time, never pretend
                # it is a live tank sensor value.
                computed_at = anchor
            elif cursor > anchor and at-cursor <= timedelta(seconds=gap) and not any(utc(f.occurred_at) > cursor for f in fills) and not any(utc(t.occurred_at) > cursor for t in moves):
                computed_at = cursor
                quality = 'estimated'
            else:
                result['stock_reason'] = 'GPS is stale or incomplete since the stock reading. Capture a fresh verified tank reading.'
                return result
    amount -= use
    if not ZERO <= amount <= D(vehicle.tank_capacity_l):
        result['stock_reason'] = 'Calculated stock is outside physical capacity; reconcile readings, deliveries and GPS.'
        return result
    if computed_at > anchor or fills or moves:
        quality = 'estimated'
    for k in ('gps', 'mileage'):
        sources[k] = sorted(set(sources[k]))
    result.update(stock_l=q(amount), stock_quality=quality, stock_as_of=computed_at.isoformat(),
        stock_reason='Verified snapshot at the displayed time.' if quality == 'measured' else
        'Estimate: anchor + posted deliveries + approved net transfers − GPS-based engine use. Not a sensor measurement.')
    return result
