# Authoritative calculations, units and quality

Implementation: `backend/fleet/calculations.py`, version `cfc-1.0.0`; rebuildable daily snapshots in `services.py`. Operational dates use Asia/Kolkata; stored timestamps are UTC, including explicit conversion for MySQL and SQLite. API timestamps must carry a timezone.

Litres, km/L and money use Decimal. Geodesic segment lengths use a spherical Earth haversine calculation (mean radius 6,371.0088 km), converted to Decimal. These are accepted straight geodesic fix-to-fix segments, not an assertion of measured road distance across unknown intervals. Rounding is ROUND_HALF_UP: generally 3 decimals for km/L quantities and 2 for INR. Fleet totals sum rounded daily values; raw source data is retained.

| Quantity | Formula / eligibility |
|---|---|
| Bike baseline | `(B1+B2+B3)/3`; three positive readings with one matching scope |
| Planned distance | Sum approved actual service-date trips × approved per-trip distance; holidays, extra, workshop and detour trips explicit |
| GPS distance | Sum accepted geodesic segments; no connection across the configured maximum gap or device mapping boundary |
| Deviation | Actual GPS km − approved planned km; positive means above plan |
| Expected engine use | Sum interval km / approved km/L effective during that interval; route-specific profiles take precedence |
| Idling | Separate L/hour only when the profile explicitly excludes idling, ignition is valid/on and accepted stationary time exists |
| Disappearance | Verified opening + posted deliveries + authorised transfers in − transfers out − verified closing |
| Eligible residual | Disappearance − complete expected use; requires reliable boundaries and sufficient configured GPS coverage |
| Top-up | `max(0,target-reliable_stock)`; estimated stock labels the output estimated; unknown stock returns null |
| Mileage | Total reconciled distance / total reconciled consumed fuel; never average per-event km/L |
| Fuel cost | Posted litres × independently invoice-verified prices; unverified or missing prices are excluded, not replaced with zero |
| Refill count | Distinct posted, non-reversed fuel events; drafts/pending records excluded |

Approved service windows supply GPS coverage's denominator. The numerator is accepted segment seconds overlapping those windows, capped at 100%. Missing windows mean unknown coverage. This metric does not certify road-distance accuracy. No-service days with an approved zero-trip plan have no travel demand. Unobserved engine use remains unknown. Data-quality gates and boundary measurement uncertainty accompany residuals; a residual is never an accusation.

Cross-midnight segments are allocated in proportion to elapsed time, without duplicating source events. Mileage changes also split intervals. Derived movement groups are rebuildable GPS interpretations, while raw events remain immutable. Provider-specific ignition/trip classification requires vendor validation. Driver assignment resolves at occurrence/fix time.

Exact measured and independently verified stock readings at period boundaries enable reconciliation. A closing boundary is the next opening boundary. Old readings are not described as current measured stock; the system either derives a clearly estimated balance from complete data or returns unknown. Reliable sensor readings require tank-specific calibration and stable reading windows.

GPS processing handles unique event IDs, replay, chronological sorting, speed conversion, stationary jitter, impossible jumps, poor accuracy, gaps, device swaps and odometer reset flags. Device cadence affects health. Revision changes invalidate the suitability of frozen reports for new signatures and require successor snapshots.

Regression examples exercised by tests:

- 79/80/81 km → 80 km/trip; two trips → 160 km/day.
- Four 80 km trips / 4 km/L → 320 km / 80 L.
- 100 L target − 18 L stock → 82 L.
- 40 + 200 − 60 → 180 L disappearance; 720/4 → 180 L; residual 0 L.
- Equal stock boundaries and 200 L consumed: range 800 km; actual 720 km; shortfall 80 km / 20 L equivalent.
- 120 + 2,000 − 180 → 1,940 L; 7,600/4 → 1,900 L; residual 40 L. The 60 L stock increase explains why a legacy 100 L comparison is different.

The public calculation-examples endpoint and authenticated refill-preview tool perform these educational calculations without creating operational records.
