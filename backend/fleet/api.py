import hashlib
from datetime import timedelta
import pyotp
from fastapi import APIRouter, Depends, Form, HTTPException, Query, Request, Response
from pydantic import ValidationError
from sqlalchemy import or_, update
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session as DBSession
from fleet.config import settings
from fleet.db import get_db
from fleet.models import *
from fleet.schemas import *
from fleet.auth import current_user, require, independent, check_vehicle, check_period, vehicle_scope, ADMIN, APPROVERS, password_hash, verify_password, user_view, create_session, encrypt_secret, decrypt_secret
from fleet.services import *

router=APIRouter(prefix='/api/v2')

@router.get('/public/calculation-examples')
def examples():
    disappeared,residual=stock_reconcile(40,200,60,expected_use([(720,4)]))
    monthly,monthly_residual=stock_reconcile(120,2000,180,expected_use([(7600,4)]))
    standard,shortfall,equivalent=range_variance(720,200,4)
    return clean({'illustrative':True,'persisted':False,'calculation_version':VERSION,'bike':{'runs':[79,80,81],'mean_km':bike_mean([79,80,81],['trip']*3),'trips_per_day':2,'daily_km':160},'gps_weekly':{'days':[160,162,158,160,160],'total_km':800,'complete_days':5,'average_km':160,'baseline_km':160},'four_trips':{'distances':[80,80,80,80],'km':320,'kmpl':4,'expected_l':expected_use([(80,4)]*4)},'refill':{'capacity_l':120,'target_l':100,'predicted_l':20,'measured_l':18,'predicted_topup_l':recommendation(100,20),'measured_topup_l':recommendation(100,18)},'weekly':{'opening_l':40,'delivered_l':200,'transfer_in_l':0,'transfer_out_l':0,'closing_l':60,'disappearance_l':disappeared,'actual_km':720,'kmpl':4,'expected_l':180,'residual_l':residual,'standard_range_km':standard,'range_shortfall_km':shortfall,'equivalent_l':equivalent},'monthly':{'opening_l':120,'delivered_l':2000,'closing_l':180,'actual_km':7600,'kmpl':4,'expected_l':1900,'disappearance_l':monthly,'residual_l':monthly_residual,'legacy_apparent_variance_l':100,'stock_increase_l':60}})

@router.get('/tools/refill-preview')
def refill_preview(target:Decimal=Query(100,ge=0,le=2000),stock:Decimal|None=Query(None,ge=0,le=2000),capacity:Decimal=Query(120,gt=0,le=2000),quality:Literal['measured','estimated','unknown']='unknown',user:User=Depends(current_user)):
    if target>capacity or (stock is not None and stock>capacity):raise HTTPException(422,'Target and stock must fit physical capacity.')
    reliable=stock if quality!='unknown' else None
    return clean({'illustrative':True,'persisted':False,'target_l':target,'stock_l':reliable,'quality':quality,'top_up_l':recommendation(target,reliable),'calculation_version':VERSION,'formula':'max(0, operating target − reliable stock) · unknown stock yields no exact recommendation'})

def ref(db,model,id):
    obj=db.get(model,id) if id else None
    if not obj:raise HTTPException(422,f'{model.__name__} reference not found.')
    return obj

def changed(db,obj,version):
    result=db.execute(update(type(obj)).where(type(obj).id==obj.id,type(obj).version==version).values(version=version+1),execution_options={'synchronize_session':False})
    if result.rowcount!=1:raise HTTPException(409,'Record changed. Reload and review the latest version.')
    db.refresh(obj)

def commit(db):
    try:db.commit()
    except IntegrityError:
        db.rollback();raise HTTPException(409,'Duplicate or conflicting record. Bus number, registration, invoice, pump transaction and idempotency key must be unique.')

