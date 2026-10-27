from celery import Celery
from celery.schedules import crontab
from datetime import date,timedelta
from fleet.config import settings
from fleet.db import SessionLocal
from fleet.models import Vehicle, now
from fleet.calculations import IST,day_start
from fleet.services import rebuild

celery=Celery('college_fleet_command',broker=settings.REDIS_URL,backend=settings.REDIS_URL)
celery.conf.update(timezone='Asia/Kolkata',enable_utc=True,task_serializer='json',accept_content=['json'],result_serializer='json',beat_schedule={'daily-recalculation':{'task':'fleet.daily','schedule':crontab(hour=1,minute=15)},'gps-refresh':{'task':'fleet.provider_poll','schedule':60.0}})

@celery.task(name='fleet.daily',autoretry_for=(ConnectionError,),retry_backoff=True,max_retries=5)
def daily():
    end=now().astimezone(IST).date()+timedelta(days=1)
    with SessionLocal() as db:
        for v in db.query(Vehicle).all():rebuild(db,v.id,end-timedelta(days=3),end)
        db.commit()

@celery.task(name='fleet.provider_backfill',autoretry_for=(ConnectionError,),retry_backoff=True,max_retries=5)
def provider_backfill(start,end):
    from fleet.providers import ConfiguredProvider
    from fleet.operations import ingest_points
    from fleet.schemas import GPSInput
    provider=ConfiguredProvider()
    with SessionLocal() as db:
        for page in provider.historical_positions(day_start(date.fromisoformat(start)),day_start(date.fromisoformat(end))):
            ingest_points(db,[GPSInput.model_validate(p) for p in page])

@celery.task(name='fleet.provider_poll')
def provider_poll():
    if not settings.GPS_PROVIDER_TOKEN:return {'status':'not_configured'}
    end=now().astimezone(IST).date()+timedelta(days=1)
    return provider_backfill(str(end-timedelta(days=2)),str(end))

@celery.task(name='fleet.report',autoretry_for=(ConnectionError,),retry_backoff=True,max_retries=3)
def report_job(user_id,start,end,kind,vehicle_id=None):
    from fleet.models import User
    from fleet.report_api import freeze_report
    with SessionLocal() as db:
        user=db.get(User,user_id)
        return freeze_report(date.fromisoformat(start),date.fromisoformat(end),kind,vehicle_id,True,None,user,db)['id']
