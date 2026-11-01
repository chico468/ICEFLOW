# Phase 5 — RUN_REPORT (iceberg physics hindcast closeout)

Branch: `real-icebergs-physics` (from `real-icebergs` / origin/main). Phase 4 steps 1-5 complete.

## Scope
Phase 4 evaluates iceberg drift physics against the real BYU/NIC consolidated Antarctic iceberg database v6
(daily positions, one file per iceberg, 1976-2022), with splits train 2005-2017, val 2018, test 2019-2022,
leads 1/3/7 days, no ML, no tuning on TEST.

## Data sources and honesty
- Tracks: real BYU/NIC v6 observations (`data/raw/iceberg/consolidated_database_v6.zip`).
  - 601 raw tracks, 464 moving after grounding filter (<0.1 kt), 281,605 position-days.
- VAL (2018): 26,824 rows. TEST (2019-2022): 63,880 rows.
- Forcing: NONE of ERA5 wind or GLORYS current is on disk. `data/raw/iceberg/era5_wind/` is empty and no
  GLORYS directory exists. Therefore every number in this report is computed from observed tracks with
  **no forcing model** (no ERA5, no GLORYS). Wind-only ablation and full physics are **not fabricated**;
  they are omitted pending PART 2 (ERA5 download) and PART 3 (GLORYS ingest).
- `models/eval/iceberg_hindcast_simulated_forcing.json` is a simulated-forcing sanity run
  (`data_source: "simulated_forcing"`). It is **not** a real result and is kept out of this report.

## Step 3 — Part 1 tracks-only physics baseline (no forcing, no ML)
Report: `models/eval/iceberg_part1_report.json` (`data_source: "real"`).
Radii p50/p90 calibrated on VAL residuals of the best baseline per lead; empirical coverage measured on TEST.

| lead | best baseline (VAL) | cal p50 km | cal p90 km | test median km | test p90 km | coverage p50 | coverage p90 | n samples | n icebergs |
|----:|---|---:|---:|---:|---:|---:|---:|---:|---:|
| 1 d | no movement | 1.46 | 15.16 | 3.32 | 13.51 | 0.374 | 0.924 | 21,449 | 50 |
| 3 d | 7-day damped velocity | 6.12 | 32.56 | 7.23 | 27.43 | 0.457 | 0.932 | 21,327 | 50 |
| 7 d | no movement | 12.39 | 72.57 | 21.53 | 77.24 | 0.381 | 0.886 | 21,104 | 50 |

Unit tests: `tests/test_iceberg_physics_part1.py` (4 passed, fixtures, no network).

## Step 4 — Paired comparison on identical (track, t0, lead) samples
Report: `models/eval/iceberg_physics_report.json` (`data_source: "real"`).
VAL (2018) selects the best baseline per lead; TEST (2019-2022) reports median/p90/n on identical samples and
bootstrap CI (by iceberg) of each variant vs the best baseline. `promoted` is computed in code, not hardcoded;
no tuning on TEST.

Baselines (all on identical TEST samples):

| lead | best baseline (VAL) | no movement med/p90 km | 3-day velocity med/p90 km | 7-day damped med/p90 km | n samples |
|----:|---|---:|---:|---:|---:|
| 1 d | no movement | 3.32 / 13.51 | 1.88 / 8.78 | 2.35 / 10.32 | 21,449 |
| 3 d | 7-day damped | 9.88 / 36.58 | 6.56 / 25.49 | 7.23 / 27.43 | 21,327 |
| 7 d | no movement | 21.53 / 77.24 | 17.40 / 63.97 | 16.12 / 59.24 | 21,104 |

Forcing variants (wind_only, full_physics, velocity_initialised): **not available** — ERA5 wind and GLORYS
current are not on disk. Omitted, not fabricated.

Unit tests: `tests/test_iceberg_physics_comparison.py` (3 passed, fixtures, no network).

## Step 5 — Velocity-initialised physics variant
Defined pre-TEST and chosen on VAL only; added to the variant set alongside wind_only and full_physics. Not
computable with real numbers until PART 2 ERA5 download and PART 3 GLORYS ingest are present; marked
not-available, not fabricated.

## Verification
- Full backend pytest: `340 passed, 1 warning` (run on clean tree after reverting the out-of-scope
  `route_optimizer.py` ETA commit).
- git status clean; all Phase 4 commits pushed to `origin/real-icebergs-physics`.

## Remaining (Phase 4 PART 2 / PART 3, unblocked by data)
- PART 2: run `scripts/download_era5_wind_ablation.py` to fetch ERA5 10 m wind from ARCO for representative
  days in 2019-2022, then wind-only hindcast.
- PART 3: full hindcast with ERA5 wind + GLORYS currents (surface and 0-100 m mean).
- Once ERA5/GLORYS data lands on disk, recompute `models/eval/iceberg_physics_report.json` so wind_only,
  full_physics and velocity_initialised rows become real (data_source "real" only when ERA5 and GLORYS
  forcing were really used).
