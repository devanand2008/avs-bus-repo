"""Build an isolated local QA frontend without changing operational API configuration."""
import os,subprocess
from pathlib import Path
root=Path(__file__).resolve().parents[1];env=os.environ.copy();env.update(API_INTERNAL_URL='http://127.0.0.1:8001',CFC_DIST_DIR='.cfc-qa')
raise SystemExit(subprocess.call(['node',str(root/'frontend/node_modules/next/dist/bin/next'),'build'],cwd=root/'frontend',env=env))
