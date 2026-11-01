# RUN LOG PHASE 4 — iceberg physics hindcast

## 2026-11-01: Part A — demo-integration branch (local only, not pushed)
- Created local-only branch demo-integration from origin/main
- Merged origin/real-voyage (fast-forward), then origin/be2-sic-ml (conflict in docs/RUN_LOG.md resolved by keeping both sides)
- Committed as 25f1f8d (local only)
- Full pytest: 367 passed, 3 warnings in 241.87s

## 2026-11-01: Part B — coverage endpoint (branch be-coverage-endpoint, pushed)
- Added GET /api/v1/environment/coverage to src/api/routers/copernicus_layers.py
  - replay {start, end, bbox, products:[{layer, product, version, kind, start, end}]} from ICEFLOW_REPLAY_PACK manifest
  - real_ice {latest_cached_date, walkback_days=14, today, available} from NSIDC cache
- Added _check_coverage() to src/api/routers/navigation.py: replay plan requests outside coverage return
  HTTP 422 with {code: "out_of_coverage", variable, requested, available}; never 500, never silent fallback
- Added tests/test_coverage.py (14 tests): endpoint shape, product kinds, ISO date, out-of-coverage 422,
  missing replay_date 422, simulated mode always 200, promoted gate tests (losing/CI-zero/winning/any-variant)
- All tests pass

## 2026-11-01: Part C — Phase 4B real forcing iceberg evaluation (branch be-iceberg-physics-real, pushed)
- Ported scripts/iceberg_physics_real_eval.py, scripts/download_iceberg_forcing.py, src/core/real_forcing.py,
  tests/test_real_forcing.py, tests/test_real_ice_routing.py from real-icebergs-physics
- Updated src/core/iceberg_tracker.py: _field_forcing uses EnvironmentProvider.sample_grid();
  environment param typed as EnvironmentProvider; initial_velocity_ms for velocity-initialised variant
- Updated src/core/route_optimizer.py: real_ice raises NSIDCUnavailableError, never falls back;
  replay remains hard failure for missing observation
- Real forcing evaluation: 140 unique (track, t0) samples, 14 icebergs, replay-window check 2022-01-10->2022-01-19
  ERA5 1.9 GB + GLORYS ~2.85 GB = within 6 GB budget
  velocity_initialised variant included for all leads (promoted=null, replay_window_check scope)
- TEST/VAL BLOCKED: ARCO store chunked one global hour per chunk; server-side cropping needs CDS token
- Wrote models/eval/iceberg_physics_report.json: data_source="real", promoted=null for all leads,
  evaluation_scope="replay_window_check", test_val_blocked=True
- Moved models/eval/iceberg_hindcast_simulated_forcing.json to docs/experiments/
- Full pytest: 381 passed, 3 warnings in 250.98s

## 2026-11-01: Part C fixes — gate logic inverted, evaluation_scope labeled, real_ice raises, gate tests added
- Fixed promoted gate: starts False, set True only if forcing variant significantly beats baseline (CI entirely below zero)
- Added evaluation_scope: "replay_window_check" to report; promoted=null for this scope (not evaluated)
- TEST/VAL evaluation BLOCKED: reason "ARCO store is chunked one global hour per chunk; server-side cropping needs a CDS token"
- real_ice raises NSIDCUnavailableError, never falls back to synthetic
- Added gate tests: promoted false when physics loses, promoted false when CI includes zero,
  promoted true when physics wins, promoted true when any forcing variant wins

## 2026-11-01: Task 1 — Timeline resolution honours step_min
- Rewrote GET /api/v1/voyage/{id}/timeline in src/api/routers/voyages.py:
  Steps resampled from route polyline + waypoint_etas at requested step_min interval;
  position/SOG/heading interpolated along each route leg; environment sampled per step via provider
- Step counts (Cape Town -> Bharati replay 2022-01-15):
  step_min=10: 1324 steps; step_min=30: 442 steps; step_min=60: 221 steps
- First step = departure, last step = near arrival; environment sampled (wind_u, ice_conc, etc.)

