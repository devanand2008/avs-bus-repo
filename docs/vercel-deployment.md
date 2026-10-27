# Vercel deployment

This repository deploys the Next.js web app and FastAPI API together using Vercel Services (Beta). `vercel.json` routes `/api/*` to the API service and all other paths to the web service. Vercel handles TLS. Local Windows launchers and the React Native source remain usable separately.

## Selected destination

- Project: `college-fleet-command`
- Project ID: `prj_7XyJGb1rR4hd0AcXuReI0WuMRlzy`
- Account: `team_LGnAbOq993hXXmq626M0R2MV`
- Production URL: https://college-fleet-command.vercel.app
- Additional alias: `college-fleet-command-devanands2008-7426s-projects.vercel.app`
- Root directory: repository root; framework: Services.

Only the reviewed source manifest from `scripts/vercel-source.py` is uploaded through the authenticated Vercel connection. It excludes `.env` files, `.runtime`, uploaded evidence, databases, local reports, native signing information and development builds. No Git commit exists in the supplied local repository, so this is a source upload deployment rather than a Git release.

## Required production settings

Set these on the dedicated Vercel project, never as `NEXT_PUBLIC_*` variables:

| Variable | Value |
|---|---|
| DATABASE_MODE | `supabase` |
| DATABASE_SCHEMA | `college_fleet` |
| DATABASE_URL | Supabase transaction pooler URL with `sslmode=require` (port 6543); obtain the exact host from the project's Connect dialog |
| ENVIRONMENT | `production` |
| SERVERLESS | `true` |
| SECRET_KEY | Dedicated random secret, at least 32 characters |
| CRON_SECRET | Dedicated random scheduler authentication secret |
| COOKIE_SECURE | `true` |
| MFA_REQUIRED | `false` |
| MFA_ENABLED | `false` |
| EVIDENCE_STORAGE | `database` for initial private database-backed evidence, or configure the existing private S3 adapter |
| CORS_ORIGINS | Exact production HTTPS origin(s), comma-separated |

The Vercel deployment hostname and project production hostname are also accepted as exact origins through Vercel's injected environment variables. No wildcard `*.vercel.app` origin is trusted.

The current deployment uses the user-authorised private `college_fleet` schema in Supabase project `zzrtilfronngzpuiymzi` (region ap-southeast-1), with dedicated `college_fleet_app` login. It has no table permissions in the existing public application schema. A separate project can be used later. Initialise migrations with a session-pooler/direct connection, then set the transaction-pooler connection for runtime. The serverless SQLAlchemy engine uses NullPool. Do not point Vercel at a loopback/local MySQL URL. No database failover or fake data is introduced on missing configuration: the deployed page displays a configuration-pending message, and data endpoints return 503.

Run `python scripts/setup-cloud-database.py --config .runtime/cloud-database.json` after placing the dedicated connection and bootstrap details in that private JSON file. The script refuses development/test/local targets and refuses a populated database without the fleet schema. It applies migrations, bootstraps settings/admin only, enables RLS on every `cfc_*` table and revokes public Data API access. API permissions remain authoritative; the trusted backend database role owns its tables. Do not enable permissive anonymous Supabase policies.

## Evidence and scheduled calculations

With `EVIDENCE_STORAGE=database`, evidence bytes are committed transactionally with their metadata in `cfc_evidence_content`. They are never exposed through resource listings and retain SHA-256 verification, role/object checks and private download audit. Include this table in backups. Serverless uploads are capped at 3 MiB to stay below Vercel's request-body ceiling. The private S3-compatible adapter remains available for larger storage needs; migrate existing bytes deliberately before changing stores.

Vercel Cron invokes `/api/cron/daily` at 19:45 UTC (01:15 Asia/Kolkata) and authenticates using `CRON_SECRET`. This recalculates the last three operational days. Scheduled execution is production-only. Provider webhook forwarding supplies live GPS updates when a vendor is configured. Real vendor credentials, rate limits and cadence still need validation.

Celery/Redis queue workers and continuous provider polling are separate processes and do not run as persistent Vercel Functions. The current web workflows use synchronous report freeze/export and calculation endpoints; Celery queue endpoints require a separately configured Redis broker/worker. Native APK/IPA installers are built and distributed separately; Vercel hosts the web/API and can serve them as the native client's HTTPS API.

