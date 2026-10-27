"""Start a loopback-only QA web server, with a fixed local API and separate build directory."""
import os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1]
env=os.environ.copy();env.update(API_INTERNAL_URL='http://127.0.0.1:8001',CFC_DIST_DIR='.cfc-qa')
raise SystemExit(subprocess.call(['node',str(root/'frontend/node_modules/next/dist/bin/next'),'start','--hostname','127.0.0.1','--port','3001'],cwd=root/'frontend',env=env))