def scoped_records(db,user,model):
    qs=db.query(model);scope=vehicle_scope(db,user)
    if scope is None:return qs
    if model is Vehicle:return qs.filter(Vehicle.id.in_(scope))
    if model is Driver:return qs.filter(Driver.id==user.driver_id)
    if model is Assignment:return qs.filter(Assignment.driver_id==user.driver_id)
    if model in (Report,Audit,Approval):raise HTTPException(403,'Reports and audit workspaces require a staff role.')
    if hasattr(model,'vehicle_id'):
        stamp=getattr(model,'occurred_at',None)
        if stamp is None:stamp=getattr(model,'starts_at',None)
        if stamp is None:stamp=model.created_at
        allowed=db.query(Assignment.id).filter(Assignment.vehicle_id==model.vehicle_id,Assignment.driver_id==user.driver_id,Assignment.starts_at<=stamp,or_(Assignment.ends_at==None,Assignment.ends_at>stamp)).exists()
        return qs.filter(model.vehicle_id.in_(scope),allowed)
    if model is Transfer:
        allowed=db.query(Assignment.id).filter(Assignment.driver_id==user.driver_id,or_(Assignment.vehicle_id==Transfer.from_vehicle_id,Assignment.vehicle_id==Transfer.to_vehicle_id),Assignment.starts_at<=Transfer.occurred_at,or_(Assignment.ends_at==None,Assignment.ends_at>Transfer.occurred_at)).exists()
        return qs.filter(allowed)
    if model is Route:
        ids=[a.route_id for a in db.query(Assignment).filter(Assignment.vehicle_id.in_(scope),Assignment.driver_id==user.driver_id).all() if a.route_id]
        return qs.filter(Route.id.in_(ids))
    raise HTTPException(403,'This resource is restricted to fleet staff.')

@router.get('/public/config')
def public_config(db:DBSession=Depends(get_db)):
    c=get_college(db)
    return {'name':c.name,'short_name':c.short_name,'primary_color':c.primary_color,'logo_url':c.logo_url,'timezone':c.timezone,'week_start':c.week_start,'map_style_url':settings.MAP_STYLE_URL,'map_attribution':settings.MAP_ATTRIBUTION,'app_name':'College Fleet Command','mfa_required':settings.MFA_REQUIRED and settings.MFA_ENABLED,'mfa_available':settings.MFA_ENABLED,'evidence_max_mb':3 if settings.SERVERLESS else 10}

@router.post('/auth/login')
def login(payload:LoginInput,request:Request,response:Response,db:DBSession=Depends(get_db)):
    user=db.query(User).filter_by(email=str(payload.email).lower()).first()
    if user and user.locked_until and utc(user.locked_until)>now():raise HTTPException(429,'Too many attempts. Try again in 15 minutes.')
    valid=user is not None and not user.archived and verify_password(payload.password,user.password_hash)
    if valid and settings.MFA_ENABLED and user.mfa_enabled:valid=bool(payload.otp and pyotp.TOTP(decrypt_secret(user.mfa_secret)).verify(payload.otp,valid_window=1))
    if not valid:
        if user:
            user.failed_logins+=1
            if user.failed_logins>=5:user.locked_until=now()+timedelta(minutes=15)
            db.commit()
        else:verify_password(payload.password,password_hash('constant-time-dummy'))
        raise HTTPException(401,'Invalid credentials or MFA code.' if settings.MFA_ENABLED else 'Invalid email or password.')
    user.failed_logins=0;user.locked_until=None;audit(db,user,'login',user,'Authenticated session')
    return create_session(db,user,response,request.headers.get('x-client')=='native')

@router.get('/auth/me')
def me(user:User=Depends(current_user)):return user_view(user)

