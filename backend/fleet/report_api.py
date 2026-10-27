from fleet.api import *
from fleet.reports import csv_report,pdf_report

@router.post('/reports/queue')
def queue_report(start:date,end:date,kind:Literal['gps_weekly','fuel_weekly','monthly']='monthly',vehicle_id:str|None=None,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'CORRESPONDENT','TRANSPORT_VERIFIER'});boundaries(start,end)
    if vehicle_id:check_vehicle(db,user,vehicle_id)
    from fleet.tasks import report_job
    try:job=report_job.apply_async(args=[user.id,str(start),str(end),kind,vehicle_id],retry=False)
    except Exception:raise HTTPException(503,'Report queue unavailable. Start Redis and the Celery worker; use synchronous freeze for local operation.')
    db.add(Audit(actor_id=user.id,action='queue_report',entity_type='job',entity_id=job.id,vehicle_id=vehicle_id,reason='Explicit provisional asynchronous report request',after={'start':str(start),'end':str(end),'kind':kind},digest=digest({'job':job.id,'actor':user.id})));commit(db)
    return {'job_id':job.id,'status':'queued'}

@router.get('/jobs/{id}')
def job_status(id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    entry=db.query(Audit).filter_by(entity_type='job',entity_id=id,action='queue_report').first()
    if not entry or (entry.actor_id!=user.id and user.role not in {'SYSTEM_ADMIN','AUDITOR'}):raise HTTPException(404,'Job not found.')
    from fleet.tasks import celery
    try:
        result=celery.AsyncResult(id);state=result.state
        return {'job_id':id,'state':state,'report_id':result.result if state=='SUCCESS' else None,'error':'Report generation failed; review worker logs.' if state=='FAILURE' else None}
    except Exception:raise HTTPException(503,'Queue backend unavailable.')

def make_report_payload(db,user,start,end,vehicle_id=None):
    data=dashboard(db,user,start,end,vehicle_id=vehicle_id,include_archived=True,include_sources=True);data['college']=serial(get_college(db));a,b=boundaries(start,end);cases=[]
    for bus in data['buses']:
        vid=bus['vehicle_id'];cases.extend(serial(c)|{'bus_number':bus['bus_number']} for c in db.query(Case).filter(Case.vehicle_id==vid,Case.created_at>=a,Case.created_at<b).all())
        fills=db.query(FuelEvent).filter(FuelEvent.vehicle_id==vid,FuelEvent.status=='posted',FuelEvent.occurred_at>=a,FuelEvent.occurred_at<b).order_by(FuelEvent.occurred_at).all();intervals=[]
        for fill in fills:
            nxt=db.query(FuelEvent).filter(FuelEvent.vehicle_id==vid,FuelEvent.status=='posted',FuelEvent.occurred_at>fill.occurred_at).order_by(FuelEvent.occurred_at).first()
            profiles=[m for m in bus['mileage_versions'] if utc(datetime.fromisoformat(m['effective_from']))<=utc(fill.occurred_at) and (not m['effective_to'] or utc(datetime.fromisoformat(m['effective_to']))>utc(fill.occurred_at))]
            standard=D(profiles[0]['kmpl']) if len(profiles)==1 else None;legacy=q(fill.litres*standard) if standard else None;distance=None
            if nxt and utc(fill.occurred_at)==day_start(utc(fill.occurred_at).astimezone(IST).date()) and utc(nxt.occurred_at)==day_start(utc(nxt.occurred_at).astimezone(IST).date()):
                daily=db.query(DailySnapshot).filter(DailySnapshot.vehicle_id==vid,DailySnapshot.service_date>=utc(fill.occurred_at).astimezone(IST).date(),DailySnapshot.service_date<utc(nxt.occurred_at).astimezone(IST).date()).all()
                if daily and all(s.data['gps_km'] is not None for s in daily):distance=q(sum((D(s.data['gps_km']) for s in daily),ZERO))
            intervals.append(clean({'fuel_id':fill.id,'occurred_at':fill.occurred_at,'litres':fill.litres,'standard_range_km':legacy,'actual_interval_km':distance,'shortfall_km':q(legacy-distance) if legacy is not None and distance is not None else None,'equivalent_l':q(fill.litres-distance/standard) if standard and distance is not None else None,'quality':'legacy_range_comparison' if distance is not None else 'insufficient_exact_interval_data'}))
        bus['fill_intervals']=intervals
    data['cases']=cases;data['close_checklist']=month_checklist(db,user,start,end);data['close_status']='provisional' if any(data['close_checklist'].values()) else 'complete';return data

@router.get('/month-close/checklist')
def close_checklist(start:date,end:date,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,APPROVERS|{'ACCOUNTS','AUDITOR'});return month_checklist(db,user,start,end)

@router.post('/reports/freeze',status_code=201)
def freeze_report(start:date,end:date,kind:Literal['gps_weekly','fuel_weekly','monthly']='monthly',vehicle_id:str|None=None,provisional:bool=False,supersedes_id:str|None=None,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'CORRESPONDENT','TRANSPORT_VERIFIER'});boundaries(start,end)
    if vehicle_id:check_vehicle(db,user,vehicle_id)
    data=make_report_payload(db,user,start,end,vehicle_id)
    if data['close_status']=='provisional' and not provisional:raise HTTPException(422,{'message':'Resolve close checklist or explicitly freeze a provisional report.','checklist':data['close_checklist']})
    previous=ref(db,Report,supersedes_id) if supersedes_id else None
    if previous and (previous.kind!=kind or previous.start_date!=start or previous.end_date!=end or previous.vehicle_id!=vehicle_id):raise HTTPException(422,'Revision must retain scope and period.')
    data['snapshot_hash']=digest(data)
    r=Report(vehicle_id=vehicle_id,kind=kind,start_date=start,end_date=end,payload=data,sha256=data['snapshot_hash'],created_by=user.id,status='frozen_provisional' if provisional else 'frozen_final',revision=previous.revision+1 if previous else 1,supersedes_id=previous.id if previous else None)
    db.add(r);db.flush();audit(db,user,'freeze_report',r,'Explicit provisional close with unresolved checklist' if provisional else 'Close checklist complete');commit(db);return serial(r,user)

