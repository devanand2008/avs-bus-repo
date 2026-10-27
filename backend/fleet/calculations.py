"""Authoritative calculation engine. km, L, km/L, INR; half-open IST periods."""
from datetime import datetime, date, time, timedelta, timezone
from decimal import Decimal, ROUND_HALF_UP
from math import radians, sin, cos, atan2, sqrt
from zoneinfo import ZoneInfo

VERSION = 'cfc-1.2.0'
IST = ZoneInfo('Asia/Kolkata')
ZERO = Decimal('0')
def D(x): return Decimal(str(x))
def q(x, places='0.001'): return None if x is None else D(x).quantize(Decimal(places), rounding=ROUND_HALF_UP)
def utc(t): return t.replace(tzinfo=timezone.utc) if t.tzinfo is None else t.astimezone(timezone.utc)
def day_start(d): return datetime.combine(d, time.min, IST).astimezone(timezone.utc)
def boundaries(start, end):
    if end <= start: raise ValueError('End date is exclusive and must follow start date.')
    if (end-start).days > 366: raise ValueError('Select at most 366 days per report.')
    return day_start(start), day_start(end)

def period(preset='today', today=None, week_start=0):
    t = today or datetime.now(IST).date()
    if preset=='yesterday': return t-timedelta(days=1),t
    if preset in ('this_week','last_week'):
        a=t-timedelta(days=(t.weekday()-week_start)%7)
        if preset=='last_week': a-=timedelta(days=7)
        return a,a+timedelta(days=7)
    if preset in ('this_month','last_month'):
        a=t.replace(day=1)
        if preset=='last_month': return (a-timedelta(days=1)).replace(day=1),a
        return a,(a+timedelta(days=32)).replace(day=1)
    return t,t+timedelta(days=1)

def bike_mean(values, scopes):
    if len(values)!=3 or len(scopes)!=3 or len(set(scopes))!=1: raise ValueError('Three matching survey scopes are required.')
    if any(D(v)<=0 for v in values): raise ValueError('Survey distances must be positive.')
    return sum(map(D,values), ZERO)/3

def expected_use(intervals):
    total=ZERO
    for distance, mileage in intervals:
        if mileage is None: return None
        if D(mileage)<=0: raise ValueError('Mileage must be positive km/L.')
        total+=D(distance)/D(mileage)
    return total

def stock_reconcile(opening, deliveries, closing, expected, transfers_in=ZERO, transfers_out=ZERO):
    disappearance = None if opening is None or closing is None else D(opening)+D(deliveries)+D(transfers_in)-D(transfers_out)-D(closing)
    residual = None if disappearance is None or expected is None else disappearance-D(expected)
    return disappearance,residual

def recommendation(target, stock): return None if stock is None else max(ZERO,D(target)-D(stock))
def aggregate_mileage(distance, consumed): return None if consumed is None or D(consumed)<=0 else D(distance)/D(consumed)
def range_variance(distance, consumed, standard):
    standard_range=D(consumed)*D(standard)
    return standard_range, standard_range-D(distance), D(consumed)-D(distance)/D(standard)


def shortage_metrics(actual, planned, consumed, expected, standard, *, gps_complete, plan_complete, fuel_eligible, uncertainty=None):
    """Positive per-bus review quantities. Never substitute deliveries for use.

    km shortage compares stock-adjusted fuel range with GPS; route shortage
    independently compares approved scheduled km with GPS. Unknown stays null.
    """
    route = max(ZERO, D(planned)-D(actual)) if gps_complete and plan_complete and actual is not None and planned is not None else None
    reliable = fuel_eligible and gps_complete and actual is not None and consumed is not None and D(consumed)>=0 and expected is not None
    diesel = max(ZERO, D(consumed)-D(expected)) if reliable else None
    fuel_range = D(consumed)*D(standard) if reliable and standard is not None and D(standard)>0 else None
    km = max(ZERO, fuel_range-D(actual)) if fuel_range is not None else None
    status = 'insufficient_data' if diesel is None else 'no_positive_variance' if diesel==0 else 'within_uncertainty' if uncertainty is not None and diesel<=D(uncertainty) else 'review_required'
    return {'km_shortage_km':q(km),'diesel_shortage_l':q(diesel),'route_shortage_km':q(route),
            'reconciled_range_km':q(fuel_range),'shortage_status':status,
            'shortage_basis':'Stock-adjusted fuel range versus GPS; route shortage is a separate schedule comparison. Positive variances require review, not automatic deductions.',
            'km_shortage_note':'Requires complete GPS, verified stock boundaries and one applicable mileage model including idling.',
            'diesel_shortage_note':'Requires complete GPS/expected use and verified opening/closing stock; uncertainty is shown separately.'}

