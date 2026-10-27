"""First-time local MySQL setup after starting loopback-only mysqld. No synthetic data."""
import secrets,sys,time
from pathlib import Path
import pymysql
root=Path(__file__).resolve().parents[1];runtime=root/'.runtime';runtime.mkdir(exist_ok=True)
if (runtime/'local-access.txt').exists():raise SystemExit('Local configuration already exists; refusing to replace credentials.')
for attempt in range(30):
    try:conn=pymysql.connect(host='127.0.0.1',port=3307,user='root',password='');break
    except pymysql.err.OperationalError:time.sleep(1)
else:raise SystemExit('Start local MySQL first.')
dbpass=secrets.token_urlsafe(32);rootpass=secrets.token_urlsafe(40);adminpass=secrets.token_urlsafe(18)
with conn.cursor() as c:
    c.execute('CREATE DATABASE IF NOT EXISTS college_fleet CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    c.execute('CREATE USER IF NOT EXISTS fleet_local@localhost IDENTIFIED BY %s',(dbpass,))
    c.execute('GRANT ALL PRIVILEGES ON college_fleet.* TO fleet_local@localhost')
    c.execute('ALTER USER root@localhost IDENTIFIED BY %s',(rootpass,))
conn.commit();conn.close()
env=root/'backend'/'.env'
if env.exists():(runtime/'legacy-backend.env').write_bytes(env.read_bytes())
env.write_text(f'DATABASE_MODE=mysql\nMYSQL_DATABASE_URL=mysql+pymysql://fleet_local:{dbpass}@127.0.0.1:3307/college_fleet?charset=utf8mb4\nSECRET_KEY={secrets.token_urlsafe(48)}\nBOOTSTRAP_EMAIL=admin@collegefleet.in\nBOOTSTRAP_PASSWORD={adminpass}\nCORS_ORIGINS=http://localhost:3000,http://127.0.0.1:3000,http://localhost:3001,http://127.0.0.1:3001\nMFA_REQUIRED=false\nGPS_SIMULATOR_ENABLED=false\n',encoding='utf-8')
(runtime/'local-access.txt').write_text(f'LOCAL DEVELOPMENT ONLY — keep private\nWeb: http://localhost:3000\nAdministrator: admin@collegefleet.in\nPassword: {adminpass}\nMySQL port: 3307\nDatabase: college_fleet\nRoot password: {rootpass}\nDo not use these credentials in a real deployment. No fleet records are seeded.\n',encoding='utf-8')
print('Private local credentials saved in .runtime/local-access.txt. backend/.env configured for explicit MySQL mode. No fleet data added.')