@router.post('/auth/logout')
def logout(request:Request,response:Response,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    token=request.cookies.get('cfc_session') or request.headers.get('authorization','')[7:]
    s=db.query(Session).filter_by(token_hash=hashlib.sha256(token.encode()).hexdigest()).first()
    if s:s.archived=True
    db.commit();response.delete_cookie('cfc_session',path='/');return {'ok':True}

@router.post('/auth/mfa/enrol')
def mfa_enrol(user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    if not settings.MFA_ENABLED:raise HTTPException(403,'Authenticator verification is disabled for this deployment.')
    if user.mfa_enabled:raise HTTPException(409,'MFA already enabled.')
    secret=pyotp.random_base32();user.mfa_secret=encrypt_secret(secret);db.commit()
    return {'secret':secret,'uri':pyotp.TOTP(secret).provisioning_uri(user.email,issuer_name='College Fleet Command')}

@router.post('/auth/mfa/confirm')
def mfa_confirm(otp:str=Form(...),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    if not settings.MFA_ENABLED:raise HTTPException(403,'Authenticator verification is disabled for this deployment.')
    if not user.mfa_secret or not pyotp.TOTP(decrypt_secret(user.mfa_secret)).verify(otp,valid_window=1):raise HTTPException(422,'Invalid MFA code.')
    user.mfa_enabled=True;audit(db,user,'mfa_enabled',user,'TOTP confirmed');commit(db);return {'ok':True}

@router.get('/users')
def users(user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'SYSTEM_ADMIN'});return [user_view(u)|{'archived':u.archived,'version':u.version} for u in db.query(User).all()]

@router.post('/users',status_code=201)
def add_user(payload:UserInput,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'SYSTEM_ADMIN'})
    if payload.driver_id:ref(db,Driver,payload.driver_id)
    data=payload.model_dump(exclude={'password'});data['email']=str(data['email']).lower()
    u=User(**data,password_hash=password_hash(payload.password));db.add(u)
    try:db.flush()
    except IntegrityError:db.rollback();raise HTTPException(409,'Email already exists.')
    audit(db,user,'create_user',u,'Administrator provisioned account');commit(db);return user_view(u)

@router.post('/users/{id}/disable')
def disable_user(id:str,payload:Decision,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'SYSTEM_ADMIN'});u=ref(db,User,id)
    if u.id==user.id:raise HTTPException(422,'Cannot disable your current account.')
    changed(db,u,payload.version);u.archived=not u.archived
    for s in db.query(Session).filter_by(user_id=u.id).all():s.archived=True
    audit(db,user,'toggle_account',u,payload.reason);commit(db);return user_view(u)

@router.get('/settings')
def get_settings(user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,ADMIN|APPROVERS|{'AUDITOR'});return serial(get_college(db))|{'database_mode':settings.DATABASE_MODE,'storage':'s3_private' if settings.S3_BUCKET else 'local_private','gps_credentials_configured':bool(settings.GPS_PROVIDER_TOKEN),'mfa_required':settings.MFA_REQUIRED and settings.MFA_ENABLED,'mfa_available':settings.MFA_ENABLED,'evidence_max_mb':3 if settings.SERVERLESS else 10}

