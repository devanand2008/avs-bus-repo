# Verification record — 23 October 2026

Logo update: the supplied artwork now appears on web login/navigation/loading/MFA/offline screens, web install/tab icons, React Native login/header/loading and configured launcher/splash assets, plus PDF covers and page footers. Web production build, mobile TypeScript and Android/iOS/web bundle exports passed after this update. The report API regression passed; all three report variants rendered with an image on each of their three pages. Native launcher/splash appearance still requires a new signed device build. Branding does not modify operational records or frozen calculation payloads.

This records completed local checks, not a production or field acceptance certificate. Operational configuration uses MySQL explicitly because authorised Supabase connection credentials were not supplied. Startup bootstraps an administrator/settings only; synthetic fleet data exists in a separate QA database.

## Completed checks

| Check | Actual result |
|---|---|
| Full backend suite on MySQL 8.4.13 | **64 passed** in 235.42 seconds, including concurrent posting and MFA enrolment. Five non-fatal serializer warnings. |
| Isolated in-memory suite | **63 passed, 1 skipped**; the real concurrency case is exercised on MySQL. |
| HTTP admin → telemetry → fuel → Correspondent journey | Passed against separate QA services. Selected-month fleet/detail/export values matched. |
| Reports | GPS weekly, fuel weekly and monthly PDFs/CSVs exported; immutable hashes and independent preparation/verification/signature checked. Nine PDF pages rendered; representative layout pages visually inspected. |
| Web | Production compilation and TypeScript passed; desktop/phone login, monthly dashboard, UUID bus navigation, retained date filters, ledger examples and refill layout inspected in-browser. |
| React Native | TypeScript passed; Expo exported Android/iOS Hermes and web bundles. No installed physical-device test or signed APK/IPA is claimed. |
| Windows launcher | Six failure/readiness unit checks; cold MySQL/API/web/scheduler startup and repeated BAT launch passed; no fleet seeded. |
| Dependency audits | Web npm audit and backend requirements pip-audit: zero known reported vulnerabilities at verification. Native toolchain still reports upstream braces/node-forge/sprintf-js advisories; do not treat export success as security certification. |

A strict MySQL test caught encrypted TOTP ciphertext exceeding the original column length. The model and migration `0004_mfa_ciphertext.py` now allow the encrypted value, and the full MySQL suite passed after that fix.

The suite covers all requested numeric regression examples, missing versus zero, scope matching, midnight and mileage-version allocation, date additivity, stock carry-forward, historical assignments, replay/duplicates, GPS quality/gaps, late frozen-report revisions, private evidence access, role and object permissions, self-approval, idempotency/concurrent posting, immutable corrections, independent financial decisions and exports.

## Measured dashboard conditions

Windows 10 build 26300; Python 3.11.9; local MySQL 8.4.13; one API worker; one client; concurrent local build/test activity. The QA database held **33 vehicles** (30 seeded buses plus three distinct journey-test buses), **67,050 GPS events**, **1,899 daily summaries** and **560 fuel events**, with at least 60 days of history. Three selected-month requests took **1.079, 1.749 and 1.382 seconds**, median **1.382 seconds**, each returning 471,559 bytes. This limited local benchmark is not a scalability claim. Load testing, payload reduction, query profiling and capacity planning remain deployment work.

Machine-readable results: `output/checks/verification.json`. UI captures and PDF page renders are under `output/checks/`; synthetic sample exports are under `output/pdf/`. They contain labelled synthetic QA records, not college operational evidence.

## Remaining external acceptance work

- Connect and validate the actual Supabase project (TLS, RLS, migrations, backups, restore and least-privilege role). Supabase adapter configuration is implemented but untested against a live project.
- Obtain an authorised vendor API contract and validate device identity, units, cadence, pagination, signatures, rate limits, backfills and delayed fixes against retained vendor evidence. Current demo/template adapters do not establish real tracker accuracy.
- Validate any tank hardware against each tank, calibration version, stable windows, slosh/slope/motion and supervised measured deliveries. Maintenance suggestions and review flags do not diagnose faults or identify misconduct.
- Exercise Docker/Redis/Celery services and S3-compatible private evidence on the chosen deployment; Docker is unavailable on this local machine. The local development scheduler was started; scheduled clock-time execution is not a completed production soak test.
- Build college-signed native installers and test Android/iOS devices, SecureStore, camera/document picking, offline drafts, reconnection, report sharing and MFA. Enrol privileged MFA through the web security flow before native sign-in; native enrolment is not implemented.
- Complete HTTPS/reverse-proxy controls, malware scanning/quarantine, rate limiting, independent backups and an actual restore drill. Common English/Tamil labels and Tanglish help are present; full reviewed Tamil translation of all explanatory text remains localisation work.
- Supervise a 3–5 bus pilot, compare paper/digital records, approve legacy Chairman/Corres/deduction-field mappings and conduct a real month close before fleet-wide adoption.