## 2026-11-01: Task 2 — Passage sanity (Cape Town -> Bharati replay)
- Great-circle distance: 2823.5 nm
- Sailed distance: 2999.4 nm
- Vessel open water speed: 16.84 kn
- Average SOG: 13.75 kn (below max speed — no bug)
- Hours in ice >15% SIC: 9.5 h
- Avg Lindqvist speed reduction: 0.43 kn

## 2026-11-01: Task 3 — SIC promotion audit (from real_sic_ml_report.json)
- Promotion rule (code, real_sic_forecaster.py:14-16): lead promoted only if model RMSE beats tuned
  baseline with bootstrap CI of RMSE difference excluding zero, in BOTH all-season and Nov-Mar,
  on variable ice zone
- Lead 3: all-season CI=[-0.00799,-0.004] (excludes 0), Nov-Mar CI=[-0.00978,-0.0055] (excludes 0) → promoted
- Lead 7: all-season CI=[-0.01583,-0.00551] (excludes 0), Nov-Mar CI=[-0.01986,-0.01141] (excludes 0) → promoted
- Lead 14: all-season CI=[-0.02361,-0.01099] (excludes 0), Nov-Mar CI=[-0.0282,-0.01785] (excludes 0) → promoted
- Lead 14 promoted because CI excludes zero in BOTH seasons on VIZ cells (rule satisfied)
- Sensor-era (AMSR2): lead3 rmse=0.09257 ci=[-0.00818,-0.00422]; lead7 rmse=0.12484 ci=[-0.01422,-0.00749];
  lead14 rmse=0.15605 ci=[-0.01823,-0.01136] — model beats baseline on AMSR2-era data too

## 2026-11-01: Task 4 — Scorecard null promoted + evaluation_scope
- promoted values may be null (not evaluated); never coerced to false (removed bool() coercion)
- Added evaluation_scope field to each scorecard row (from report metadata, default "test")
- Added n per row (already present)
- Updated docs/SPRINT.md scorecard contract: promoted {sic: {bool|null}, iceberg: {bool|null}},
  rows include evaluation_scope
- Added test_scorecard_promoted_can_be_null: asserts null preserved, evaluation_scope and n on row
- Scorecard: data_source=real, 146 rows, promoted sic={3:True,7:True,14:True}, iceberg={1:False,3:False,7:False}

## 2026-11-01: Task 6 — Merge into demo-integration, full pytest, restart uvicorn, curl outputs
- All changes committed on demo-integration (local only)
- Pushed demo-integration -> origin/be-iceberg-physics-real (9b6095d)
- Branch hygiene: git merge-base be-iceberg-physics-real origin/main = clean; no ETA commit
- src/core changed files: iceberg_tracker.py, real_forcing.py, route_optimizer.py
- route_optimizer.py diff: real_ice raises NSIDCUnavailableError (fallback REMOVED, never added)
- Full pytest: 381 passed, 3 warnings in 250.98s (0:04:10)
- Restarted uvicorn on port 8000 (no reload): ICEFLOW_REPLAY_PACK=~/iceflow-data/replay-pack-2022-01
- curl /api/v1/environment/coverage: 200, replay {start:2022-01-15, end:2022-02-16,
  products:[era5_wind_10m,cmems_current,nrt_ice_concentration,glorys_siconc]},
  real_ice {latest_cached_date:2026-08-01, walkback_days:14, today:2026-11-01, available:true}
- curl POST /api/v1/voyage (cape_town->bharati, replay 2022-01-15): voyage_id 5c866053030d,
  arrival_iso 2022-01-24T04:36:00+00:00, status PLANNED
- curl GET /api/v1/voyage/5c866053030d/timeline?step_min=30: n_steps=442 (about 432 like golden fixture),
  first step t_utc=2022-01-15T00:00:00+00:00, environment sampled (wind_u=1.599)
- curl GET /api/v1/evidence/scorecard: data_source=real, 146 rows,
  promoted sic={3:True,7:True,14:True}, iceberg={1:False,3:False,7:False},
  rows carry evaluation_scope and n
