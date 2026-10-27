import hashlib
import json
import re
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone
from decimal import Decimal
from fastapi import HTTPException
from sqlalchemy import or_
from fleet.models import *
from fleet.calculations import *
from fleet.auth import vehicle_scope, aware
from fleet.fuel_balance import tank_balance, mileage_context, interval_use

MODELS = {'vehicles':Vehicle,'drivers':Driver,'routes':Route,'assignments':Assignment,'devices':DeviceMapping,'surveys':Survey,'mileage':Mileage,'plans':PlannedTrip,'tank-readings':TankReading,'calibrations':Calibration,'transfers':Transfer,'manual-trips':Trip,'fuel':FuelEvent,'cases':Case,'reports':Report,'approvals':Approval,'audit':Audit}

def clean(value):
    if isinstance(value, Decimal): return str(value)
    if isinstance(value, (date,datetime)): return value.isoformat()
    if isinstance(value, dict): return {k:clean(v) for k,v in value.items()}
    if isinstance(value, (list,tuple)): return [clean(v) for v in value]
    return value

def serial(obj, user=None):
    data={c.name:clean(getattr(obj,c.name)) for c in obj.__table__.columns}
    for secret in ('password_hash','token_hash','mfa_secret','storage_key'): data.pop(secret,None)
    if isinstance(obj,Driver) and user and user.role not in {'SYSTEM_ADMIN','DATA_ADMIN'}:
        for private in ('mobile','licence_number'): data.pop(private,None)
    if isinstance(obj,Survey):
        data['mean_km']=str(q(bike_mean([obj.b1_km,obj.b2_km,obj.b3_km],[obj.scope]*3)))
        data['spread_km']=str(q(max(obj.b1_km,obj.b2_km,obj.b3_km)-min(obj.b1_km,obj.b2_km,obj.b3_km)))
    return data

def digest(value): return hashlib.sha256(json.dumps(clean(value),sort_keys=True,separators=(',',':')).encode()).hexdigest()

def equivalent(a,b):
    if isinstance(a,datetime) and isinstance(b,datetime):return utc(a)==utc(b)
    if isinstance(a,Decimal) or isinstance(b,Decimal):return a is not None and b is not None and D(a)==D(b)
    return a==b

def audit(db,user,action,obj,reason,before=None):
    after=serial(obj,user)
    # Operational evidence is append-only through the API; digest catches accidental alteration.
    entry=Audit(actor_id=user.id if user else None,action=action,entity_type=obj.__tablename__,entity_id=obj.id,vehicle_id=getattr(obj,'vehicle_id',None) or (obj.id if isinstance(obj,Vehicle) else None),before=before,after=after,reason=reason,digest=digest({'before':before,'after':after,'reason':reason}))
    db.add(entry)

def get_college(db):
    c=db.query(College).first()
    if c is None: raise HTTPException(503,'Database is not initialised. Run migrate and bootstrap.')
    return c

def vehicle(db,id):
    v=db.get(Vehicle,id)
    if v is None: raise HTTPException(404,'Bus not found.')
    return v

def natural(value): return [(0,int(t)) if t.isdigit() else (1,t.lower()) for t in re.split('(\d+)',value)]

def assignment_at(db, vehicle_id, timestamp):
    return db.query(Assignment).filter(Assignment.vehicle_id==vehicle_id,Assignment.archived==False,Assignment.starts_at<=timestamp,or_(Assignment.ends_at==None,Assignment.ends_at>timestamp)).order_by(Assignment.starts_at.desc()).first()

def invalidate_reports(db,vehicle_id,start,end=None):
    a=utc(start).astimezone(IST).date(); b=utc(end or start).astimezone(IST).date()
    for r in db.query(Report).filter(or_(Report.vehicle_id==vehicle_id,Report.vehicle_id==None),Report.start_date<=b,Report.end_date>a).all(): r.needs_revision=True

def rule_case(db,vehicle_id,rule,explanation,inputs,fingerprint,rule_version='1.0'):
    if db.query(Case).filter_by(fingerprint=fingerprint).first(): return
    db.add(Case(vehicle_id=vehicle_id,rule=rule,explanation=explanation,inputs=clean(inputs),fingerprint=fingerprint,rule_version=rule_version))