def geodesic_km(lat1,lon1,lat2,lon2):
    a,b,c,d=map(radians,map(float,(lat1,lon1,lat2,lon2)))
    h=sin((c-a)/2)**2+cos(a)*cos(c)*sin((d-b)/2)**2
    return D(6371.0088*2*atan2(sqrt(h),sqrt(max(0,1-h))))

def speed_kph(value, unit):
    return None if value is None else D(value)*{'kmh':D(1),'mph':D('1.609344'),'mps':D('3.6')}[unit]

def accepted_segments(points, max_gap=300, max_speed=120):
    """Return accepted geodesic segments and quality counts; never bridge missing intervals."""
    points=sorted(points, key=lambda p:(utc(p.fix_at),p.event_id))
    out=[]; flags={'gaps':0,'jumps':0,'jitter':0,'poor_accuracy':0,'resets':0}; previous=None
    for p in points:
        p.quality='accepted'
        if p.accuracy_m is not None and D(p.accuracy_m)>50:
            flags['poor_accuracy']+=1; p.quality='poor_accuracy'; previous=None; continue
        if previous is None: previous=p; continue
        secs=D((utc(p.fix_at)-utc(previous.fix_at)).total_seconds())
        if secs<=0: p.quality='duplicate_time'; continue
        if p.device_id!=previous.device_id or p.provider!=previous.provider or secs>D(max_gap):
            flags['gaps']+=1; p.quality='gap_boundary'; previous=p; continue
        if p.odometer_km is not None and previous.odometer_km is not None and p.odometer_km<previous.odometer_km:
            flags['resets']+=1
        distance=geodesic_km(previous.lat,previous.lon,p.lat,p.lon)
        inferred=distance*3600/secs
        if inferred>D(max_speed):
            flags['jumps']+=1; p.quality='impossible_jump'; previous=None; continue
        if distance<D('0.015') and (p.ignition is False or p.speed_kph is None or p.speed_kph<D(2)):
            flags['jitter']+=1; p.quality='stationary_jitter'
            out.append((utc(previous.fix_at),utc(p.fix_at),ZERO,previous,p))
            previous=p; continue
        out.append((utc(previous.fix_at),utc(p.fix_at),distance,previous,p)); previous=p
    return out,flags

def split_interval(start,end,distance,cuts=()):
    start,end=utc(start),utc(end)
    if end<=start: return []
    points={start,end}
    next_day=day_start(start.astimezone(IST).date()+timedelta(days=1))
    while next_day<end:
        points.add(next_day); next_day+=timedelta(days=1)
    points.update(utc(c) for c in cuts if start<utc(c)<end)
    points=sorted(points); total=D((end-start).total_seconds())
    return [(a,b,D(distance)*D((b-a).total_seconds())/total) for a,b in zip(points,points[1:])]

FORMULAS = {
 'gps_km': ('Sum accepted geodesic GPS segments; split at IST midnight. Never bridge long gaps.', 'km'),
 'planned_km': ('Sum approved trip distance × trips on each actual service date, including explicit holidays and detours.', 'km'),
 'deviation_km': ('Validated GPS km − approved planned km. Positive = above plan; negative = below plan.', 'km'),
 'delivered_l': ('Sum posted, non-reversed delivery events occurring in [start, end). Pending drafts excluded.', 'L'),
 'expected_l': ('Sum accepted distance interval ÷ mileage version effective in that interval. Separate idling only when excluded from standard.', 'L'),
 'disappearance_l': ('Verified opening + posted deliveries + approved transfers in − approved transfers out − verified closing. Requires exact period boundaries.', 'L'),
 'residual_l': ('Stock-adjusted disappearance − expected engine use. Review signal, subject to completeness and uncertainty gates.', 'L'),
 'fuel_cost': ('Sum posted litres × independently verified invoice unit price. Unverified prices excluded.', 'INR'),
 'top_up_l': ('max(0, operating target − reliable current stock). Unknown stock → no exact recommendation.', 'L'),
 'stock_l': ('Verified stable tank/refill snapshot + subsequent posted deliveries + approved transfers in − approved transfers out − accepted GPS interval engine use. Estimated after movement; unknown with GPS gaps, stale data or missing mileage. See stock_as_of and stock_anchor.', 'L'),
 'refill_count': ('Count distinct posted, non-reversed fuel event IDs in [start,end).', 'events'),
 'km_shortage_km': ('max(0, stock-adjusted disappearance × single approved mileage including idling − validated GPS km). Requires complete GPS, mileage and exact verified stock boundaries. Review variance, not a confirmed loss.', 'km'),
 'diesel_shortage_l': ('max(0, stock-adjusted disappearance − expected engine use). Expected use applies each effective mileage interval. Requires complete GPS and exact verified stock boundaries; consider boundary uncertainty. Review variance, not confirmed theft.', 'L'),
 'route_shortage_km': ('max(0, approved planned km − validated GPS km). Requires complete approved plans and GPS coverage for every date. A route shortfall is separate from fuel-range shortage.', 'km'),
}