@router.put('/settings')
def set_settings(payload:CollegeInput,version:int,reason:str=Query(min_length=3),user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    require(user,{'SYSTEM_ADMIN'});c=get_college(db);before=serial(c);changed(db,c,version)
    for k,v in payload.model_dump().items():setattr(c,k,v)
    audit(db,user,'configure',c,reason,before);commit(db);return serial(c)

@router.get('/dashboard')
def fleet_dashboard(start:date,end:date,search:str='',status:str='',include_archived:bool=False,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    return dashboard(db,user,start,end,search=search,status=status,include_archived=include_archived)

@router.get('/buses/{vehicle_id}/detail')
def detail(vehicle_id:str,start:date,end:date,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    a,b=boundaries(start,end);check_period(db,user,vehicle_id,a,b);v=vehicle(db,vehicle_id);data=summarise_bus(db,v,start,end);histories={}
    for kind in ('assignments','devices','mileage','fuel','tank-readings','calibrations','manual-trips','cases','reports'):
        model=MODELS[kind];qs=db.query(model).filter(model.vehicle_id==v.id)
        if kind in ('fuel','tank-readings'):qs=qs.filter(model.occurred_at>=a,model.occurred_at<b)
        if user.role=='DRIVER' and kind in ('assignments','devices'):qs=qs.filter(model.starts_at<b,or_(model.ends_at==None,model.ends_at>a))
        if user.role=='DRIVER' and kind in ('manual-trips',):qs=qs.filter(model.starts_at>=a,model.ends_at<=b)
        if user.role=='DRIVER' and kind in ('cases',):qs=qs.filter(model.created_at>=a,model.created_at<b)
        if user.role=='DRIVER' and kind in ('reports',):qs=qs.filter(model.id=='no-driver-report-access')
        histories[kind]=[serial(o,user) for o in qs.order_by(model.created_at.desc()).limit(1000).all()]
    ids={x.route_id for x in db.query(Assignment).filter_by(vehicle_id=v.id).all() if x.route_id}
    histories['surveys']=[serial(s,user) for s in db.query(Survey).filter(Survey.route_id.in_(ids)).all()] if ids else []
    evidence_query=db.query(Evidence).filter_by(vehicle_id=v.id)
    if user.role=='DRIVER':
        evidence_query=evidence_query.filter(Evidence.id.in_([f['evidence_id'] for f in histories['fuel'] if f.get('evidence_id')]))
    histories['evidence']=[serial(e,user) for e in evidence_query.all()]
    histories['audit']=[] if user.role=='DRIVER' else [serial(e,user) for e in db.query(Audit).filter_by(vehicle_id=v.id).order_by(Audit.created_at.desc()).limit(200).all()]
    for t in histories['manual-trips']:t['driver_name']=ref(db,Driver,t['driver_id']).name if t.get('driver_id') else None
    return {'vehicle':serial(v),'summary':data,'history':histories}

@router.get('/buses/{vehicle_id}/gps')
def gps_history(vehicle_id:str,start:date,end:date,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    a,b=boundaries(start,end);check_period(db,user,vehicle_id,a,b)
    rows=db.query(GPSPoint).filter(GPSPoint.vehicle_id==vehicle_id,GPSPoint.fix_at>=a,GPSPoint.fix_at<b).order_by(GPSPoint.fix_at).limit(10000).all()
    return {'items':[serial(r,user) for r in rows],'limit':10000,'truncated':len(rows)==10000}

@router.get('/explain/{metric}')
def explain(metric:str,start:date,end:date,vehicle_id:str|None=None,user:User=Depends(current_user),db:DBSession=Depends(get_db)):
    if metric not in FORMULAS:raise HTTPException(404,'Unknown metric.')
    if vehicle_id:check_vehicle(db,user,vehicle_id)
    data=dashboard(db,user,start,end,vehicle_id=vehicle_id,include_sources=True);formula,unit=FORMULAS[metric]
    return {'metric':metric,'formula':formula,'unit':unit,'period':data['period'],'value':data['buses'][0].get(metric) if vehicle_id and data['buses'] else data['metrics'].get(metric),'calculation_version':VERSION,'rounding':'Decimal arithmetic; ROUND_HALF_UP, 3 decimal places for km and L; 2 for INR. Fleet sums use the displayed rounded daily summaries.','quality':'Exact verified stock boundaries and GPS completeness gate residuals. Partial metrics list contributing buses.','contributors':data['contributors'].get(metric),'sources':[{'vehicle_id':b['vehicle_id'],'bus_number':b['bus_number'],'source_ids':b['source_ids'],'daily':b['daily'],'mileage_versions':b['mileage_versions'],'stock_l':b['stock_l'],'stock_quality':b['stock_quality'],'stock_as_of':b['stock_as_of'],'stock_anchor':b['stock_anchor'],'stock_reason':b['stock_reason'],'stock_source_ids':b['stock_source_ids'],'operating_target_l':b['operating_target_l'],'top_up_l':b['top_up_l'],'latest_refill':b['latest_refill'],'km_shortage_km':b['km_shortage_km'],'diesel_shortage_l':b['diesel_shortage_l'],'route_shortage_km':b['route_shortage_km'],'reconciled_range_km':b['reconciled_range_km'],'disappearance_l':b['disappearance_l'],'expected_l':b['expected_l'],'uncertainty_l':b['uncertainty_l'],'shortage_status':b['shortage_status'],'shortage_basis':b['shortage_basis']} for b in data['buses']],'tanglish':'GPS km-ai approved km/L-aal divide pannina expected diesel L. Stock illaina zero-nu edukkakoodathu. Residual irundhaal review seyyavum.'}
