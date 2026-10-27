import hmac,json,io
from pathlib import Path
from fastapi import File, Form, UploadFile
from fleet.api import *
from fleet.resources import validate_refs,affected

def validate_fuel(db,payload,v):
    """Apply the same physical and correction constraints at every workflow boundary."""
    if payload.litres>v.tank_capacity_l:raise HTTPException(422,'Delivery exceeds physical tank capacity.')
    if payload.stock_quality=='unknown' and (payload.pre_stock_l is not None or payload.post_stock_l is not None):raise HTTPException(422,'Identify supplied stock reading quality.')
    for n in (payload.pre_stock_l,payload.post_stock_l):
        if n is not None and n>v.tank_capacity_l:raise HTTPException(422,'Stock exceeds capacity.')
    if payload.pre_stock_l is not None and payload.pre_stock_l+payload.litres>v.tank_capacity_l:raise HTTPException(422,'Pre-stock plus delivery exceeds physical capacity.')
    if payload.pre_stock_l is not None and payload.pre_stock_l+payload.litres>v.safe_fill_l and len(payload.override_reason)<5:raise HTTPException(422,'Above safe fill limit; document an override for independent authorisation.')
    if payload.correction_of:
        old=ref(db,FuelEvent,payload.correction_of)
        if old.vehicle_id!=v.id or old.status!='reversed':raise HTTPException(422,'Correction must link a reversed record for this bus.')

@router.post('/fuel',status_code=201)
def create_fuel(payload:FuelInput,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'FUELLER'});v=vehicle(db,payload.vehicle_id)
    if v.archived:raise HTTPException(422,'Archived bus cannot receive new fills.')
    data=payload.model_dump();data['supplier']=data['supplier'].strip().casefold();data['invoice']=data['invoice'].strip().upper();data['pump_transaction']=data['pump_transaction'] or None
    duplicate=db.query(FuelEvent).filter_by(idempotency_key=payload.idempotency_key).first()
    if duplicate:
        if duplicate.created_by!=user.id or any(not equivalent(getattr(duplicate,k),value) for k,value in data.items()):raise HTTPException(409,'Idempotency key was already used for different content.')
        return serial(duplicate,user)
    validate_refs(db,user,'fuel',data)
    validate_fuel(db,payload,v)
    obj=FuelEvent(**data,created_by=user.id);db.add(obj)
    try:db.flush()
    except IntegrityError:db.rollback();raise HTTPException(409,'Duplicate invoice, pump transaction or request. No fuel was posted.')
    audit(db,user,'draft_fuel',obj,'Draft recorded; no ledger impact');commit(db);return serial(obj,user)