## Acceptance checks

After each source deployment reaches READY, test `/api/v2/public/deployment`, `/api/health`, staff sign-in/MFA, empty fleet, admin entry, private upload/download permissions and reporting period retention. Verify a privileged login through the actual deployed origin to catch cookie/origin issues. Test operational writes only with explicitly disposable test records or a separate QA deployment. Do not seed the college's production fleet to prove the dashboard works.

On 27 October 2026, the two-free-project quota prevented creating a third Supabase project. The user explicitly authorised an isolated fleet schema in “devanand2008's Project” instead. No existing public application tables were changed. Vercel team access was approved and the production deployment reached READY. Migrations through 0005_evidence were applied inside college_fleet; 24 fleet tables have RLS, one configured administrator exists and the fleet is empty. Cloud credentials are saved only in `.runtime/cloud-access.txt` and protected Vercel settings. Authenticator verification is disabled at the user's request; sign in with email and password.


## Verified production release (27 October 2026)

- Web `/` and `/login`: HTTP 200; logo, fonts and desktop/phone layouts render.
- `/api/health`: HTTP 200, `database=supabase`, `status=healthy`.
- Dedicated session and transaction pooler connections: authenticated as `college_fleet_app`.
- Admin sign-in and retained session: HTTP 200; Secure and HttpOnly cookie flags verified. Operational endpoints return 403 until privileged MFA enrolment is completed.
- Daily calculation endpoint: 401 without scheduler authentication; 200 with the configured scheduler secret. A real timed overnight run has not yet been observed.
- PostgreSQL ORM, private binary evidence and missing-vs-zero calculations: passed inside a transaction which was rolled back. Afterwards vehicle/evidence counts remain zero.
- Full lightweight backend suite after serverless changes: 67 passed, one MySQL-specific concurrency skip. Vercel's Linux Next.js/Python production build passed. The additional local MySQL rerun was unavailable because that local server did not become reachable; the earlier 64-test MySQL record remains historical, not a test of the new cloud schema.

Evidence: `output/checks/vercel-live.json`, `vercel-live-login-desktop.png` and `vercel-live-login-mobile.png`. The Supabase advisor's fleet findings are informational RLS-without-policy notices: browser Data API roles have no schema/table grants and receive default-deny RLS; the trusted table-owning backend role enforces fleet permissions. [Supabase explanation](https://supabase.com/docs/guides/database/database-linter?lint=0008_rls_enabled_no_policy). Existing public-schema view/function advisories belong to the other application and were not modified during this fleet deployment.


## Password-only sign-in update

At the user's request, production MFA_REQUIRED and MFA_ENABLED are false. Authenticator fields/enrolment prompts are hidden, enrolled accounts can sign in with their password, and MFA enrolment/confirmation endpoints are disabled. Administrator sign-in, password validation, secure sessions, private evidence permissions and role checks continue to apply. Existing encrypted MFA records are retained rather than deleted. Backend regression suite: 71 passed and one MySQL-only skip; web TypeScript passed.


## Obsolete authenticator screen removed

The forced MfaSetup component and its app-shell redirect were removed entirely after an already-open browser tab retained an older build. The PWA shell cache version was advanced and the service worker claims existing clients. Existing sign-in sessions open the dashboard after refreshing, without an authenticator enrolment screen.


## College branding update

The user confirmed AVS Engineering College as the replacement college name. The saved college settings were updated through the authorised settings API with an audit reason; the short label is AVSEC. Web fallback/header labels, browser metadata, backend/bootstrap defaults, environment examples and demo setup documentation use the new name. Mobile screens and newly prepared PDF/CSV reports read the saved college settings. Historical audit entries and frozen report payloads retain their original values.


## Full branding consistency audit

AVS Engineering College / AVSEC is confirmed in the live database college record, production COLLEGE_NAME/COLLEGE_SHORT_NAME, frontend/bootstrap defaults and new report output. Remaining former-name strings were removed from archived source screens/configuration. PWA install/offline labels and React Native app/web display labels now use AVS branding; native package IDs stay stable for updates. The backend health response reports college_name and college_short_name from the saved database record. Web/native type checks and four backend serverless checks passed; native Android/iOS/web bundles were rebuilt against the production API. Installed native binaries require the separate signed build/distribution workflow.
