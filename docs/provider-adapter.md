# Authorised GPS adapter and hardware checklist

`backend/fleet/providers.py` defines inventory, historical positions, live-update capability, health and backfill. `DemoProvider` is deterministic, clearly synthetic and never enabled automatically. `ConfiguredProvider` is a real HTTP client template, **not a claim of compatibility with an unidentified vendor**.

Template vendor contract:

- `GET /devices`: authorised device inventory.
- `GET /positions?from=<UTC>&to=<UTC>&cursor=<cursor>`: `{items:[event...],next_cursor:null}`.
- `GET /health`: connection/account health.
- Optional forwarding to `/api/v2/gps/webhook` with lowercase hexadecimal HMAC-SHA256 in `X-GPS-Signature`, calculated over the exact request body using `GPS_WEBHOOK_SECRET`.

Each event includes provider, device ID, event ID, fix timestamp with timezone, latitude/longitude and optional source speed/unit (`kmh`, `mph`, `mps`), ignition, accuracy metres and odometer km. The server supplies receive time and stores source/raw values. Map devices by effective fix-time intervals before import. Unmapped events are counted and rejected from distance calculations; retain/retry vendor source batches after correcting mappings.

Backfill paginates and detects repeated cursors. HTTP 429/5xx retries use bounded backoff/Retry-After; Celery retries failed jobs. Final vendor implementations must define rate limits, pagination, units, ignition validity, source IDs and retention guarantees. Credentials stay in backend environment/secrets and never enter React/React Native builds.

Before field use:

1. Obtain written authorisation and the vendor's documented API/stream contract; verify existing tracker model, SIM ownership and historical access.
2. Validate GPS units, fix/receive time semantics, timezone, cadence, accuracy, ignition behaviour, duplicates, delayed events and known outages against supervised journeys.
3. Verify every effective device-to-bus mapping; test a supervised tracker swap and odometer reset.
4. Check route geometries, survey scopes, holidays, authorised detours and planned service windows with transport staff.
5. Reuse the existing tracker and fuel-desk phone first. Purchase no sensor based solely on this application's diagrams.
6. Optional tank sensors require a compatible gateway, tank-specific calibration curve, mounting review, supervised dip measurements and stable pre/post windows. Record slope, movement, slosh, temperature/fault behaviours and uncertainty. Sensor calibration versions retain approvers.
7. Optional pump integration requires authorised dispenser transaction IDs, invoice references, units and independent delivery evidence. Keep deliveries separate from estimated engine use.
8. Pilot 3–5 buses with parallel paper/digital checks and named maker/checker/approver roles. Verify data completeness, stock carry-over, exports and backup restore before expanding.
9. Agree retention and incident procedures; protect driver numbers and private evidence. No student/passenger information is collected by the application.

The UI's 12-week roadmap is a proposed supervised plan, not a dated commitment or evidence of completed vendor validation. Native Android/iOS device testing, installation signing, hardware compatibility and field accuracy require actual authorised equipment and owner sign-off.
