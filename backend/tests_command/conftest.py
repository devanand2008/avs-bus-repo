import os,sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
url=os.environ.get('TEST_DATABASE_URL','sqlite:///:memory:')
if url.startswith('mysql'):
    if not url.split('?',1)[0].endswith('_test'):raise RuntimeError('MySQL tests require a separate database ending in _test.')
    os.environ['DATABASE_MODE']='mysql';os.environ['MYSQL_DATABASE_URL']=url
else:
    if url!='sqlite:///:memory:':raise RuntimeError('Default tests use ephemeral in-memory SQLite only.')
    os.environ['DATABASE_MODE']='test';os.environ['DATABASE_URL']=url;os.environ['ALLOW_TEST_SQLITE']='true'
os.environ['SECRET_KEY']='test-only-not-a-production-secret-000000000'
os.environ['MFA_REQUIRED']='false'
import pytest
from fastapi.testclient import TestClient
from fleet.db import Base,engine,SessionLocal,get_db
from fleet.models import *
from fleet.auth import password_hash
from app.main import app
from hashlib import sha256

@pytest.fixture
def env(tmp_path,monkeypatch):
    from fleet.config import settings
    monkeypatch.setattr(settings,'PRIVATE_STORAGE_DIR',str(tmp_path))
    Base.metadata.drop_all(engine);Base.metadata.create_all(engine)
    with SessionLocal() as db:
        c=College(name='Synthetic Test College',demo=True);db.add(c)
        users={};headers={};pw=password_hash('test-password-123')
        for role in ('SYSTEM_ADMIN','DATA_ADMIN','CORRESPONDENT','TRANSPORT_VERIFIER','FUELLER','DRIVER','ACCOUNTS','AUDITOR'):
            user=User(email=role.lower()+'@example.com',name='Synthetic '+role,role=role,password_hash=pw,demo=True);db.add(user);db.flush();users[role]=user.id
            token='test-session-'+role;db.add(Session(user_id=user.id,token_hash=sha256(token.encode()).hexdigest(),expires_at=now()+__import__('datetime').timedelta(hours=1)))
            headers[role]={'Authorization':'Bearer '+token,'Origin':'http://localhost:3000'}
        db.commit()
    client=TestClient(app)
    yield {'client':client,'users':users,'headers':headers,'db':SessionLocal}
    client.close();Base.metadata.drop_all(engine)

@pytest.fixture
def fleet(env):
    from fleet.calculations import day_start,D
    from datetime import date
    from PIL import Image
    import io,hashlib
    e=env;db=e['db']();u=e['users'];v=Vehicle(bus_number='007',registration='TEST-TN-30-007',tank_capacity_l=220,safe_fill_l=200,operating_target_l=100,demo=True);db.add(v);db.flush()
    driver=Driver(employee_id='TEST-D1',name='Synthetic Test Driver',mobile='restricted',demo=True);db.add(driver);db.flush();db.get(User,u['DRIVER']).driver_id=driver.id
    route=Route(code='TEST-R1',name='Synthetic Test Route',trip_km=80,scope='round_trip',created_by=u['DATA_ADMIN'],approved_by=u['TRANSPORT_VERIFIER']);db.add(route);db.flush()
    start=day_start(date(2026,9,1));db.add(Assignment(vehicle_id=v.id,driver_id=driver.id,route_id=route.id,starts_at=start,reason='Synthetic fixture'))
    db.add(DeviceMapping(vehicle_id=v.id,provider='test_provider',device_id='DEVICE-007',starts_at=start,cadence_seconds=30))
    im=Image.new('RGB',(100,100),'white');buffer=io.BytesIO();im.save(buffer,'PNG');raw=buffer.getvalue()
    from fleet.config import settings
    key='test.png';(Path(settings.PRIVATE_STORAGE_DIR)/key).write_bytes(raw)
    ev=Evidence(vehicle_id=v.id,uploaded_by=u['DATA_ADMIN'],filename=key,mime='image/png',size=len(raw),sha256=hashlib.sha256(raw).hexdigest(),storage_key=key);db.add(ev);db.flush()
    m=Mileage(vehicle_id=v.id,kmpl=4,effective_from=start,reason='Synthetic tested standard',created_by=u['DATA_ADMIN'],approved_by=u['TRANSPORT_VERIFIER'],evidence_id=ev.id);db.add(m);db.commit()
    result={**e,'vehicle':v.id,'driver':driver.id,'route':route.id,'evidence':ev.id,'mileage':m.id,'image':raw};db.close();return result