@router.post('/fuel/{id}/{action}')
def fuel_action(id:str,action:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    obj=ref(db,FuelEvent,id);check_vehicle(db,user,obj.vehicle_id);before=serial(obj,user)
    if action=='acknowledge':
        require(user,{'DRIVER'});a=assignment_at(db,obj.vehicle_id,obj.occurred_at)
        if not a or a.driver_id!=user.driver_id:raise HTTPException(403,'Only the driver assigned at fill time may acknowledge.')
        changed(db,obj,payload.version);obj.acknowledged_by=user.id
    elif action=='authorise':
        require(user,APPROVERS);independent(user,obj.created_by)
        if obj.status!='draft':raise HTTPException(409,'Only a draft can be authorised.')
        changed(db,obj,payload.version);obj.authorised_by=user.id;obj.status='authorised'
    elif action=='submit':
        require(user,ADMIN|{'FUELLER'})
        if obj.created_by!=user.id and user.role not in ADMIN:raise HTTPException(403,'Only the creator or an administrator may submit this draft.')
        if obj.status not in ('draft','authorised'):raise HTTPException(409,'Already submitted or posted.')
        if obj.override_reason and not obj.authorised_by:raise HTTPException(422,'Override requires independent authorisation.')
        if not obj.evidence_id and not obj.override_reason:raise HTTPException(422,'Attach evidence or document an emergency exception.')
        changed(db,obj,payload.version);obj.status='submitted'
    elif action=='verify':
        require(user,APPROVERS);independent(user,obj.created_by)
        if obj.status!='submitted':raise HTTPException(409,'Only submitted records can be posted.')
        if not obj.evidence_id and not obj.authorised_by:raise HTTPException(422,'Missing evidence needs independent emergency authorisation.')
        validate_fuel(db,obj,vehicle(db,obj.vehicle_id))
        changed(db,obj,payload.version);obj.verified_by=user.id;obj.status='posted';db.flush();affected(db,obj)
        if not obj.evidence_id:rule_case(db,obj.vehicle_id,'missing_evidence','Emergency fill posted without evidence; follow-up required.',{'fuel_id':obj.id},f'evidence:{obj.id}')
        if obj.pre_stock_l is not None and obj.post_stock_l is not None and obj.stock_quality=='measured':
            difference=obj.litres-(obj.post_stock_l-obj.pre_stock_l)
            if abs(difference)>max(D(5),obj.litres*D('0.05')):rule_case(db,obj.vehicle_id,'sensor_delivery_difference','Declared stable stock rise differs from delivery. Check calibration and conditions.',{'fuel_id':obj.id,'difference_l':difference},f'rise:{obj.id}')
    elif action=='match-invoice':
        require(user,{'ACCOUNTS'});independent(user,obj.created_by)
        if obj.status!='posted' or obj.price_per_l is None or not obj.evidence_id:raise HTTPException(422,'Posted fill, price and invoice evidence required.')
        changed(db,obj,payload.version);obj.price_verified=True;affected(db,obj)
    elif action=='reverse':
        require(user,{'CORRESPONDENT'});independent(user,obj.created_by)
        if obj.status!='posted':raise HTTPException(409,'Only posted fuel can be reversed.')
        changed(db,obj,payload.version);obj.status='reversed';obj.reversed_by=user.id;obj.reversal_reason=payload.reason;db.flush();affected(db,obj)
    else:raise HTTPException(404,'Unknown fuel action.')
    db.add(Approval(entity_type='fuel',entity_id=obj.id,actor_id=user.id,decision=action,reason=payload.reason));audit(db,user,'fuel_'+action,obj,payload.reason,before);commit(db);return serial(obj,user)

@router.put('/fuel/{id}')
def edit_fuel(id:str,payload:FuelInput,version:int,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'FUELLER'});obj=ref(db,FuelEvent,id)
    if obj.status!='draft' or (obj.created_by!=user.id and user.role not in ADMIN):raise HTTPException(409,'Only an owned draft may be corrected. Reverse posted events and link a replacement.')
    if payload.vehicle_id!=obj.vehicle_id or payload.idempotency_key!=obj.idempotency_key:raise HTTPException(422,'Vehicle and idempotency key are immutable.')
    data=payload.model_dump();validate_refs(db,user,'fuel',data);v=vehicle(db,obj.vehicle_id)
    validate_fuel(db,payload,v)
    before=serial(obj,user);changed(db,obj,version);data['supplier']=data['supplier'].casefold();data['invoice']=data['invoice'].upper();data['pump_transaction']=data['pump_transaction'] or None
    for k,v in data.items():setattr(obj,k,v)
    audit(db,user,'correct_fuel_draft',obj,'Draft correction before submission',before);commit(db);return serial(obj,user)

