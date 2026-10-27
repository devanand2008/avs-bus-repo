# College Fleet Command operator guide

## First setup: genuine records only

Open `http://localhost:3000`. The generated local administrator credentials are in the ignored `.runtime/local-access.txt`. No buses, drivers, fuel records or telemetry are seeded into the operational database. Never email or publish that credentials file.

The new aurora login has four **responsibility preview** tabs. Selecting a tab does not impersonate a user or grant privileges. Your authenticated server account determines access. MFA users supply a password and current authenticator code. The application-server status is a real health check; it does not certify a GPS vendor connection.

1. System Admin creates named accounts in **People & access**. Create a Data Admin, Fueller, Transport Verifier, Correspondent, Accounts and individual Driver accounts. Link Driver accounts to driver profiles. Auditor is read-only.
2. Data Admin opens **Fleet records → Buses**. Add the visible bus number as text, registration, specifications and depot. `007` remains `007`; links use a permanent UUID.
3. Add driver profiles and dated driver/route assignments. To substitute a driver, close the prior assignment's exclusive end time and create the successor. Referenced route versions are immutable; create a new version code for a change.
4. Create and independently approve routes, surveys and mileage standards. All three survey measurements must use the same scope. Upload evidence privately and paste its ID into the appropriate draft. Enter starting/ending odometer readings as documented in the form.
5. Schedule actual service dates in **Service calendar**. Include holidays (zero trips), extra trips, detours and workshop service. Supply approved start/end service windows in JSON, e.g. `[{"start":"2026-10-22T07:00:00+05:30","end":"2026-10-22T09:00:00+05:30"}]`. Coverage is unknown without a valid denominator; it is never inferred from guessed driving speed.
6. Configure dated GPS mappings. A server administrator configures the authorised adapter and credentials. Use the separate **Manual distance fallback** workflow when provider data is missing; it never becomes GPS distance.
7. Capture opening fuel stock as a stable, evidence-backed tank reading and have an independent verifier approve it. A measured closing reading exactly at an IST midnight is also the next day's opening boundary.

## Refill desk

Identify the real bus → capture pre-fill stock and quality → record delivered litres, supplier, unique invoice and occurrence time → attach evidence → obtain independent authorisation for any emergency override → submit → independent verifier verifies/posts → Accounts matches priced invoices. Drivers acknowledge only fills during their historical assignment.

The physical capacity, safe limit and operating target are different fields. Override approval cannot authorise a physically impossible fill. A draft has no ledger impact. Posted records require an independently authorised reversal and a linked correction; they cannot be silently edited. Distinct posted, non-reversed records determine the refill count.

PWA drafts explicitly saved while offline remain on that browser/device and display their unsynchronised state. React Native provides an explicit device-only draft switch and a sync action. Request IDs prevent duplicate posting. Final authorisation/verification requires the server. Upload evidence after reconnecting if it was unavailable offline. Clear device drafts after successful sync, and secure shared phones with device access controls.

## Correspondent journey

Choose Today, Yesterday, This/Last Week, This/Last Month or a Custom Range. Display dates are inclusive; the API uses `[start, end)` in Asia/Kolkata. Week starts are configurable and default to Monday. Click a bus number to open `/buses/<vehicle UUID>`; date and fleet search/status filters travel in the URL.

The eight detail tabs cover overview, GPS/trips, distance comparison, fuel ledger, stock/mileage, assignments, cases and reports/audit. Archived buses remain available by their permanent link or the archived-record filter.

Click important metrics for formula, version, quality, rounding and source IDs. Delivered diesel, estimated engine use and stock disappearance are independent quantities. Missing values show a dash/Unknown. Partial fleet metrics list contributing buses.

Use the **Prioritised review queue** and case workspace. Cases progress New → Acknowledged/Investigating → Explained or Confirmed discrepancy → Closed; reopening returns to Investigating. Explanations are retained separately. A financial case amount needs an independent prior investigation and Correspondent approval. Accounts matches the approved decision. No automatic deductions occur.

## Three-sheet ledger and examples

**College records** is the default ledger mode and uses persisted records for the selected bus and reporting dates. **Illustrative calculation lab** is an explicit educational mode using server-calculated specification examples; it never writes fleet records. The dual-tank simulator, login illustration and diagnostic plots are clearly labelled schematics/examples. An illustrative `B01` is not a stored vehicle or live telemetry.

The Tanglish note toggle provides contextual operating explanations. English/Tamil navigation and common operational labels are supported; evidence and free text remain as entered.

## Month close and exports

Review exact opening/closing stock, pending fuel, invoice prices, transfers, incomplete GPS and unresolved cases. Resolve the checklist, or explicitly choose provisional close. A verifier/Correspondent freezes a report; a different Correspondent can sign it. PDF/CSV downloads use the same frozen payload and hash.

Late source data flags a frozen report for a successor revision; it does not overwrite its payload. Signatures are application attestations (name, server time, version and audit history), not government-qualified cryptographic signatures.

Report types: GPS Weekly, Weekly Fuel and Monthly. Calendar totals remain separate from per-filling reconciliation. Per-filling comparisons stay unknown unless exact interval data is available. Chairman/Corres/deduction-field mapping stays unconfirmed until explicitly configured in **College & security**; cases have no five-slot limit.

## React Native

Run the Expo app in `mobile/` using the same API. Use a reachable LAN/HTTPS API URL on a physical device; `localhost` on a phone means that phone. Native session tokens use SecureStore; web sessions use HttpOnly cookies. Pull to refresh, choose reporting dates, open any bus, upload evidence, capture/sync drafts, acknowledge/verify permitted records and download/share report files. Full advanced master-data editing and CSV import remain available in the responsive web app.

## Recovery

If the database connection fails, the UI shows an error and no writes are redirected to another database. Check `.env`, selected database mode, migrations and `/api/health`. Do not load demo seeds to conceal missing data. See deployment, calculations and hardware documentation before field operation.
