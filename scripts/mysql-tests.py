"""Run the real MySQL suite against a disposable, separate *_test database."""
import os,sys,secrets,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];sys.path.insert(0,str(root/'backend'))
import pymysql
access=(root/'.runtime/local-access.txt').read_text(encoding='utf-8');rootpw=next(x.split(': ',1)[1] for x in access.splitlines() if x.startswith('Root password: '))
password=secrets.token_urlsafe(30)
conn=pymysql.connect(host='127.0.0.1',port=3307,user='root',password=rootpw)
with conn.cursor() as c:
    c.execute('CREATE DATABASE IF NOT EXISTS college_fleet_test CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
    c.execute('CREATE USER IF NOT EXISTS fleet_test@localhost IDENTIFIED BY %s',(password,))
    c.execute('ALTER USER fleet_test@localhost IDENTIFIED BY %s',(password,))
    c.execute('GRANT ALL PRIVILEGES ON college_fleet_test.* TO fleet_test@localhost')
conn.commit();conn.close()
env=os.environ.copy();env['TEST_DATABASE_URL']=f'mysql+pymysql://fleet_test:{password}@127.0.0.1:3307/college_fleet_test?charset=utf8mb4'
raise SystemExit(subprocess.call([sys.executable,'-m','pytest','tests_command','-q','--disable-warnings'],env=env,cwd=root/'backend'))
