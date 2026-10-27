import csv,io,json
from fastapi import File, UploadFile
from fleet.api import *

def validate_refs(db,user,kind,data,obj=None):
    for key,model in {'vehicle_id':Vehicle,'driver_id':Driver,'route_id':Route,'from_vehicle_id':Vehicle,'to_vehicle_id':Vehicle,'calibration_id':Calibration}.items():
        if data.get(key):
            r=ref(db,model,data[key])
            if r.archived:raise HTTPException(422,f'{key} is archived.')
            if model is Vehicle:check_vehicle(db,user,r.id)
    if data.get('evidence_id'):
        ev=ref(db,Evidence,data['evidence_id']);check_vehicle(db,user,ev.vehicle_id)
        if data.get('vehicle_id') and ev.vehicle_id!=data['vehicle_id']:raise HTTPException(422,'Evidence belongs to another bus.')
    if kind in ('assignments','devices','mileage'):
        db.query(Vehicle).filter_by(id=data['vehicle_id']).with_for_update().first()
        start=data.get('starts_at') or data.get('effective_from');end=data.get('ends_at') or data.get('effective_to')
        model=MODELS[kind];start_col=model.effective_from if kind=='mileage' else model.starts_at;end_col=model.effective_to if kind=='mileage' else model.ends_at
        qs=db.query(model).filter(model.archived==False,or_(end_col==None,end_col>start))
        if end:qs=qs.filter(start_col<end)
        if obj:qs=qs.filter(model.id!=obj.id)
        if kind=='devices':qs=qs.filter(or_(model.vehicle_id==data['vehicle_id'],(model.provider==data['provider']) & (model.device_id==data['device_id'])))
        else:qs=qs.filter(model.vehicle_id==data['vehicle_id'])
        if kind=='mileage':qs=qs.filter(model.route_id==data.get('route_id'),model.approved_by!=None)
        if kind!='mileage' and qs.first():raise HTTPException(409,'Effective dates overlap. Close the previous history interval first.')
    if kind=='surveys':
        route=ref(db,Route,data['route_id'])
        if route.scope!=data['scope']:raise HTTPException(422,'Survey and route scope must match.')
        if data['readings']:
            if len(data['readings'])!=3:raise HTTPException(422,'Provide start/end readings for three runs.')
            for i,r in enumerate(data['readings']):
                try:delta=D(r['end_km'])-D(r['start_km'])
                except Exception:raise HTTPException(422,'Survey readings require numeric start_km and end_km.')
                if not delta.is_finite():raise HTTPException(422,'Survey readings must be finite.')
                if abs(delta-data[f'b{i+1}_km'])>D('0.05'):raise HTTPException(422,'Survey distance must match end minus start.')
    if kind=='plans' and data.get('route_id'):
        if ref(db,Route,data['route_id']).scope!=data['scope']:raise HTTPException(422,'Trip and route scopes must match.')
    if kind=='tank-readings':
        v=vehicle(db,data['vehicle_id'])
        if data['litres']>v.tank_capacity_l:raise HTTPException(422,'Reading exceeds physical capacity.')
        if data['quality']=='measured' and not data['stable']:raise HTTPException(422,'Measured stock requires a stable window.')
        if data['source']=='sensor':
            cal=ref(db,Calibration,data.get('calibration_id'))
            if cal.vehicle_id!=v.id or not cal.approved_by or utc(cal.effective_from)>utc(data['occurred_at']):raise HTTPException(422,'An approved tank-specific calibration effective at this time is required.')
        if data['source']=='manual_estimate' and data['quality']!='estimated':raise HTTPException(422,'Manual estimate cannot be labelled measured.')

