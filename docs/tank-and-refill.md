# Daily GPS, tank diesel and refill recommendations

The dashboard and each bus's **Stock & mileage** tab show:

- Accepted GPS km for the selected IST reporting period (choose Today or Yesterday for daily km).
- Diesel remaining, its measurement/estimate time and quality.
- The bus's operating target and recommended top-up in litres.
- The last posted refill in that period: occurrence time, before-stock, delivered litres and after-stock.

Click a number to inspect its backend formula, anchor, source IDs, mileage versions and dates. Fleet totals state how many buses contribute. Unknown tank values never become zero. The React Native overview also shows tank and top-up figures, with the refill snapshot in Stock & mileage.

## Operator workflow

1. An administrator creates the bus with separate physical capacity, safe fill limit and operating target, then assigns a GPS device and approved mileage model.
2. Provider events arrive through the authorised adapter/signed webhook. Accepted segments update daily km and expected engine use. The scheduled daily job rebuilds recent dates; late data revises summaries and flags frozen reports for revision.
3. A fueller records actual delivered litres and invoice evidence, with before/after readings when available. Identify measured versus estimated readings accurately. A measured post-fill reading must be stable and corroborated during independent verification.
4. A different authorised reviewer verifies and posts the refill. Draft/submitted/reversed events are excluded from posted refill totals and refill anchors.
5. Open the dashboard for the relevant date. The recommendation is `max(0, operating target − usable stock)`. It is a recommendation to the operating target, not permission to exceed the safe fill limit.

## Calculation version cfc-1.1.0

GPS measures position and supports distance calculations; it does not measure tank litres. Tank balance starts from an independently verified stable tank reading or independently posted refill snapshot. A refill with only a before-reading can anchor `before + delivered`, explicitly estimated. A post-reading supersedes that arithmetic when supplied and verified.

`Estimated balance = anchor + later posted deliveries + approved transfers in − approved transfers out − GPS-modelled engine use`

The anchor's own delivery is not added twice. Same-time ambiguous reading/refill ordering blocks a balance. Engine use applies the mileage version and route assignment effective within each segment; separate idling applies only when excluded by the approved mileage model.

Intraday estimates require continuous accepted GPS segments from the anchor, including correct device mappings, no long gaps/jumps and approved mileage. A fresh snapshot may be displayed at its own timestamp for up to ten minutes without tracking; it is not presented as a current sensor value. A GPS estimate is dated at its last accepted fix and expires after the configured GPS gap threshold. Raw continuous estimation is limited to seven days. Completed midnight-to-midnight estimates can use every intervening daily summary only when each has known consumption and 100% approved service-window coverage; movement outside scheduled windows remains a model limitation requiring supervised validation. Missing history, stale telemetry, missing models or an implausible negative/over-capacity result produce unknown stock and no exact recommendation.

Actual independently verified boundary readings remain necessary for stock-adjusted disappearance and residuals. Recommendations do not imply a discrepancy or theft finding. Historical target changes are not reconstructed: refill previews use the current configured operating target. Frozen reports retain their original snapshot.

## API additions

Existing authenticated `/api/v2/dashboard`, `/api/v2/buses/{vehicleId}/detail` and `/api/v2/explain/{metric}` responses include `stock_as_of`, `stock_reason`, `stock_anchor`, `stock_source_ids` and `latest_refill`. Existing `stock_l`, `stock_quality`, `top_up_l` and `operating_target_l` remain compatible. Fleet `metrics`/`contributors` additionally include `stock_l` and `top_up_l`. `stock_l` is now an explainable metric. There is no new public telemetry endpoint, credential or database migration.

## Synthetic verification

`backend/tests_command/test_tank_dashboard.py` covers 80 km at 4 km/L, estimated balance 18 L / top-up 82 L, full and partial fills, pre-only estimates, zero versus unknown, draft exclusion, reversal, duplicate/out-of-order GPS, gaps, stale coverage, effective mileage changes, exclusive midnight boundaries, dashboard/bus agreement and formula sources. Existing suites cover permissions, concurrent approval, midnight allocation, transfers, late revisions and exports.

For a disposable visual demo, provision an empty localhost MySQL database ending `_demo` with its own non-root user. Put `DATABASE_MODE=mysql`, `MYSQL_DATABASE_URL`, `SECRET_KEY`, `BOOTSTRAP_PASSWORD`, `MFA_ENABLED=false`, `COOKIE_SECURE=false` and localhost QA `CORS_ORIGINS` in a private JSON config outside source control. Run:

