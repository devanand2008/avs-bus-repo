"""Development scheduler when local Redis is unavailable. Production uses Celery Beat."""
from apscheduler.schedulers.blocking import BlockingScheduler
from fleet.tasks import daily,provider_poll
if __name__=='__main__':
    scheduler=BlockingScheduler(timezone='Asia/Kolkata')
    scheduler.add_job(daily.run,'cron',hour=1,minute=15,id='daily',max_instances=1,coalesce=True)
    scheduler.add_job(provider_poll.run,'interval',minutes=1,id='poll',max_instances=1,coalesce=True)
    print('Local development scheduler active. Daily 01:15 IST; configured-provider poll each minute.',flush=True)
    scheduler.start()