def affected(db,obj):
    vehicle_id=getattr(obj,'vehicle_id',None)
    if isinstance(obj,Transfer):
        for id in (obj.from_vehicle_id,obj.to_vehicle_id):invalidate_reports(db,id,obj.occurred_at)
        return
    if not vehicle_id:return
    stamp=next((getattr(obj,x,None) for x in ('occurred_at','starts_at','effective_from') if getattr(obj,x,None)),None)
    if isinstance(obj,PlannedTrip):stamp=day_start(obj.service_date)
    if stamp:
        d=utc(stamp).astimezone(IST).date()
        latest=db.query(DailySnapshot.service_date).filter_by(vehicle_id=vehicle_id).order_by(DailySnapshot.service_date.desc()).first()
        end=max(now().astimezone(IST).date()+timedelta(days=1),d+timedelta(days=1),latest[0]+timedelta(days=1) if latest else d+timedelta(days=1))
        # Closing a previously open interval changes later summaries too. Never silently
        # leave a frozen report or the second year of a historical backfill unchanged.
        invalidate_reports(db,vehicle_id,stamp,day_start(end))
        if isinstance(obj,PlannedTrip):end=d+timedelta(days=1)
        while d<end:
            chunk_end=min(end,d+timedelta(days=366))
            rebuild(db,vehicle_id,d,chunk_end)
            d=chunk_end


def create_resource(db,user,kind,data):
    validate_refs(db,user,kind,data)
    if kind in ('routes','surveys','mileage','plans','tank-readings','calibrations','transfers','manual-trips'):data['created_by']=user.id
    if kind=='manual-trips':
        data['source']='manual';a=assignment_at(db,data['vehicle_id'],data['starts_at']);data['driver_id']=a.driver_id if a else None
    obj=MODELS[kind](**data);db.add(obj)
    try:db.flush()
    except IntegrityError:db.rollback();raise HTTPException(409,'Duplicate or conflicting resource. No import rows were saved.')
    if kind in ('assignments','devices'):affected(db,obj)
    audit(db,user,'create',obj,'Admin entry; independent approval required for operational facts');return obj

@router.get('/resources/{kind}/export')
def export_resource(kind:str,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|{'CORRESPONDENT','TRANSPORT_VERIFIER','AUDITOR','ACCOUNTS'})
    if kind not in MODELS:raise HTTPException(404,'Unknown resource.')
    rows=[serial(r,user) for r in scoped_records(db,user,MODELS[kind]).all()]
    for row in rows:row.pop('payload',None)
    fields=list(rows[0]) if rows else ['id'];out=io.StringIO(newline='');w=csv.DictWriter(out,fieldnames=fields,extrasaction='ignore');w.writeheader()
    from fleet.reports import safe_cell
    for row in rows:w.writerow({k:safe_cell(json.dumps(v,ensure_ascii=False) if isinstance(v,(dict,list)) else v) for k,v in row.items()})
    return Response(('\ufeff'+out.getvalue()).encode(),media_type='text/csv',headers={'Content-Disposition':f'attachment; filename="{kind}.csv"'})

@router.post('/resources/{kind}/import')
async def import_csv(kind:str,file:UploadFile=File(...),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN)
    if kind not in SCHEMAS:raise HTTPException(422,'Use the dedicated workflow for this record type.')
    content=await file.read(2*1024*1024+1)
    if len(content)>2*1024*1024:raise HTTPException(413,'CSV maximum is 2 MB.')
    try:rows=list(csv.DictReader(io.StringIO(content.decode('utf-8-sig'))))
    except Exception:raise HTTPException(422,'Use UTF-8 CSV with a header row.')
    if not 1<=len(rows)<=1000:raise HTTPException(422,'Import 1–1000 rows per batch.')
    ids=[]
    for n,row in enumerate(rows,2):
        data={k:v for k,v in row.items() if v!=''}
        for key in ('stops','geometry','readings','curve'):
            if key in data:
                try:data[key]=json.loads(data[key])
                except ValueError:raise HTTPException(422,f'Row {n}: invalid JSON in {key}.')
        try:p=SCHEMAS[kind].model_validate(data)
        except ValidationError as e:raise HTTPException(422,{'row':n,'errors':json.loads(e.json())})
        obj=create_resource(db,user,kind,p.model_dump());ids.append(obj.id)
    commit(db);return {'created':len(ids),'ids':ids,'note':'Operational records remain drafts until independently approved.'}