def rebuild(db,vehicle_id,start_date,end_date):
    """Rebuild only affected days from source events; version changed results, flag frozen reports."""
    start,end=boundaries(start_date,end_date); c=get_college(db); rules=c.rules
    v=vehicle(db,vehicle_id)
    points=db.query(GPSPoint).filter(GPSPoint.vehicle_id==v.id,GPSPoint.fix_at>=start-timedelta(seconds=int(rules.get('gps_gap_seconds',300))),GPSPoint.fix_at<end+timedelta(seconds=int(rules.get('gps_gap_seconds',300)))).all()
    mappings=db.query(DeviceMapping).filter_by(vehicle_id=v.id).all()
    valid_points=[]
    for point in points:
        if any(m.provider==point.provider and m.device_id==point.device_id and utc(m.starts_at)<=utc(point.fix_at) and (not m.ends_at or utc(m.ends_at)>utc(point.fix_at)) for m in mappings): valid_points.append(point)
        else: point.quality='unmapped_at_fix'
    segments,flags=accepted_segments(valid_points,int(rules.get('gps_gap_seconds',300)),float(rules.get('max_speed_kph',120)))
    mileages,assignments,cuts=mileage_context(db,v.id)
    daily=defaultdict(lambda:{'gps_km':ZERO,'expected_l':ZERO,'idle_l':ZERO,'coverage_seconds':0,'sources':set(),'mileage_ids':set(),'missing_mileage':False,'points':[],'flags':dict.fromkeys(flags,0),'route_deviations':0})
    for point in points:
        d=utc(point.fix_at).astimezone(IST).date()
        if start_date<=d<end_date:
            daily[d]['points'].append(point.id)
            tag={'gap_boundary':'gaps','impossible_jump':'jumps','stationary_jitter':'jitter','poor_accuracy':'poor_accuracy'}.get(point.quality)
            if tag: daily[d]['flags'][tag]+=1
    route_cache={r.id:r for r in db.query(Route).filter(Route.id.in_({a.route_id for a in assignments if a.route_id})).all()}
    def assigned_at(t):return next((a for a in assignments if utc(a.starts_at)<=t and (not a.ends_at or utc(a.ends_at)>t)),None)
    # Derived trips are rebuilt from immutable raw evidence; crossing midnight keeps one underlying trip.
    groups=[]
    for segment in segments:
        if not groups or groups[-1][-1][1]!=segment[0] or groups[-1][-1][4].device_id!=segment[3].device_id:groups.append([])
        groups[-1].append(segment)
    db.query(Trip).filter(Trip.vehicle_id==v.id,Trip.source=='provider_gps',Trip.starts_at<end,Trip.ends_at>start).delete(synchronize_session=False)
    for group in groups:
        a,b=group[0][0],group[-1][1]
        if not (a<end and b>start):continue
        assignment=assigned_at(a)
        trip_id=str(__import__('uuid').uuid5(__import__('uuid').NAMESPACE_URL,f'cfc-trip:{v.id}:{group[0][3].provider}:{group[0][3].device_id}:{group[0][3].event_id}'))
        existing=db.get(Trip,trip_id)
        if not existing:db.add(Trip(id=trip_id,vehicle_id=v.id,starts_at=a,ends_at=b,source='provider_gps',distance_km=q(sum((s[2] for s in group),ZERO),'0.00001'),driver_id=assignment.driver_id if assignment else None,reason='Derived accepted GPS segment group; source evidence remains immutable.'))
    for a,b,distance,p1,p2 in segments:
        for x,y,km in split_interval(a,b,distance,cuts):
            d=x.astimezone(IST).date()
            if not start_date<=d<end_date: continue
            row=daily[d]; row['gps_km']+=km; row['coverage_seconds']+=(y-x).total_seconds(); row['sources'].update((p1.id,p2.id))
            assigned=assigned_at(x)
            litres,idle,m=interval_use(mileages,assignments,x,y,km,p1,p2)
            if m:
                row['mileage_ids'].add(m.id); row['expected_l']+=litres; row['idle_l']+=idle
            else: row['missing_mileage']=True
            if assigned and assigned.route_id:
                route=route_cache.get(assigned.route_id)
                if route and route.approved_by and route.geometry:
                    coords=route.geometry.get('coordinates',[])
                    # Sampled corridor test is a suggestion only, never an adjudicated distance.
                    if coords and min(geodesic_km(p2.lat,p2.lon,lat,lon) for lon,lat in coords)>D(rules.get('route_tolerance_m',500))/1000:
                        row['route_deviations']+=1
    manual=db.query(Trip).filter(Trip.vehicle_id==v.id,Trip.source=='manual',Trip.reviewer_id!=None,Trip.starts_at<end,Trip.ends_at>start).all()
    manual_days=defaultdict(lambda:ZERO)
    for trip in manual:
        for a,b,km in split_interval(trip.starts_at,trip.ends_at,trip.distance_km):
            if start<=a<end: manual_days[a.astimezone(IST).date()]+=km
    plans=db.query(PlannedTrip).filter(PlannedTrip.vehicle_id==v.id,PlannedTrip.service_date>=start_date,PlannedTrip.service_date<end_date,PlannedTrip.approved_by!=None,PlannedTrip.archived==False).all()
    p_by=defaultdict(list)
    for p in plans:p_by[p.service_date].append(p)
    d=start_date; updated=0
    while d<end_date:
        row=daily[d]; planned=sum((p.trip_km*p.trips for p in p_by[d]),ZERO) if p_by[d] else None
        a=day_start(d); b=a+timedelta(days=1)
        last=max((utc(p.fix_at) for p in points if a<=utc(p.fix_at)<b),default=None)
        valid_count=sum(1 for p in valid_points if a<=utc(p.fix_at)<b and p.quality not in ('poor_accuracy','impossible_jump'))
        # Coverage only has a denominator when approved service windows exist. Never invent tracking hours from distance.
        windows=[(utc(datetime.fromisoformat(w['start'])),utc(datetime.fromisoformat(w['end']))) for p in p_by[d] for w in (p.service_windows or [])]
        expected_seconds=sum(((y-x).total_seconds() for x,y in windows),0)
        covered_seconds=sum((max(0,(min(sb,y)-max(sa,x)).total_seconds()) for sa,sb,_,_,_ in segments for x,y in windows),0)
        coverage=min(D(100),D(covered_seconds)/D(expected_seconds)*100) if expected_seconds else (D(100) if planned==0 else None)
        actual=q(row['gps_km']) if len(row['sources'])>=2 else (ZERO if planned==0 and valid_count else None)
        expected=None if actual is None or row['missing_mileage'] else q(row['expected_l'])
        data=clean({'gps_km':actual,'manual_km':q(manual_days[d]),'planned_km':q(planned),'deviation_km':None if actual is None or planned is None else q(actual-planned),'expected_l':expected,'idle_l':q(row['idle_l']),'coverage_pct':q(coverage,'0.1'),'coverage_basis':'Accepted GPS segment seconds within approved service windows / approved service-window seconds; unknown without approved windows.','last_fix':last,'gps_source_ids':sorted(row['sources']),'point_ids':sorted(row['points']),'mileage_ids':sorted(row['mileage_ids']),'plan_ids':[p.id for p in p_by[d]],'flags':row['flags'],'route_deviation_samples':row['route_deviations'],'status':'provisional' if d>=now().astimezone(IST).date() or actual is None or coverage is None or coverage<90 or expected is None else 'final'})
        fingerprint=digest(data)
        snap=db.query(DailySnapshot).filter_by(vehicle_id=v.id,service_date=d).first()
        if not snap:
            snap=DailySnapshot(vehicle_id=v.id,service_date=d,calculation_version=VERSION,input_hash=fingerprint,data=data); db.add(snap); updated+=1
        elif snap.input_hash!=fingerprint or snap.calculation_version!=VERSION:
            snap.data=data; snap.input_hash=fingerprint; snap.revision+=1; snap.calculation_version=VERSION; updated+=1; invalidate_reports(db,v.id,a,b-timedelta(microseconds=1))
        if d<now().astimezone(IST).date() and planned and (actual is None or (coverage is not None and coverage<50)):
            rule_case(db,v.id,'tracker_coverage','GPS coverage is incomplete. Distance and consumption may be understated.',{'date':d,'snapshot':data},f'coverage:{v.id}:{d}')
        if row['route_deviations']:
            rule_case(db,v.id,'route_corridor','Some accepted fixes are outside the configured route sample corridor. Verify geometry and authorised detours.',{'date':d,'sample_count':row['route_deviations']},f'route:{v.id}:{d}')
        d+=timedelta(days=1)
    db.flush()
    evaluate_stock_rules(db,v,start_date,end_date)
    return updated