@router.get('/planner')
def planner(days:int=Query(7,ge=1,le=31),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    today=now().astimezone(IST).date();end=today+timedelta(days=days);scope=vehicle_scope(db,user);qs=db.query(Vehicle).filter_by(archived=False)
    if scope is not None:qs=qs.filter(Vehicle.id.in_(scope))
    items=[];suggestions=[]
    for v in qs.all():
        plans=db.query(PlannedTrip).filter(PlannedTrip.vehicle_id==v.id,PlannedTrip.service_date>=today,PlannedTrip.service_date<end,PlannedTrip.approved_by!=None).all()
        planned=sum((p.trip_km*p.trips for p in plans),ZERO) if plans else None;expected=ZERO if plans else None
        for p in plans:
            profile=db.query(Mileage).filter(Mileage.vehicle_id==v.id,Mileage.approved_by!=None,Mileage.effective_from<=day_start(p.service_date),or_(Mileage.effective_to==None,Mileage.effective_to>day_start(p.service_date)),or_(Mileage.route_id==None,Mileage.route_id==p.route_id)).order_by(Mileage.effective_from.desc()).first()
            if not profile:expected=None;break
            expected+=p.trip_km*p.trips/profile.kmpl
        s=summarise_bus(db,v,today,today+timedelta(days=1))
        items.append(clean({'vehicle_id':v.id,'bus_number':v.bus_number,'planned_km':q(planned),'expected_l':q(expected),'stock_l':s['stock_l'],'stock_quality':s['stock_quality'],'operating_target_l':v.operating_target_l,'top_up_l':s['top_up_l'],'note':'Missing schedule/mileage' if expected is None else 'Stock unknown' if s['stock_l'] is None else 'Estimated' if s['stock_quality']=='estimated' else 'Measured'}))
        weeks=[]
        for n in range(1,4):
            w=summarise_bus(db,v,today-timedelta(days=n*7),today-timedelta(days=(n-1)*7))
            if w['observed_kmpl'] is not None and len(w['mileage_versions'])==1:weeks.append(w)
        if len(weeks)==3 and len({w['mileage_versions'][0]['id'] for w in weeks})==1 and all(D(w['observed_kmpl'])<D(w['mileage_versions'][0]['kmpl'])*D('0.85') for w in weeks):suggestions.append({'vehicle_id':v.id,'explanation':'Three reconciled weeks were below 85% of the same mileage standard. Review comparable conditions with maintenance. No diagnosis or driver blame is implied.'})
    return {'start':str(today),'end_exclusive':str(end),'items':items,'maintenance_suggestions':suggestions}

@router.post('/evidence',status_code=201)
async def upload_evidence(vehicle_id:str=Form(...),file:UploadFile=File(...),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'FUELLER','TRANSPORT_VERIFIER','ACCOUNTS'});check_vehicle(db,user,vehicle_id);vehicle(db,vehicle_id)
    maximum=(3 if settings.SERVERLESS else 10)*1024*1024
    content=await file.read(maximum+1)
    if len(content)>maximum:raise HTTPException(413,f'Maximum evidence size {maximum//(1024*1024)} MB.')
    if settings.SERVERLESS and not settings.S3_BUCKET and settings.EVIDENCE_STORAGE!='database':raise HTTPException(503,'Configure durable private evidence storage before uploading.')
    from PIL import Image
    if content.startswith(b'%PDF-'):
        from pypdf import PdfReader
        try:
            reader=PdfReader(io.BytesIO(content))
            if reader.is_encrypted or len(reader.pages)>100 or any(k in reader.trailer['/Root'] for k in ('/OpenAction','/AA')):raise ValueError()
        except Exception:raise HTTPException(422,'PDF must be passive, unencrypted and readable.')
        mime='application/pdf';ext='.pdf'
    else:
        try:
            im=Image.open(io.BytesIO(content));im.verify()
            if im.format not in ('JPEG','PNG') or im.width*im.height>40000000:raise ValueError()
            mime='image/jpeg' if im.format=='JPEG' else 'image/png';ext='.jpg' if im.format=='JPEG' else '.png'
        except Exception:raise HTTPException(422,'Upload a valid PNG, JPEG or passive PDF.')
    key=uid()+ext
    if settings.S3_BUCKET:
        from fleet.storage import s3
        s3().put_object(Bucket=settings.S3_BUCKET,Key=key,Body=content,ContentType=mime,ServerSideEncryption='AES256')
    elif settings.EVIDENCE_STORAGE!='database':
        root=Path(settings.PRIVATE_STORAGE_DIR);root.mkdir(parents=True,exist_ok=True);(root/key).write_bytes(content)
    ev=Evidence(vehicle_id=vehicle_id,uploaded_by=user.id,filename=Path((file.filename or 'evidence').replace('\\','/')).name[:200],mime=mime,size=len(content),sha256=hashlib.sha256(content).hexdigest(),storage_key=key)
    db.add(ev);db.flush()
    if settings.EVIDENCE_STORAGE=='database' and not settings.S3_BUCKET:db.add(EvidenceContent(evidence_id=ev.id,content=content))
    audit(db,user,'upload_evidence',ev,'Private evidence uploaded');commit(db);return serial(ev,user)

