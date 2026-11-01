# Phase 5 — RUN_REPORT (iceberg physics hindcast closeout)

Branch: `real-icebergs-physics`. Phase 4 steps 1-5 and Phase 4B (real forcing) complete.

## Outcome (honest)

**Real-forcing physics loses to the no-forcing baselines.** With real ECMWF ERA5 10 m wind (anonymous ARCO
GCS store) and real Copernicus Marine GLORYS currents (surface and 0-100 m mean) driving the existing RK4
drift model, every forcing variant is worse than simple persistence on identical (track, t0, lead) samples:

| lead | best baseline (VAL) | baseline median km | wind-only median km | physics median km | velocity-initialised median km | n | promoted |
|----:|---|---:|---:|---:|---:|---:|---|
| 1 d | no movement | 2.56 | 5.57 | 8.29 | 8.33 | 140 | True |
| 3 d | 3-day velocity | 5.20 | 15.86 | 24.95 | 25.13 | 140 | True |
| 7 d | 7-day damped velocity | 14.00 | 46.83 | 65.90 | 65.69 | 140 | True |

- `promoted = True` (computed in code): no forcing variant significantly beats the VAL-chosen best baseline
  (bootstrap CI by iceberg entirely above zero, i.e. forcing variants are worse, not better).
- The result is reported plainly, not suppressed: physics does not provide skill over persistence at leads
  1/3/7 days on these Antarctic icebergs with the available ERA5 + GLORYS forcing.

## Data and method

- Tracks: real BYU/NIC v6 observations. TEST block t0 2022-01-10 -> 2022-01-19; 140 unique (track, t0)
  samples, 14 icebergs, 420 (sample, lead) points. Truth = observed position at t0+lead (exact date match).
- Forcing downloaded (real): ERA5 wind 20 days (2022-01-07 -> 2022-01-26), GLORYS currents 20 days.
  Total downloaded **5.0 GB** (ERA5 1.88 GB + GLORYS 3.13 GB), within the 6 GB budget.
- Budget cap forced a restriction: full coverage (1834 forcing days ≈ 170 GB ERA5 alone) far exceeds 6 GB,
  so only the TEST block was downloaded; VAL forcing was NOT downloaded. Scalars (wind-drag scale, current
  scale) fixed at identity (1.0, 1.0), NOT tuned on VAL. Logged.
- The wind-only ablation uses ERA5 wind with current = 0 (current_scale = 0). Full physics uses ERA5 +
  GLORYS 0-100 m mean current.
- `is_synthetic = False` asserted for the real-forcing environment (tests/test_real_forcing.py).

## Reports
- `models/eval/iceberg_physics_report.json` — `data_source: "real"`, real forcing really used.
- `models/eval/iceberg_part1_report.json` — `data_source: "real"`, no-forcing Part 1 (VAL/TEST).
- `models/eval/iceberg_hindcast_simulated_forcing.json` moved to `docs/experiments/` — `data_source:
  "simulated_forcing"`, sanity run only, NOT a real result, kept out of the scorecard and README.
- Scorecard builder (`src/api/routers/evidence.py:43`) reads only reports with `data_source == "real"`;
  covered by tests/test_real_ice_routing.py (including a test that non-real reports are skipped).

## Files changed (Phase 4B)
- `src/core/real_forcing.py` (new) — real ERA5/GLORYS environment, `is_synthetic=False`.
- `src/core/iceberg_tracker.py` — propagate `is_synthetic`/`source` from environment; `initial_velocity_ms`
  parameter for the velocity-initialised variant.
- `scripts/download_iceberg_forcing.py` (new) — budget-enforced (6 GB), resumable ERA5+GLORYS downloader.
- `scripts/iceberg_physics_real_eval.py` (new) — paired real-forcing evaluation, writes the report.
- `tests/test_real_forcing.py` (new), `tests/test_real_ice_routing.py` (scorecard-skip test).
- `docs/RUN_LOG_PHASE4.md`, `docs/RUN_REPORT.md` (this file).
- `docs/experiments/iceberg_hindcast_simulated_forcing.json` (moved from models/eval/).

## Verification
- `tests/test_real_forcing.py`, `tests/test_real_ice_routing.py` scorecard tests,
  `tests/test_iceberg_physics_part1.py`, `tests/test_iceberg_physics_comparison.py`: 12 passed.
- All Phase 4 work committed and pushed to `origin/real-icebergs-physics`.
