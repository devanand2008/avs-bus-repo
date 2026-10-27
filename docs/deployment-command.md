# Setup, security, backups and restores

## Existing repository and runtime

This repository already used React/Next.js and FastAPI/SQLAlchemy. College Fleet Command preserves that working stack rather than introducing a second Django server. The new backend is the `fleet/` modular monolith, mounted at `/api/v2`; the prior frontend is preserved in `frontend/legacy-ui/` and legacy APIs are unmounted. Existing `fuelguard.db` and original operational tables are not migrated into or deleted by the new schema. Historical data must be validated and imported explicitly.

Requirements: Python 3.11+, Node 24, Supabase PostgreSQL or MySQL 8.4+, and Redis/Celery for production background jobs. Docker Compose is optional. The first local verification used the official MySQL Windows ZIP, running loopback-only at port 3307 under `.runtime/` with generated private passwords. This binary/data is ignored and not part of source delivery.

## Configure Supabase first

Copy `backend/.env.example` to `backend/.env`. Use the Supabase **Postgres database connection** (direct or session pooler appropriate to your network), not the browser anon key. Set `DATABASE_MODE=supabase`, `DATABASE_URL`, a random `SECRET_KEY` (32+ characters), `BOOTSTRAP_EMAIL` and a unique bootstrap password (12+ characters). Keep every database/vendor/storage credential server-side.