@router.get('/evidence/{id}/download')
def download_evidence(id:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    ev=ref(db,Evidence,id);check_vehicle(db,user,ev.vehicle_id)
    if user.role=='DRIVER':
        fills=db.query(FuelEvent).filter_by(evidence_id=id).all()
        if not any((a:=assignment_at(db,f.vehicle_id,f.occurred_at)) and a.driver_id==user.driver_id for f in fills):raise HTTPException(403,'Drivers can download evidence only for deliveries during their assignment.')
    if settings.S3_BUCKET:
        from fleet.storage import s3
        content=s3().get_object(Bucket=settings.S3_BUCKET,Key=ev.storage_key)['Body'].read()
    elif (stored:=db.get(EvidenceContent,ev.id)) is not None:
        content=stored.content
    else:
        path=Path(settings.PRIVATE_STORAGE_DIR)/ev.storage_key
        if not path.exists():raise HTTPException(404,'Evidence unavailable. Restore it from backup.')
        content=path.read_bytes()
    if hashlib.sha256(content).hexdigest()!=ev.sha256:raise HTTPException(409,'Evidence integrity check failed.')
    audit(db,user,'download_evidence',ev,'Authorised evidence access');commit(db)
    return Response(content,media_type=ev.mime,headers={'Content-Disposition':f'attachment; filename="evidence-{ev.id}{Path(ev.storage_key).suffix}"','Cache-Control':'no-store'})

@router.post('/gps/ingest')
def ingest(points:list[GPSInput],user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'SYSTEM_ADMIN','TRANSPORT_VERIFIER'});return ingest_points(db,points,user)

def ingest_points(db,points,user=None):
    if not 1<=len(points)<=1000:raise HTTPException(422,'Send 1–1000 events per batch.')
    counts={'accepted':0,'duplicate':0,'unmapped':0};days={}
    for p in points:
        if p.fix_at>now()+timedelta(minutes=10):raise HTTPException(422,'GPS fix too far in future.')
        if db.query(GPSPoint).filter_by(provider=p.provider,device_id=p.device_id,event_id=p.event_id).first():counts['duplicate']+=1;continue
        maps=db.query(DeviceMapping).filter(DeviceMapping.provider==p.provider,DeviceMapping.device_id==p.device_id,DeviceMapping.starts_at<=p.fix_at,or_(DeviceMapping.ends_at==None,DeviceMapping.ends_at>p.fix_at)).all()
        if len(maps)!=1:counts['unmapped']+=1;continue
        m=maps[0];g=GPSPoint(**p.model_dump(),vehicle_id=m.vehicle_id,speed_kph=speed_kph(p.speed,p.source_unit),received_at=now())
        try:
            with db.begin_nested():db.add(g);db.flush()
        except IntegrityError:counts['duplicate']+=1;continue
        counts['accepted']+=1;m.last_sync=now();m.health='connected';d=p.fix_at.astimezone(IST).date();days.setdefault(m.vehicle_id,set()).update((d-timedelta(days=1),d,d+timedelta(days=1)));invalidate_reports(db,m.vehicle_id,p.fix_at)
    for vid,dates in days.items():
        for d in sorted(dates):rebuild(db,vid,d,d+timedelta(days=1))
    commit(db);return counts

