# College Fleet Command

Daily GPS kilometres, timestamped tank balances, posted-refill readings, refill recommendations and km/diesel shortage review figures are available on the dashboard and bus details. See [tank and refill operation / synthetic tests](docs/tank-and-refill.md).


A persistent college fleet operations product for **AVS Engineering College**. College branding is configurable. There is no hardcoded fleet size.

The supplied application logo is retained in `logo/Gemini_Generated_Image_gzm9c8gzm9c8gzm9.png`. Run `python scripts/brand-assets.py` after replacing that artwork to regenerate web/PWA icons, React Native assets and the PDF report logo. Native launcher/splash changes require a new native build; refreshing the web app updates its displayed logo.

The repository contains a React/Next.js web PWA, a FastAPI/SQLAlchemy backend, a React Native/Expo app, Supabase PostgreSQL and explicit MySQL support, versioned calculations, private evidence, independent fuel/report workflows, migrations, Celery jobs, tests and operator documentation. The pre-existing stack was retained; this is not a new Django/Vite repository.

## Cloud deployment

The web and FastAPI API are deployed at [college-fleet-command.vercel.app](https://college-fleet-command.vercel.app). Production uses Supabase project `zzrtilfronngzpuiymzi`, isolated `college_fleet` schema and a dedicated database role. Sign in with email and password; authenticator verification is disabled at the user's request. Private initial credentials are in `.runtime/cloud-access.txt`. See [deployment details](docs/vercel-deployment.md) for scheduled calculations, durable evidence, native API configuration and worker limits.

## Open the local application

- Web: [http://localhost:3000](http://localhost:3000)
- API/OpenAPI: [http://localhost:8000/docs](http://localhost:8000/docs)
- New animated login: [http://localhost:3000/login](http://localhost:3000/login)
- Generated local admin credentials: **`.runtime/local-access.txt`** (private, ignored by Git).
- Windows launcher: double-click **`RUN_COLLEGE_FLEET.bat`** in `D:\bus` (the existing `start_college_fleet_command.bat` works too). It starts the configured local database when applicable, checks migrations, starts the API/web/scheduler, waits for the login page and opens your default browser. Keep the folder in place; the services run in the background.
- Repeat checks: double-click **`run_tests.bat`**. Detailed results and remaining integration work are in `docs/verification.md`.
- Launch without opening a browser: `RUN_COLLEGE_FLEET.bat --no-browser`. Repeated launches reuse healthy services. No administrator rights or PowerShell execution-policy change is needed.
- If a port belongs to another app, the launcher stops with an explanation rather than stopping that process. Logs are in `.runtime/launcher-*.log`; setup logs may contain private database configuration, so do not share them publicly.
- On a new machine, complete the dependency and database setup below first. This launcher runs the local development web server; it is not a public deployment installer.

**Operational startup creates only the configured administrator and college settings. No fabricated buses, drivers, fuel or GPS records are inserted.** The explicit 30-bus/60-day demonstration command is for a separate empty database and requires a synthetic-data acknowledgement.

## Setup

1. Copy `backend/.env.example` to `backend/.env` and configure Supabase Postgres, a random server secret and administrator credentials. Use the database/session-pooler URL, not a browser anon key.
2. If Supabase is unavailable, configure an actual MySQL database and explicitly select `DATABASE_MODE=mysql`. The application never switches databases silently. On the verified local machine MySQL runs at `127.0.0.1:3307`; its generated credentials are private.
3. Install and start:

```powershell
cd backend
python -m pip install -r requirements.txt
python -m alembic upgrade head
python -m fleet.cli bootstrap
python -m uvicorn app.main:app --host 127.0.0.1 --port 8000
```

In a second terminal:

```powershell
cd frontend
npm ci
npm run dev
```

For the **React Native** app:

```powershell
cd mobile
npm ci
# Configure EXPO_PUBLIC_API_URL using mobile/.env.example.
npm start
```

A physical phone must use a reachable LAN/HTTPS API address, not that phone's localhost. `npm run export` compiles Android, iOS and web bundles. Building signed APK/IPA installers requires Android/iOS build tools and college-owned signing configuration; source/bundles alone are not an installed device test.

## What is implemented

- Genuine server sessions; eight roles; object/period access; restricted driver contact details; encrypted TOTP MFA enrolment; no client-side role impersonation or fake login fallback.
- UUID vehicle identities, preserved leading zeros, dated driver/route/device history, master-data CRUD, validation, search, pagination, archive/restore, atomic CSV imports and exports.
- Correspondent dashboard and eight-tab bus details with reporting dates retained in links; daily summaries, charts, map adapter, source explanations, data confidence, refill planning and month-close checklist.
- Decimal backend calculations, explicit missing-vs-zero semantics, mileage versions, midnight portions, GPS replay/gap/jump checks, stock boundaries, corrections/reversals and independently posted fuel.
- Private evidence uploads/downloads and S3-compatible adapter; audit records; review-case lifecycle and authorised financial decisions; frozen/checksummed report revisions with separate preparation, verification and signature stages; PDF/CSV exports.
- Celery/Redis scheduled calculations, provider backfills and report jobs. An explicit development scheduler supports local operation without Redis.
- React Native fleet/detail screens, admin records/forms, evidence upload, refill capture/offline drafts/sync, permitted workflow actions and report sharing.
- The attached visual brief: exact navy/teal/ivory/amber token architecture, aurora/glass animated login, Framer Motion role previews, vector parked-bus schematic, three-sheet ledger, dual-tank calculator, diagnostic pipeline and governance/field-roadmap screens. Reduced-motion preferences are respected. Example numbers are clearly labelled and never stored as college records.

## Validation

Run the isolated calculation/API tests:

```powershell
cd backend
python -m pytest tests_command -q
```

On this configured machine `python scripts/mysql-tests.py` runs the suite against a separate disposable `college_fleet_test` database, including real concurrent approval checks. It never drops the operational database.

```powershell
cd frontend
npm run build
cd ../mobile
npm run typecheck
npm run export
```

The explicit HTTP journey and three printable sample reports were exercised in a separate **synthetic QA database**, containing 30 demonstration buses and at least 60 days of source history. Results and limitations are in [verification](docs/verification.md). No live Supabase credentials, authorised vendor contract or physical native device were provided; those integrations are not claimed as validated.

## Optional synthetic demonstration

Use a **separate, empty** database. Bootstrap its admin, set a private `DEMO_PASSWORD` of at least 12 characters, then:

```text
python -m fleet.cli demo --synthetic-only
```

This command creates exactly 30 labelled synthetic buses, six synthetic routes, driver history/substitution, 60 days of GPS/service/stock/fuel data, Sunday holidays, partial fills, outages and review cases. Synthetic role accounts are `data_admin@demo.example.com`, `correspondent@demo.example.com`, `transport_verifier@demo.example.com`, `fueller@demo.example.com`, `driver@demo.example.com`, `accounts@demo.example.com` and `auditor@demo.example.com`; use the password you supplied. No automatic seed runs on login or server start.

## Documentation

- [Operator guide](docs/operator-guide.md)
- [Configuration, deployment, security, backup and restore](docs/deployment-command.md)
- [API reference](docs/api-command.md) and live `/docs`
- [Calculation formulas, quality and regression examples](docs/calculations.md)
- [GPS adapter contract and hardware/pilot checklist](docs/provider-adapter.md)
- [Checks performed and remaining integration work](docs/verification.md)

The old frontend is retained in `frontend/legacy-ui/`; the new API deliberately does not mount legacy auth/data endpoints. Existing legacy database files are preserved. Import historical college data only after source review and reconciliation.

Real deployment and field accuracy require authorised vendor validation, secure hosting, backups/restores, native device tests and supervised pilot evidence. The proposed 12-week UI roadmap is not a claim of completed field work.
