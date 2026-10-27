"""Server-only vendor adapter contract. Vendor-specific mapping needs authorised validation."""
from abc import ABC,abstractmethod
from datetime import timedelta
from decimal import Decimal
import time
import httpx
from fleet.config import settings

class ProviderAdapter(ABC):
    @abstractmethod
    def device_inventory(self):...
    @abstractmethod
    def historical_positions(self,start,end):...
    @abstractmethod
    def health(self):...
    def live_updates(self):
        raise NotImplementedError('Use signed webhook forwarding when supported by the vendor.')
    def backfill(self,start,end):return self.historical_positions(start,end)

class DemoProvider(ProviderAdapter):
    """Deterministic synthetic path. Never enabled automatically and clearly source-labelled."""
    def __init__(self,device_id='DEMO-001'):self.device_id=device_id
    def device_inventory(self):return [{'device_id':self.device_id,'provider':'synthetic_demo'}]
    def health(self):return {'status':'synthetic_demo','real_telemetry':False}
    def historical_positions(self,start,end):
        points=[];t=start;i=0
        while t<end:
            points.append({'provider':'synthetic_demo','device_id':self.device_id,'event_id':f'{self.device_id}:{t.isoformat()}','fix_at':t.isoformat(),'lat':str(Decimal('11.6500000')+Decimal(i%100)*Decimal('0.0005000')),'lon':'78.1600000','speed':'30','source_unit':'kmh','ignition':True,'accuracy_m':'5','raw':{'synthetic':True}})
            t+=timedelta(seconds=30);i+=1
            if len(points)==500:yield points;points=[]
        if points:yield points

class ConfiguredProvider(ProviderAdapter):
    """Template contract: GET /devices, /positions?from=&to=&cursor=, /health.
    Vendor response positions: {items:[GPSInput],next_cursor:null}. Adapt these methods to vendor docs.
    """
    def __init__(self):
        if not settings.GPS_PROVIDER_URL.startswith('https://') or not settings.GPS_PROVIDER_TOKEN:raise RuntimeError('Authorised HTTPS provider URL and server-side token required.')
        self.client=httpx.Client(base_url=settings.GPS_PROVIDER_URL,headers={'Authorization':f'Bearer {settings.GPS_PROVIDER_TOKEN}'},timeout=30)
    def request(self,path,params=None):
        for attempt in range(5):
            r=self.client.get(path,params=params)
            if r.status_code==429 or r.status_code>=500:
                time.sleep(min(30,float(r.headers.get('Retry-After',2**attempt))));continue
            r.raise_for_status();return r.json()
        raise ConnectionError('Provider retry limit reached; task remains retryable.')
    def device_inventory(self):return self.request('/devices')
    def health(self):return self.request('/health')
    def historical_positions(self,start,end):
        cursor=None;seen=set()
        while True:
            data=self.request('/positions',{'from':start.isoformat(),'to':end.isoformat(),'cursor':cursor or ''});yield data['items'];cursor=data.get('next_cursor')
            if not cursor:break
            if cursor in seen:raise ConnectionError('Provider returned a repeated pagination cursor.')
            seen.add(cursor)