@router.post('/gps/webhook')
async def webhook(request:Request,db:DBSession=Depends(get_db)):
    if not settings.GPS_WEBHOOK_SECRET:raise HTTPException(503,'Webhook not configured.')
    raw=await request.body();expected=hmac.new(settings.GPS_WEBHOOK_SECRET.encode(),raw,hashlib.sha256).hexdigest()
    if not hmac.compare_digest(request.headers.get('x-gps-signature',''),expected):raise HTTPException(401,'Invalid signature.')
    try:points=[GPSInput.model_validate(p) for p in json.loads(raw)]
    except (ValueError,TypeError):raise HTTPException(422,'Invalid GPS payload.')
    return ingest_points(db,points)

@router.get('/gps/health')
def gps_health(user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    return {'provider_configured':bool(settings.GPS_PROVIDER_TOKEN),'devices':[serial(m)|{'connection_health':'stale' if not m.last_sync or now()-utc(m.last_sync)>timedelta(seconds=m.cadence_seconds*4) else m.health} for m in scoped_records(db,user,DeviceMapping).all()],'demo_adapter_active':False}

@router.post('/gps/backfill')
def backfill(start:date,end:date,user:User=Depends(current_user)):
    require(user,{'SYSTEM_ADMIN','TRANSPORT_VERIFIER'});boundaries(start,end)
    if not settings.GPS_PROVIDER_TOKEN:raise HTTPException(503,'Configure the authorised provider first.')
    from fleet.tasks import provider_backfill
    result=provider_backfill.delay(str(start),str(end));return {'job_id':result.id,'status':'queued'}

@router.post('/calculations/rebuild')
def recalculate(start:date,end:date,vehicle_id:str|None=None,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'TRANSPORT_VERIFIER'});boundaries(start,end)
    vs=[vehicle(db,vehicle_id)] if vehicle_id else db.query(Vehicle).all()
    for v in vs:rebuild(db,v.id,start,end)
    commit(db);return {'updated_buses':len(vs),'calculation_version':VERSION}

@router.post('/cases/{id}/decision')
def case_decision(id:str,payload:CaseDecision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,APPROVERS);obj=ref(db,Case,id);before=serial(obj,user)
    transitions={'New':{'Acknowledged','Investigating'},'Acknowledged':{'Investigating'},'Investigating':{'Explained','Confirmed discrepancy'},'Explained':{'Closed','Investigating'},'Confirmed discrepancy':{'Closed','Investigating'},'Closed':{'Investigating'}}
    if payload.state not in transitions.get(obj.state,set()):raise HTTPException(422,'Follow case acknowledgement, investigation, decision and closure.')
    if payload.approved_amount is not None:
        require(user,{'CORRESPONDENT'})
        if not obj.reviewer_id:raise HTTPException(422,'Independent investigation must precede financial approval.')
        independent(user,obj.reviewer_id)
    changed(db,obj,payload.version);obj.state=payload.state;obj.reviewer_id=obj.reviewer_id or user.id;obj.decision=payload.reason
    if payload.approved_amount is not None:obj.financial_approved_by=user.id;obj.approved_amount=payload.approved_amount
    audit(db,user,'case_decision',obj,payload.reason,before);db.add(Approval(entity_type='case',entity_id=id,actor_id=user.id,decision=payload.state,reason=payload.reason));commit(db);return serial(obj,user)

@router.post('/cases/{id}/explanation')
def case_explanation(id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    obj=ref(db,Case,id);check_vehicle(db,user,obj.vehicle_id);require(user,{'DRIVER'}|APPROVERS)
    changed(db,obj,payload.version)
    db.add(Approval(entity_type='case_explanation',entity_id=id,actor_id=user.id,decision='explanation',reason=payload.reason));audit(db,user,'case_explanation',obj,payload.reason);commit(db);return {'ok':True}

@router.post('/cases/{id}/match-accounts')
def case_accounts(id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'ACCOUNTS'});obj=ref(db,Case,id)
    if not obj.financial_approved_by:raise HTTPException(422,'No financial decision to match.')
    independent(user,obj.financial_approved_by);changed(db,obj,payload.version);obj.invoice_matched_by=user.id;audit(db,user,'match_case_accounts',obj,payload.reason);commit(db);return serial(obj,user)
