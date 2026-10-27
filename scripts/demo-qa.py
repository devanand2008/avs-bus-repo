"""Create a separate, clearly labelled synthetic QA database; operational data is untouched."""
import os,sys,secrets,subprocess,json,time
from pathlib import Path
import pymysql
root=Path(__file__).resolve().parents[1];runtime=root/'.runtime'
env=os.environ.copy()
if (runtime/'demo-env.json').exists():env.update(json.loads((runtime/'demo-env.json').read_text()))
else:
    access=(runtime/'local-access.txt').read_text(encoding='utf-8');rootpw=next(x.split(': ',1)[1] for x in access.splitlines() if x.startswith('Root password: '));pw=secrets.token_urlsafe(30)
    conn=pymysql.connect(host='127.0.0.1',port=3307,user='root',password=rootpw)
    with conn.cursor() as c:
        c.execute('CREATE DATABASE IF NOT EXISTS college_fleet_demo CHARACTER SET utf8mb4 COLLATE utf8mb4_unicode_ci')
        c.execute('CREATE USER IF NOT EXISTS fleet_demo@localhost IDENTIFIED BY %s',(pw,))
        c.execute('GRANT ALL PRIVILEGES ON college_fleet_demo.* TO fleet_demo@localhost')
    conn.commit();conn.close()
    demo_password=secrets.token_urlsafe(18)
    values={'DATABASE_MODE':'mysql','MYSQL_DATABASE_URL':f'mysql+pymysql://fleet_demo:{pw}@127.0.0.1:3307/college_fleet_demo?charset=utf8mb4','BOOTSTRAP_EMAIL':'admin@demo.example.com','BOOTSTRAP_PASSWORD':demo_password,'DEMO_PASSWORD':demo_password,'COLLEGE_NAME':'SYNTHETIC QA — AVS Engineering College','PRIVATE_STORAGE_DIR':str(runtime/'demo-evidence')}
    (runtime/'demo-env.json').write_text(json.dumps(values),encoding='utf-8');env.update(values)
if '--serve' in sys.argv:
    raise SystemExit(subprocess.call([sys.executable,'-m','uvicorn','app.main:app','--host','127.0.0.1','--port','8001'],cwd=root/'backend',env=env))
for command in ([sys.executable,'-m','alembic','upgrade','head'],[sys.executable,'-m','fleet.cli','bootstrap'],[sys.executable,'-m','fleet.cli','demo','--synthetic-only']):
    result=subprocess.call(command,cwd=root/'backend',env=env)
    if result:raise SystemExit(result)
print('Synthetic QA environment created separately. Operational fleet remains empty.')