def evaluate_stock_rules(db,v,start_date,end_date):
    """Quality-gated review suggestions; never a theft finding or payroll action."""
    start,end=boundaries(start_date,end_date);rules=get_college(db).rules;version=str(rules.get('rule_version','1.0'))
    s=summarise_bus(db,v,start_date,end_date)
    if s['residual_eligible'] and s['residual_l'] is not None and abs(D(s['residual_l']))>D(rules.get('residual_l',10))+D(s['uncertainty_l'] or 0):
        rule_case(db,v.id,'stock_residual','Stock-adjusted disappearance differs from complete modelled engine use beyond the configured review threshold and boundary uncertainty. Investigate evidence and comparable conditions.',{'period':[str(start_date),str(end_date)],'residual_l':s['residual_l'],'uncertainty_l':s['uncertainty_l'],'calculation_version':VERSION,'sources':s['source_ids']},f'residual:{v.id}:{start_date}:{end_date}',version)
    readings=db.query(TankReading).filter(TankReading.vehicle_id==v.id,TankReading.occurred_at>=start,TankReading.occurred_at<=end,TankReading.verified_by!=None,TankReading.quality=='measured',TankReading.stable==True).order_by(TankReading.occurred_at).all()
    for a,b in zip(readings,readings[1:]):
        loss=a.litres-b.litres;uncertainty=a.uncertainty_l+b.uncertainty_l
        if loss<=D(rules.get('park_drop_l',10))+uncertainty:continue
        flows=db.query(Transfer).filter(or_(Transfer.from_vehicle_id==v.id,Transfer.to_vehicle_id==v.id),Transfer.approved_by!=None,Transfer.occurred_at>=a.occurred_at,Transfer.occurred_at<b.occurred_at).count()
        fills=db.query(FuelEvent).filter(FuelEvent.vehicle_id==v.id,FuelEvent.status=='posted',FuelEvent.occurred_at>=a.occurred_at,FuelEvent.occurred_at<b.occurred_at).count()
        if flows or fills:continue
        points=db.query(GPSPoint).filter(GPSPoint.vehicle_id==v.id,GPSPoint.fix_at>=a.occurred_at,GPSPoint.fix_at<=b.occurred_at).order_by(GPSPoint.fix_at).all()
        if len(points)<2 or not all(p.ignition is False for p in points):continue
        segments,flags=accepted_segments(points,int(rules.get('gps_gap_seconds',300)),float(rules.get('max_speed_kph',120)))
        span=(utc(b.occurred_at)-utc(a.occurred_at)).total_seconds();covered=sum((y-x).total_seconds() for x,y,*_ in segments)
        if span<=0 or covered/span<.9 or flags['gaps'] or flags['jumps'] or sum((km for _,_,km,_,_ in segments),ZERO)>D('.02'):continue
        rule_case(db,v.id,'parked_stock_drop','Two independently verified stable readings show a sustained parked stock drop with valid ignition-off coverage and no authorised transfer. Verify slope, calibration, slosh and faults before deciding.',{'reading_ids':[a.id,b.id],'gps_source_ids':[p.id for p in points],'drop_l':str(loss),'uncertainty_l':str(uncertainty)},f'parked:{a.id}:{b.id}',version)