@router.get('/resources/{kind}')
def list_resource(kind:str,page:int=Query(1,ge=1),page_size:int=Query(25,ge=1,le=200),search:str='',archived:bool=False,vehicle_id:str|None=None,start:date|None=None,end:date|None=None,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    if kind not in MODELS:raise HTTPException(404,'Unknown resource.')
    if kind=='audit':require(user,ADMIN|APPROVERS|{'AUDITOR'})
    model=MODELS[kind];qs=scoped_records(db,user,model).filter(model.archived==archived)
    if (start is None)!=(end is None):raise HTTPException(422,'Supply both start and exclusive end dates.')
    if start and end:
        a,b=boundaries(start,end)
        if hasattr(model,'occurred_at'):qs=qs.filter(model.occurred_at>=a,model.occurred_at<b)
        elif model is Case:qs=qs.filter(model.created_at>=a,model.created_at<b)
        elif hasattr(model,'service_date'):qs=qs.filter(model.service_date>=start,model.service_date<end)
    if vehicle_id and hasattr(model,'vehicle_id'):check_vehicle(db,user,vehicle_id);qs=qs.filter(model.vehicle_id==vehicle_id)
    if search:
        columns=[getattr(model,k) for k in ('bus_number','registration','name','employee_id','code','invoice','rule','device_id') if hasattr(model,k)]
        if columns:qs=qs.filter(or_(*(c.ilike(f'%{search}%') for c in columns)))
    total=qs.count()
    if model is Vehicle:rows=sorted(qs.all(),key=lambda v:natural(v.bus_number))[(page-1)*page_size:page*page_size]
    else:rows=qs.order_by(model.created_at.desc()).offset((page-1)*page_size).limit(page_size).all()
    return {'items':[serial(r,user) for r in rows],'total':total,'page':page,'page_size':page_size}

@router.post('/resources/{kind}',status_code=201)
def add_resource(kind:str,payload:dict,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|({'FUELLER','TRANSPORT_VERIFIER'} if kind=='tank-readings' else set()))
    if kind not in SCHEMAS:raise HTTPException(422,'Use the dedicated workflow for this resource.')
    try:data=SCHEMAS[kind].model_validate(payload).model_dump()
    except ValidationError as e:raise HTTPException(422,json.loads(e.json()))
    obj=create_resource(db,user,kind,data);commit(db);return serial(obj,user)

@router.put('/resources/{kind}/{id}')
def edit_resource(kind:str,id:str,payload:dict,version:int,reason:str=Query(min_length=3),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN)
    if kind not in SCHEMAS:raise HTTPException(422,'Immutable record; use linked corrections.')
    obj=ref(db,MODELS[kind],id)
    if getattr(obj,'approved_by',None) or getattr(obj,'verified_by',None) or getattr(obj,'reviewer_id',None):raise HTTPException(409,'Approved records are immutable. Create a successor version or correction.')
    if kind=='manual-trips':raise HTTPException(409,'Manual history is immutable; add a reviewed correction.')
    if kind=='routes' and db.query(Assignment).filter_by(route_id=obj.id).first():raise HTTPException(409,'Referenced routes are immutable; create a new route version code.')
    try:data=SCHEMAS[kind].model_validate(payload).model_dump()
    except ValidationError as e:raise HTTPException(422,json.loads(e.json()))
    if kind in ('assignments','devices') and any(not equivalent(getattr(obj,k),v) for k,v in data.items() if k not in ('ends_at','reason')):raise HTTPException(409,'Preserve history: only close the end timestamp and create a new assignment.')
    validate_refs(db,user,kind,data,obj);before=serial(obj,user);changed(db,obj,version)
    for k,v in data.items():setattr(obj,k,v)
    if kind in ('assignments','devices'):db.flush();affected(db,obj)
    audit(db,user,'edit_draft',obj,reason,before);commit(db);return serial(obj,user)

@router.post('/resources/{kind}/{id}/archive')
def archive_resource(kind:str,id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN)
    if kind not in {'vehicles','drivers','routes'}:raise HTTPException(422,'Operational records stay in history; use corrections or close their effective interval.')
    obj=ref(db,MODELS[kind],id);before=serial(obj,user);changed(db,obj,payload.version);obj.archived=not obj.archived;audit(db,user,'restore' if not obj.archived else 'archive',obj,payload.reason,before);commit(db);return serial(obj,user)

@router.post('/resources/{kind}/{id}/approve')
def approve_resource(kind:str,id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,APPROVERS)
    if kind not in {'routes','surveys','mileage','plans','tank-readings','calibrations','transfers','manual-trips'}:raise HTTPException(422,'Resource has no approval workflow.')
    obj=ref(db,MODELS[kind],id);independent(user,obj.created_by);attr='verified_by' if kind=='tank-readings' else 'reviewer_id' if kind=='manual-trips' else 'approved_by'
    if getattr(obj,attr):raise HTTPException(409,'Already approved.')
    if isinstance(obj,Mileage):
        qs=db.query(Mileage).filter(Mileage.id!=obj.id,Mileage.vehicle_id==obj.vehicle_id,Mileage.route_id==obj.route_id,Mileage.approved_by!=None,or_(Mileage.effective_to==None,Mileage.effective_to>obj.effective_from))
        if obj.effective_to:qs=qs.filter(Mileage.effective_from<obj.effective_to)
        db.query(Vehicle).filter_by(id=obj.vehicle_id).with_for_update().first()
        if qs.first():raise HTTPException(409,'Mileage intervals overlap. Close the previous version first.')
        if not obj.evidence_id:raise HTTPException(422,'Supporting evidence is required.')
    if isinstance(obj,Survey) and not obj.evidence_id:raise HTTPException(422,'Approved survey needs evidence.')
    if isinstance(obj,TankReading) and obj.quality=='measured' and not obj.evidence_id:raise HTTPException(422,'Measured stock verification needs evidence.')
    before=serial(obj,user);changed(db,obj,payload.version);setattr(obj,attr,user.id);db.flush();affected(db,obj)
    if isinstance(obj,Mileage):
        previous=db.query(Mileage).filter(Mileage.vehicle_id==obj.vehicle_id,Mileage.route_id==obj.route_id,Mileage.id!=obj.id,Mileage.approved_by!=None,Mileage.effective_from<obj.effective_from).order_by(Mileage.effective_from.desc()).first()
        rules=get_college(db).rules
        if previous and abs(obj.kmpl-previous.kmpl)/previous.kmpl*100>D(rules.get('standard_change_pct',20)):
            rule_case(db,obj.vehicle_id,'standard_change','Approved standard changed beyond the configured percentage. Review comparability and the supporting evidence; this is not an accusation.',{'previous_version_id':previous.id,'new_version_id':obj.id,'previous_kmpl':str(previous.kmpl),'new_kmpl':str(obj.kmpl)},f'standard:{obj.id}',str(rules.get('rule_version','1.0')))
    db.add(Approval(entity_type=kind,entity_id=id,actor_id=user.id,decision='approved',reason=payload.reason));audit(db,user,'approve',obj,payload.reason,before);commit(db);return serial(obj,user)

@router.post('/mileage/{id}/end-version')
def end_mileage(id:str,payload:Decision,effective_to:datetime,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,APPROVERS);obj=ref(db,Mileage,id);independent(user,obj.created_by)
    if effective_to.tzinfo is None or effective_to<=utc(obj.effective_from):raise HTTPException(422,'End must be timezone-aware and after start.')
    if obj.effective_to is not None:raise HTTPException(409,'Version already closed.')
    before=serial(obj);changed(db,obj,payload.version);obj.effective_to=effective_to;affected(db,obj);audit(db,user,'close_mileage_version',obj,payload.reason,before);commit(db);return serial(obj)
