"""College Fleet Command public ASGI entry point. Legacy APIs are unmounted."""
import logging, os, hmac
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy import text
from sqlalchemy.exc import OperationalError
from fleet.config import settings
from fleet.db import engine
from fleet.api import router
import fleet.resources
import fleet.operations
import fleet.report_api

app = FastAPI(title='College Fleet Command', version='2.0.0', description='Private fleet operations API; the live OpenAPI contract is authoritative.')
origins = [s.strip() for s in settings.CORS_ORIGINS.split(',') if s.strip()]
for name in ('VERCEL_URL','VERCEL_PROJECT_PRODUCTION_URL'):
    if os.environ.get(name): origins.append('https://'+os.environ[name])
app.add_middleware(CORSMiddleware, allow_origins=origins, allow_credentials=True, allow_methods=['GET','POST','PUT'], allow_headers=['Content-Type','Authorization','X-Client','X-GPS-Signature'])

@app.middleware('http')
async def protect(request: Request, call_next):
    try:
        size = int(request.headers.get('content-length','0') or '0')
    except ValueError:
        return JSONResponse({'detail':'Invalid content length.'},400)
    if size > 12*1024*1024:
        return JSONResponse({'detail':'Request too large.'},413)
    if request.method not in ('GET','HEAD','OPTIONS') and request.url.path != '/api/v2/gps/webhook':
        origin = request.headers.get('origin')
        if origin and origin not in origins:
            return JSONResponse({'detail':'Untrusted request origin.'},403)
        if request.cookies.get('cfc_session') and not request.headers.get('authorization') and not origin and request.headers.get('sec-fetch-site') not in ('same-origin','same-site'):
            return JSONResponse({'detail':'Cookie mutations require an allowed Origin.'},403)
    response = await call_next(request)
    response.headers['X-Content-Type-Options'] = 'nosniff'
    response.headers['X-Frame-Options'] = 'DENY'
    if request.url.path.startswith('/api/'):
        response.headers['Cache-Control'] = 'no-store'
    return response

@app.exception_handler(OperationalError)
async def database_error(request, exc):
    logging.getLogger('fleet').error('Database unavailable (%s); no fallback used.',type(exc).__name__)
    return JSONResponse({'detail':'Database unavailable. Check the configured Supabase or MySQL connection. No writes were redirected.'},503)

@app.get('/api/health')
def health():
    try:
        with engine.connect() as conn:
            conn.execute(text('SELECT 1'))
            row=conn.execute(text('SELECT id,name,short_name FROM cfc_college LIMIT 1')).first()
            if not row:raise RuntimeError('College not bootstrapped')
        return {'status':'healthy','database':settings.DATABASE_MODE,'app':'College Fleet Command','college_name':row.name,'college_short_name':row.short_name,'timezone':'Asia/Kolkata','demo_auto_seed':False}
    except Exception:
        return JSONResponse({'status':'not_ready','database':settings.DATABASE_MODE,'detail':'Database or migrations unavailable. No automatic fallback.'},503)

app.include_router(router)

@app.get('/api/v2/public/deployment')
def deployment_status():
    if engine is None:
        return {'ready':False,'message':'The web and API are deployed. A dedicated fleet database must be connected and initialised before staff sign-in is available.'}
    return {'ready':True}

@app.get('/api/cron/daily')
def daily_cron(request:Request):
    from fastapi import HTTPException
    if not settings.CRON_SECRET or not hmac.compare_digest(request.headers.get('authorization',''), 'Bearer '+settings.CRON_SECRET):
        raise HTTPException(401,'Authorised scheduler required.')
    if engine is None:raise HTTPException(503,'Dedicated database configuration is pending.')
    from fleet.tasks import daily
    daily.run()
    return {'status':'completed','timezone':'Asia/Kolkata'}