def reliable_boundary(db,vehicle_id,timestamp):
    return db.query(TankReading).filter(TankReading.vehicle_id==vehicle_id,TankReading.occurred_at==timestamp,TankReading.quality=='measured',TankReading.stable==True,TankReading.verified_by!=None).order_by(TankReading.created_at.desc()).first()

def summarise_bus(db,v,start_date,end_date):
    start,end=boundaries(start_date,end_date)
    daily=db.query(DailySnapshot).filter(DailySnapshot.vehicle_id==v.id,DailySnapshot.service_date>=start_date,DailySnapshot.service_date<end_date).order_by(DailySnapshot.service_date).all()
    fills=db.query(FuelEvent).filter(FuelEvent.vehicle_id==v.id,FuelEvent.occurred_at>=start,FuelEvent.occurred_at<end,FuelEvent.status=='posted').all()
    total_days=(end_date-start_date).days
    def total(key):
        vals=[D(r.data[key]) for r in daily if r.data.get(key) is not None]
        return q(sum(vals,ZERO)) if vals else None
    actual=total('gps_km'); planned=total('planned_km'); expected=total('expected_l')
    expected_complete=len(daily)==total_days and all(s.data.get('expected_l') is not None for s in daily)
    gps_days=sum(s.data.get('gps_km') is not None for s in daily)
    delivered=sum((f.litres for f in fills),ZERO)
    opening=reliable_boundary(db,v.id,start); closing=reliable_boundary(db,v.id,end)
    transfers=db.query(Transfer).filter(or_(Transfer.from_vehicle_id==v.id,Transfer.to_vehicle_id==v.id),Transfer.occurred_at>=start,Transfer.occurred_at<end,Transfer.approved_by!=None).all()
    tin=sum((t.litres for t in transfers if t.to_vehicle_id==v.id),ZERO); tout=sum((t.litres for t in transfers if t.from_vehicle_id==v.id),ZERO)
    disappearance,residual=stock_reconcile(opening.litres if opening else None,delivered,closing.litres if closing else None,expected if expected_complete else None,tin,tout)
    uncertainty=(opening.uncertainty_l+closing.uncertainty_l) if opening and closing else None
    coverage_vals=[D(s.data['coverage_pct']) for s in daily if s.data.get('coverage_pct') is not None and D(s.data.get('planned_km') or 0)>0]
    coverage=sum(coverage_vals,ZERO)/len(coverage_vals) if coverage_vals else None
    eligible=residual is not None and expected_complete and coverage is not None and coverage>=90
    historical=assignment_at(db,v.id,min(end-timedelta(microseconds=1),now()) if start<=now() else start)
    dr=db.get(Driver,historical.driver_id) if historical and historical.driver_id else None
    rt=db.get(Route,historical.route_id) if historical and historical.route_id else None
    survey=db.query(Survey).filter(Survey.route_id==rt.id,Survey.approved_by!=None,Survey.date<end_date).order_by(Survey.date.desc()).first() if rt else None
    mileage=db.query(Mileage).filter(Mileage.vehicle_id==v.id,Mileage.approved_by!=None,Mileage.effective_from<end,or_(Mileage.effective_to==None,Mileage.effective_to>start)).order_by(Mileage.effective_from.desc()).all()
    balance=tank_balance(db,v,min(end,now()),get_college(db).rules)
    stock=balance['stock_l']; stock_quality=balance['stock_quality']
    latest_fill=max(fills,key=lambda f:(utc(f.occurred_at),utc(f.created_at)),default=None)
    refill_snapshot=None if not latest_fill else {
        'id':latest_fill.id,'occurred_at':latest_fill.occurred_at,'pre_stock_l':latest_fill.pre_stock_l,
        'delivered_l':latest_fill.litres,'post_stock_l':latest_fill.post_stock_l,
        'stock_quality':latest_fill.stock_quality,'evidence_id':latest_fill.evidence_id,
        'recommended_at_fill_l':recommendation(v.operating_target_l,latest_fill.pre_stock_l),
        'recommendation_basis':'Current operating target; historical target changes are not reconstructed.'}
    last_fix=db.query(GPSPoint).filter(GPSPoint.vehicle_id==v.id,GPSPoint.fix_at<end).order_by(GPSPoint.fix_at.desc()).first()
    open_cases=db.query(Case).filter(Case.vehicle_id==v.id,Case.state!='Closed',Case.created_at>=start,Case.created_at<end).count()
    pending=db.query(FuelEvent).filter(FuelEvent.vehicle_id==v.id,FuelEvent.occurred_at>=start,FuelEvent.occurred_at<end,FuelEvent.status.in_(['draft','submitted','authorised'])).count()
    priced=[f for f in fills if f.price_verified and f.price_per_l is not None]
    data={'vehicle_id':v.id,'bus_number':v.bus_number,'registration':v.registration,'status':v.status,'archived':v.archived,'demo':v.demo,'driver':dr.name if dr else None,'route':rt.name if rt else None,'route_id':rt.id if rt else None,'survey_mean_km':q(bike_mean([survey.b1_km,survey.b2_km,survey.b3_km],[survey.scope]*3)) if survey else None,'survey_scope':survey.scope if survey else None,'survey_readings':[str(survey.b1_km),str(survey.b2_km),str(survey.b3_km)] if survey else [],'planned_km':planned,'gps_km':actual,'manual_km':total('manual_km'),'deviation_km':None if actual is None or planned is None else q(actual-planned),'mileage_versions':[serial(m) for m in mileage],'standard_kmpl':mileage[0].kmpl if len(mileage)==1 else None,'legacy_range_km':q(delivered*mileage[0].kmpl) if len(mileage)==1 else None,'gps_average_km':q(actual/gps_days) if actual is not None and gps_days else None,'delivered_l':q(delivered),'expected_l':expected,'expected_complete':expected_complete,'disappearance_l':q(disappearance),'residual_l':q(residual) if eligible else None,'ungated_residual_l':q(residual),'residual_eligible':eligible,'uncertainty_l':q(uncertainty),'opening_l':opening.litres if opening else None,'closing_l':closing.litres if closing else None,'transfers_in_l':q(tin),'transfers_out_l':q(tout),'stock_l':q(stock),'stock_quality':stock_quality,'top_up_l':q(recommendation(v.operating_target_l,stock)),'operating_target_l':v.operating_target_l,'refill_count':len(fills),'fuel_cost':q(sum((f.litres*f.price_per_l for f in priced),ZERO),'0.01') if priced else None,'verified_price_count':len(priced),'open_cases':open_cases,'pending_approvals':pending,'coverage_pct':q(coverage,'0.1'),'gps_days':gps_days,'period_days':total_days,'last_fix':last_fix.fix_at if last_fix else None,'last_position':{'lat':last_fix.lat,'lon':last_fix.lon} if last_fix else None,'observed_kmpl':q(aggregate_mileage(actual,disappearance)) if eligible and actual is not None else None,'daily':[{**s.data,'service_date':s.service_date,'revision':s.revision,'id':s.id} for s in daily],'source_ids':{'fuel':[f.id for f in fills],'opening':opening.id if opening else None,'closing':closing.id if closing else None,'transfers':[t.id for t in transfers],'assignments':[historical.id] if historical else []},'evidence_complete':all(f.evidence_id for f in fills),'status':'final' if daily and len(daily)==total_days and all(s.data['status']=='final' for s in daily) else 'provisional'}
    gps_complete=len(daily)==total_days and all(s.data.get('gps_km') is not None and (D(s.data.get('planned_km') or 0)==0 or D(s.data.get('coverage_pct') or 0)>=90) and not any(s.data.get('flags',{}).get(k,0) for k in ('gaps','jumps','poor_accuracy')) for s in daily)
    plan_complete=len(daily)==total_days and all(s.data.get('planned_km') is not None for s in daily)
    fixed=mileage[0].kmpl if len(mileage)==1 and mileage[0].includes_idling else None
    data.update(shortage_metrics(actual,planned,disappearance,expected if expected_complete else None,fixed,
        gps_complete=gps_complete,plan_complete=plan_complete,fuel_eligible=eligible,uncertainty=uncertainty))
    data.update(balance)
    data['latest_refill']=refill_snapshot
    return clean(data)