```powershell
python scripts/tank-demo.py --config .runtime/tank-demo-env.json
python scripts/serve-tank-demo.py --config .runtime/tank-demo-env.json
# In a second terminal:
cd frontend
$env:API_INTERNAL_URL='http://127.0.0.1:8001'
$env:CFC_DIST_DIR='.cfc-next-tank'
npm run dev -- --port 3001
```

Sign in as `correspondent@tank-demo.example.com` with the config's private `BOOTSTRAP_PASSWORD`, then choose Yesterday. The seed refuses existing records and non-local/non-demo databases. QA-001 shows 80 km, estimated 18 L and an 82 L top-up; QA-002 shows a posted 50 L partial fill (18 → 68 L) and a 32 L top-up; QA-003 has unknown inputs. No synthetic rows are added to production.

Real GPS forwarding, calibration and stable tank readings still require authorised hardware/vendor validation and a supervised pilot.

Observed checks on 27 October 2026: 83 tests passed / one MySQL-only concurrency test skipped in the SQLite suite; the MySQL suite passed 82 tests, followed by all 12 tank regressions on MySQL (including the two added boundary/explanation checks). Web production build, native TypeScript and Android/iOS/web Expo export passed. Desktop and 390×844 responsive web screens were inspected. A single uncached local MySQL dashboard calculation for 33 synthetic buses across 30 days took 3.556 seconds; this is not a concurrent production load test. Production deployment `dpl_Ds6jtofQLDWP4m3VAQraN7outeRA` was READY, and authenticated dashboard/stock explanations and database health returned 200; anonymous dashboard returned 401.

## Km and diesel shortage (calculation cfc-1.2.0)

The dashboard, fleet columns, bus Overview, native overview and new report snapshots include these backend figures:

- **Km shortage** = max(0, stock-adjusted disappearance × one approved km/L standard − accepted GPS km). This requires one applicable mileage model including idling; it remains unknown across multiple models or separate idling models.
- **Diesel shortage · review** = max(0, stock-adjusted disappearance − interval-based expected engine use). Each interval uses its effective mileage model.
- **Route km shortage** = max(0, approved planned km − accepted GPS km), independently of the fuel comparison.

Fuel shortage requires verified, stable opening and closing readings at the exact reporting boundaries, complete expected-use inputs and known GPS coverage. Every operating day must have at least 90% approved-window coverage, with no detected gaps, impossible jumps or poor-accuracy interruptions. Missing dates/data yield unknown, not zero. Boundary uncertainty is displayed; a variance within that uncertainty is labelled accordingly. Km/L figures remain review signals and do not prove loss or authorise financial decisions.

Example: equal 40 L opening/closing boundaries, 200 L posted deliveries, 720 GPS km and a 4 km/L standard give 200 L accounted disappearance, 800 km fuel range, 80 km shortage and 20 L review variance. A separate approved 800 km plan also gives an 80 km route shortfall. Kilometres and litres express the same fuel variance in different units and must not be charged twice. Fleet totals add each bus's positive shortage; other buses' surplus cannot offset it. Delivered litres without reliable boundary stock never become fuel consumed.

API keys: `km_shortage_km`, `diesel_shortage_l`, `route_shortage_km`, `reconciled_range_km`, `shortage_status`, with formula/source access through the existing authenticated explain API. Dashboard metrics and contributor counts include the three shortage quantities. No migration is needed: these values are calculated from persisted, verified source records. Frozen existing snapshots remain unchanged; export fields missing in older snapshots are unavailable.

For the local synthetic QA database created above, run `python scripts/shortage-demo.py --config .runtime/tank-demo-env.json`. It adds QA-004 once, with 481 synthetic provider points, the 720 km / 200 L example, verified boundaries and an explainable review case. It refuses remote/production targets. The `test_shortages.py` suite checks the regression examples, missing/partial inputs, multiple models, measurement uncertainty, fleet aggregation, bus/dashboard consistency, explanations and authorised PDF/CSV exports.

Shortage release validation on 27 October 2026: all 97 backend tests passed on the separate MySQL test database. The 13 shortage regressions also passed on SQLite after the final report layout adjustment. Web production build, native TypeScript and Android/iOS/web export passed. Desktop/mobile screens, filter-preserving bus navigation, and the three-page synthetic monthly PDF were visually inspected. No synthetic operational data was committed to Supabase.