@router.post('/reports/{id}/verify')
def verify_report(id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'TRANSPORT_VERIFIER'});r=ref(db,Report,id);independent(user,r.created_by)
    if r.verified_by or r.signed_by:raise HTTPException(409,'Report has already passed verification.')
    if r.needs_revision:raise HTTPException(409,'Source records changed. Create a successor revision.')
    changed(db,r,payload.version);r.verified_by=user.id;r.verified_at=now();audit(db,user,'verify_report',r,payload.reason);db.add(Approval(entity_type='report',entity_id=id,actor_id=user.id,decision='verified',reason=payload.reason));commit(db);return serial(r,user)

@router.post('/reports/{id}/sign')
def sign_report(id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'CORRESPONDENT'});r=ref(db,Report,id);independent(user,r.created_by)
    if r.signed_by:raise HTTPException(409,'Already signed.')
    if r.needs_revision:raise HTTPException(409,'Source records changed. Freeze a revision before signing.')
    if not r.verified_by:raise HTTPException(422,'A separate Transport Verifier must verify this report before Correspondent signature.')
    independent(user,r.verified_by)
    changed(db,r,payload.version);r.signed_by=user.id;r.signed_at=now();audit(db,user,'sign_report',r,payload.reason);db.add(Approval(entity_type='report',entity_id=id,actor_id=user.id,decision='signed',reason=payload.reason));commit(db);return serial(r,user)

@router.get('/reports/{id}/export')
def export_report(id:str,format:Literal['csv','pdf']='pdf',user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'CORRESPONDENT','TRANSPORT_VERIFIER','AUDITOR','ACCOUNTS'});r=ref(db,Report,id)
    if r.vehicle_id:check_vehicle(db,user,r.vehicle_id)
    data=dict(r.payload);snapshot_hash=data.pop('snapshot_hash')
    if digest(data)!=snapshot_hash or snapshot_hash!=r.sha256:raise HTTPException(409,'Report integrity check failed.')
    data['snapshot_hash']=snapshot_hash;author=ref(db,User,r.created_by);signer=ref(db,User,r.signed_by) if r.signed_by else None;verifier=ref(db,User,r.verified_by) if r.verified_by else None
    signoffs={'prepared':author.name,'verified':f'{verifier.name} at {r.verified_at}' if verifier else 'Pending separate verification','approved':f'{signer.name} at {r.signed_at}' if signer else 'Pending correspondent signature'}
    content=csv_report(data,r.kind) if format=='csv' else pdf_report(data,r.kind,signoffs)
    audit(db,user,'export_report',r,f'{format} revision {r.revision}');commit(db)
    return Response(content,media_type='text/csv; charset=utf-8' if format=='csv' else 'application/pdf',headers={'Content-Disposition':f'attachment; filename="{r.kind}-{r.start_date}-v{r.revision}.{format}"','Cache-Control':'no-store'})