def dashboard(db,user,start_date,end_date,vehicle_id=None,search='',status='',include_archived=False,include_sources=False):
    start,end=boundaries(start_date,end_date); qs=db.query(Vehicle)
    scope=vehicle_scope(db,user)
    if scope is not None:
        assignments=db.query(Assignment).filter(Assignment.driver_id==user.driver_id,Assignment.starts_at<=start,or_(Assignment.ends_at==None,Assignment.ends_at>=end)).all()
        allowed={a.vehicle_id for a in assignments};qs=qs.filter(Vehicle.id.in_(allowed))
    if vehicle_id:qs=qs.filter(Vehicle.id==vehicle_id)
    if not include_archived and not vehicle_id: qs=qs.filter(Vehicle.archived==False)
    if search: qs=qs.filter(or_(Vehicle.bus_number.ilike(f'%{search}%'),Vehicle.registration.ilike(f'%{search}%')))
    if status:qs=qs.filter(Vehicle.status==status)
    vehicles=sorted(qs.all(),key=lambda x:natural(x.bus_number))
    buses=[summarise_bus(db,v,start_date,end_date) for v in vehicles]
    if not include_sources:
        for b in buses:
            for d in b['daily']:
                for key in ('gps_source_ids','point_ids','plan_ids'):d.pop(key,None)
    metrics={}; contributors={}
    for key in ('gps_km','planned_km','delivered_l','expected_l','disappearance_l','residual_l','fuel_cost','refill_count','pending_approvals','open_cases','stock_l','top_up_l','km_shortage_km','diesel_shortage_l','route_shortage_km'):
        vals=[D(b[key]) for b in buses if b.get(key) is not None]
        metrics[key]=str(q(sum(vals,ZERO),'0.01' if key=='fuel_cost' else '0.001')) if vals else None
        contributors[key]=len(vals)
    cover=[D(b['coverage_pct']) for b in buses if b['coverage_pct'] is not None]
    metrics.update(total_buses=len(buses),active_buses=sum(v.status=='active' and not v.archived for v in vehicles),operating_buses=sum(D(b['gps_km'] or 0)>0 for b in buses),coverage_pct=str(q(sum(cover,ZERO)/len(cover),'0.1')) if cover else None)
    trends=[]; d=start_date
    while d<end_date:
        rows=[day for b in buses for day in b['daily'] if str(day['service_date'])==str(d)]
        val=lambda k: str(q(sum((D(r[k]) for r in rows if r.get(k) is not None),ZERO))) if any(r.get(k) is not None for r in rows) else None
        day_fills=db.query(FuelEvent).filter(FuelEvent.vehicle_id.in_([v.id for v in vehicles]),FuelEvent.status=='posted',FuelEvent.occurred_at>=day_start(d),FuelEvent.occurred_at<day_start(d+timedelta(days=1))).all() if vehicles else []
        trends.append({'date':str(d),'gps_km':val('gps_km'),'expected_l':val('expected_l'),'delivered_l':str(q(sum((f.litres for f in day_fills),ZERO)))})
        d+=timedelta(days=1)
    return clean({'period':{'start':start_date,'end':end_date,'start_utc':start,'end_utc':end,'timezone':'Asia/Kolkata','end_exclusive':True},'metrics':metrics,'contributors':contributors,'buses':buses,'trends':trends,'calculation_version':VERSION,'generated_at':now(),'demo':any(v.demo for v in vehicles),'briefing':f"{metrics['operating_buses']} operating buses; {metrics['delivered_l'] or '0'} L posted deliveries. {metrics['pending_approvals'] or '0'} fuel records await processing. {sum(not b['expected_complete'] for b in buses)} buses have incomplete consumption inputs. {metrics['open_cases'] or '0'} cases opened in this period remain unresolved."})

def month_checklist(db,user,start_date,end_date):
    data=dashboard(db,user,start_date,end_date,include_archived=True)
    start,end=boundaries(start_date,end_date)
    unapproved_transfers=db.query(Transfer).filter(Transfer.approved_by==None,Transfer.occurred_at>=start,Transfer.occurred_at<end).count()
    return {'boundary_stock_missing':sum(b['opening_l'] is None or b['closing_l'] is None for b in data['buses']),'pending_fuel':sum(b['pending_approvals'] for b in data['buses']),'unverified_invoices':sum(b['refill_count']-b['verified_price_count'] for b in data['buses']),'incomplete_gps':sum(b['status']!='final' for b in data['buses']),'open_cases':sum(b['open_cases'] for b in data['buses']),'pending_transfers':unapproved_transfers}
