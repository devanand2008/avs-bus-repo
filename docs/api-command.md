# API contract

Live authoritative OpenAPI: `/openapi.json`; interactive docs: `/docs`. All below are relative to `/api/v2`. JSON decimals are strings; km, L, km/L, INR and UTC timestamps are explicit. Date filters use Asia/Kolkata half-open `[start,end)`; maximum 366 days per request.

| Area | Endpoints |
|---|---|
| Configuration | `GET /public/config`, authenticated `GET/PUT /settings?version=&reason=` |
| Auth | `POST /auth/login`, `GET /auth/me`, `POST /auth/logout`, `POST /auth/mfa/enrol`, form `POST /auth/mfa/confirm` |
| Users | System-admin `GET/POST /users`, `POST /users/{id}/disable` toggles access and revokes sessions |
| Dashboard | `GET /dashboard?start=&end=&search=&status=&include_archived=` |
| Bus histories | `GET /buses/{vehicleId}/detail?start=&end=`, `/buses/{vehicleId}/gps?start=&end=` |
| Sources | `GET /explain/{metric}?start=&end=&vehicle_id=`; full source identifiers fetched on demand |
| CRUD | `GET/POST /resources/{kind}`, `PUT /resources/{kind}/{id}?version=&reason=`, `POST /resources/{kind}/{id}/archive`, `POST .../approve` |
| CSV | `GET /resources/{kind}/export`, multipart `POST /resources/{kind}/import`; all-or-nothing validation, 1–1,000 rows, 2 MB |
| Fuel | `POST /fuel`, `PUT /fuel/{id}?version=`, `POST /fuel/{id}/{authorise,submit,verify,acknowledge,match-invoice,reverse}` |
| Evidence | multipart `POST /evidence` with vehicle_id/file; `GET /evidence/{id}/download` verifies scope/hash |
| GPS | `POST /gps/ingest` batch 1–1,000; signed `POST /gps/webhook`; `GET /gps/health`; `POST /gps/backfill?start=&end=` |
| Calculation | `POST /calculations/rebuild?start=&end=&vehicle_id=`, `GET /planner?days=7` |
| Mileage | `POST /mileage/{id}/end-version?effective_to=` plus version/reason body |
| Cases | `POST /cases/{id}/decision`, `/explanation`, `/match-accounts` |
| Month close | `GET /month-close/checklist?start=&end=` |
| Reports | `POST /reports/freeze?start=&end=&kind=&vehicle_id=&provisional=&supersedes_id=`, `POST /reports/{id}/verify`, `POST .../sign`, `GET .../export?format=pdf|csv` |
| Queue | `POST /reports/queue?...`, authorised owner `GET /jobs/{id}` |
| Educational tools | `GET /public/calculation-examples`, authenticated `GET /tools/refill-preview?target=&stock=&capacity=&quality=`; never persist fleet records |

Resource kinds: vehicles, drivers, routes, assignments, devices, surveys, mileage, plans, tank-readings, calibrations, transfers, manual-trips, fuel, cases, reports, approvals, audit. Not every kind permits generic writes; fuel/cases/reports/audit use dedicated workflows. Listing is paginated (`page`, `page_size` up to 200), searchable and supports archived master records. Fuel/cases accept start/end filtering. No DELETE endpoint erases approved history.

Decision bodies include `{version:<current integer>,reason:<nonempty explanation>}`. Stale/concurrent changes return 409. Unique constraints and fuel idempotency keys protect posting. Reusing a key with different content returns 409. Independently reviewed records cannot be modified through generic CRUD.

Web login returns a user and HttpOnly cookie. Native requests send `X-Client: native` during login to receive an access token and then `Authorization: Bearer ...`. Supplying client role claims never grants a role. Driver access is checked against historical vehicle assignment intervals; driver phone/licence fields are restricted to admins. Reports/exports/evidence check roles and object scope server-side.

Reports have distinct preparation, independent Transport Verifier review and Correspondent signature stages. A creator cannot verify/sign their report; a report verifier cannot also supply its Correspondent signature. Late source changes prevent new signatures until a successor revision is frozen. Snapshots retain original data and checksum.

Common response codes: 401 no/expired session; 403 role, scope or self-approval violation; 409 uniqueness/concurrency/immutable-record conflict; 422 validation/quality gate; 503 database/queue/vendor unavailable. Error responses do not expose database credentials. The application never silently substitutes demo data.