The 12-week roadmap screen is a proposed field plan, not evidence that twelve weeks of validation have occurred.


## Additional review and fixes (22–23 October)

- Centralised fuel validation for creation, draft edits and final posting. Invalid post-stock, unknown-quality readings, invalid correction links and capacity changes are rejected consistently. Non-admin fuellers cannot submit another creator's draft.
- Malformed GeoJSON and nonnumeric/nonfinite rule thresholds return validation errors. Survey readings reject nonfinite distances. Case explanations enforce optimistic concurrency.
- GPS consumption splits at route/driver assignment boundaries. Derived trip IDs include provider/device identity. Calculation version is now cfc-1.0.1; rebuilds version affected summaries and flag frozen reports.
- Historical changes rebuild beyond the first 366 days and invalidate affected frozen reports. Approved future plans receive a daily summary; future service dates do not create premature outage cases.
- Stock estimates require all intervening daily summaries, include approved transfers and deliveries, and retain unknown rather than clamping an impossible negative balance to zero. Prior stock boundaries outside the selected reporting period are included.
- Drivers cannot list unrelated evidence metadata or transfers outside their assignment interval. Driver route listings use their own assignments.
- Case workspace pagination, fuel pagination reset after date changes, cleared case amount between decisions, native full-month default, native date-filtered fuel/case lists, retained offline-sync errors and Android modal close handling corrected.
- Small positive values retain three decimal places instead of displaying zero. Long bus numbers wrap within their badge and heading. Desktop 1440px and phone 390px bus views inspected; phone page width equals viewport width. All eight detail tabs and retained month/search filters exercised.
- Six launcher unit checks pass (wrong app, unavailable database, malformed health response, healthy service, child exit and readiness timeout). Actual cold database/API/web/scheduler startup and warm repeated BAT launch passed. The launcher uses an OS lock against concurrent startup and opens the browser only after readiness.

Artifacts: `output/checks/mysql-final.txt`, `memory-final.txt`, `verification.json`, `review-desktop-bus.png`, `review-mobile-bus.png` and `review-pdf-contact-sheet.png`. Synthetic QA stays separate from the operational database. These checks cover the implemented workflows; they do not prove every possible production/device condition is bug-free.


## Cloud deployment, 27 October 2026

Web and FastAPI are deployed together at https://college-fleet-command.vercel.app. Supabase is now verified, using the explicitly authorised private college_fleet schema in project zzrtilfronngzpuiymzi and a dedicated role. Migrations through 0005_evidence are applied. All 24 fleet tables have RLS; the role cannot read existing public application tables. No buses or operational sample data were committed.

The updated serverless suite passed 67 tests (one MySQL-only skip), including private database-backed evidence and platform upload limits. Live HTTPS login/cookie, MFA gating, health, configuration and protected daily rebuild checks passed. A PostgreSQL ORM/evidence/calculation check passed in a rolled-back transaction. See docs/vercel-deployment.md and output/checks/vercel-live.json for exact scope and remaining integrations. Enrol privileged MFA on first sign-in. Native signed installers and persistent Celery/Redis workers are separate from this Vercel web/API deployment.


## Authenticator requirement removed, 27 October 2026

The user requested removal of authentication after being blocked by the authenticator-code flow. The implemented scope removes the authenticator requirement while retaining administrator email/password login. Production MFA_ENABLED=false and MFA_REQUIRED=false disable code checks, forced enrolment and enrolment/confirmation actions. Web and native login fields honour mfa_available=false. Password validation, secure sessions and role/object access continue to apply. The full backend suite passed 71 tests with one MySQL-specific skip; web/native TypeScript passed.