Supabase guidance: [database connections](https://supabase.com/docs/guides/database/connecting-to-postgres), [SQLAlchemy](https://supabase.com/kb/troubleshooting/using-sqlalchemy-with-supabase-FUqebT). Use TLS. `sslmode=require` encrypts traffic; for verified server identity use `sslmode=verify-full` and the downloaded provider certificate via `sslrootcert`. Use an account authorised to create PostGIS and the `cfc_*` tables. After migrations, use a least-privilege application database role; retain the owner only for migrations/backups.

Migrations enable RLS and revoke direct `PUBLIC`, `anon` and `authenticated` access on new tables. All browser/mobile access goes through the authenticated backend. Do not add permissive Supabase browser policies or ship service-role credentials in React code.

## Explicit MySQL fallback

If Supabase cannot be used, configure MySQL and explicitly set `DATABASE_MODE=mysql` and `MYSQL_DATABASE_URL=mysql+pymysql://USER:URL_ENCODED_PASSWORD@HOST:3306/college_fleet?charset=utf8mb4`. Create an empty UTF-8 database and an authorised application user. MySQL uses numeric coordinates and GeoJSON plus the same server distance engine; PostGIS-specific spatial indexing is unavailable in MySQL mode.

Database failure never automatically redirects writes into another database. Migrating existing records between Supabase and MySQL requires a deliberate, verified export/import and reconciliation, not changing modes during operations. SQLite is accepted only under explicit ephemeral test settings, never as a production fallback.

## Start locally

```powershell
cd D:\bus\backend
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m fleet.cli bootstrap
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In another terminal:

```powershell
cd D:\bus\frontend
npm ci
npm run dev
```

Open `http://localhost:3000`; API/OpenAPI: `http://localhost:8000/docs`. On this machine the generated admin credentials are in the ignored `.runtime/local-access.txt`. The bootstrap command creates college settings and that administrator only. The Windows launcher is `start_college_fleet_command.bat` (or `powershell -NoProfile -File scripts/start.ps1` where script execution is permitted). It reuses configured services, checks the selected database, migrates, bootstraps and starts the development scheduler. It never seeds a fleet.

For real phone testing, bind the API to a deliberately authorised LAN interface and configure a reachable API URL and allowed origins. Avoid exposing a development server to the public Internet. Production must use HTTPS, `ENVIRONMENT=production`, `COOKIE_SECURE=true`, a random secret and `MFA_REQUIRED=true`. Set allowed CORS origins explicitly. Proxy/load-balancer trust, TLS, host allowlists, monitoring and rate limits must be configured at deployment.

## Background work

For Compose, stop the standalone services first to free ports. With Supabase set the connection URL in `backend/.env`, then run `docker compose up --build -d`. With the optional container MySQL set `DATABASE_MODE=mysql` and set `MYSQL_DATABASE_URL` to `mysql+pymysql://fleet:URL_ENCODED_PASSWORD@mysql:3306/college_fleet?charset=utf8mb4` in `backend/.env`. Put matching `MYSQL_PASSWORD` and a different `MYSQL_ROOT_PASSWORD` in a private root `.env`, start `docker compose --profile mysql up -d mysql`, wait for its health check, then run `docker compose --profile mysql up --build -d`. Do not use the example development passwords for deployment. Browser origins still use the public web host, not the container hostname. Compose has not been runtime-tested on this machine because Docker is unavailable.

Production Redis must be private, authenticated and TLS-protected when crossing hosts. Run:

```text
celery -A fleet.tasks:celery worker --loglevel=INFO --concurrency=2
celery -A fleet.tasks:celery beat --loglevel=INFO
```

Beat rebuilds the last three days at 01:15 Asia/Kolkata and polls an explicitly configured provider every minute. Backfill older affected periods deliberately. Provider ingestion also rebuilds affected days and flags frozen reports for revision. Queued reports are available through `/reports/queue`; synchronous report freeze remains usable without Redis. On Windows local development without Redis, `python -m fleet.scheduler` runs the scheduled functions directly; this is not a distributed worker replacement.

## React Native

```powershell
cd D:\bus\mobile
npm ci
# Configure EXPO_PUBLIC_API_URL from .env.example for your actual device/network.
npm start
```

Expo SDK 55 supports the included native source. `npm run export` compiles Android/iOS Hermes and web bundles; it does **not** produce signed installable APK/IPA files. Android SDK/JDK are needed for `npm run android`; Xcode/macOS for `npm run ios`, or use a properly configured EAS account/build environment. Confirm college-owned bundle identifiers and signing before distribution. See [Expo SecureStore](https://docs.expo.dev/versions/v55.0.0/sdk/securestore/) for native storage behaviour.

## Private evidence

Development stores evidence under `PRIVATE_STORAGE_DIR`, outside the web root. Supply S3-compatible endpoint, private bucket and restricted server credentials to use S3. The backend proxies authorised downloads and verifies SHA-256; there are no public evidence URLs. Keep bucket ACLs private, enable server encryption and retention/versioning, and test the provider's encryption support. PNG/JPEG/PDF type/content and size checks run server-side; a production malware scanning/quarantine integration is still required before accepting untrusted third-party documents at scale.

Sessions are revocable hashed random tokens, HttpOnly/SameSite cookies for web and bearer tokens in SecureStore on native devices. Mutating cookie requests require trusted origin checks. MFA secrets are encrypted from the server secret. Keep that secret recoverable in the organisation's secret manager: losing it invalidates encrypted MFA secrets. Shared devices need device encryption and access control; offline refill drafts contain operational data and must be cleared after sync.

## Backup and restore

Back up the database, private evidence, configuration/secret-manager references, report snapshots and audit data together. Keep encrypted off-machine copies, retention policies and restore logs. SQL-backed audit digests detect accidental alteration; database owners can alter SQL data, so independent retained backups/object versioning are necessary for stronger tamper resistance.

- Supabase/Postgres: use provider backups/PITR plus a tested logical dump (`pg_dump --format=custom --file=<backup> <connection>`). Supply secrets through a protected service file/environment, not shell history. Restore with `pg_restore` into a **new** database/project, then check migrations, counts, roles/RLS, evidence hashes and report hashes.
- MySQL: use `mysqldump --single-transaction --routines --triggers` with a protected defaults file. Restore into a **new**, empty database. Confirm UTF-8, time conversion, constraints and row counts before switching the application URL.
- Evidence: copy private local storage or use versioned private S3 backups. Database-only restore does not restore file bytes. Verify every evidence row's SHA-256 and test authorised/unauthorised download paths.
- Back up secrets separately using organisational recovery controls. Do not store live passwords in repository archives.

Run an actual restore drill and reconcile a known period before using any restored system. No live Supabase, remote S3, Redis worker, physical native-device or hardware restore drill was performed by the initial local build.
