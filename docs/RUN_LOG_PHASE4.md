# RUN LOG PHASE 4 — iceberg physics hindcast (branch: real-icebergs-physics)

## 2026-11-01: Phase 4 start on real-icebergs-physics (e9ad615)
- Inherited from RUN_LOG.md (origin/real-voyage): Phase 0-3 complete. Phase 0 closeout (replay pack, ice-box test) done. Phase 1 (real provider wired into routing) done. Phase 2 (timeline API + golden fixture) done. Phase 3 (BE-2 closeout) done.
- Branch real-icebergs-physics is at e9ad615, up to date with origin/main.
- Untracked: scripts/download_era5_wind_ablation.py (PART 2 wind-only ablation ERA5 download, era5_wind/ dir empty).
- Full pytest: 340 passed, 1 warning. Frontend typecheck + 118 unit tests + build all green.
- Stashed BE-2 eval infrastructure (src/eval/*, scripts/eval_sic.py, fetch_real_sic.py, NSIDC reader fixes) already applied to tree; eval tests pass (28 passed).
- models/eval/ contains iceberg_audit_report.json, iceberg_ml_report.json, real_sic_report.json, real_sic_report.md.

## 2026-11-01: Step 2 complete — simulated forcing report designated (not a real result)
- The hindcast ran scripts/hindcast_tracks_only.py against get_environment(), which returns a synthetic EnvironmentModel (is_synthetic=True; source "synthetic; stands in for ECMWF ERA5/HRES + Copernicus Marine CMEMS"). Wind and current are synthetic fields, not real ERA5/GLORYS.
- Report renamed: models/eval/iceberg_hindcast_simulated_forcing.json (was iceberg_hindcast_tracks_only.json), data_source set to "simulated_forcing".
- This is a simulated-forcing sanity run only. Kept out of the scorecard and README. Not presented as a real result.
- Results (simulated forcing, 30 sampled tracks, 340 forecasts): lead 1d median 20.12 km/p90 54.81 km (n=123); lead 3d median 56.61 km/p90 162.87 km (n=118); lead 7d median 106.15 km/p90 414.85 km (n=99).
- Real Part 1 (tracks only, no forcing): complete. scripts/iceberg_physics_part1.py computes the three
  no-forcing baselines (no movement, 3-day velocity, 7-day damped velocity) on real BYU/NIC v6 tracks.
  Radii p50/p90 calibrated on VAL (2018) residuals of the best baseline per lead; empirical coverage
  measured on TEST (2019-2022). Report: models/eval/iceberg_part1_report.json (data_source "real").
  - lead 1d: best=no_move, test median 3.32 km / p90 13.51 km, coverage p50 0.374 / p90 0.924 (n=21449)
  - lead 3d: best=velocity_7d_damped, test median 7.23 km / p90 27.43 km, coverage p50 0.457 / p90 0.932 (n=21327)
  - lead 7d: best=no_move, test median 21.53 km / p90 77.24 km, coverage p50 0.381 / p90 0.886 (n=21104)
  Unit tests: tests/test_iceberg_physics_part1.py (fixtures, no network, 4 passed).
- Step 4 paired comparison (identical samples, VAL/TEST): complete. scripts/iceberg_physics_comparison.py
  evaluates the three no-forcing baselines plus wind_only / full_physics / velocity_initialised on identical
  (track, t0, lead) samples; VAL chooses best baseline per lead; TEST reports median/p90/n and bootstrap CI
  by iceberg vs the best baseline; promoted computed in code. Report: models/eval/iceberg_physics_report.json
  (data_source "real"; forcing variants marked not-available because ERA5 wind + GLORYS current are not on
  disk — not fabricated). Unit tests: tests/test_iceberg_physics_comparison.py (3 passed).
- Step 5 velocity-initialised physics variant: defined pre-TEST and chosen on VAL only (added to FORCING_VARIANTS
  alongside wind_only and full_physics). Not computable with real numbers until PART 2 ERA5 download and GLORYS
  ingest are present; marked not-available, not fabricated.
- Simulated-forcing sanity run (not a real result): models/eval/iceberg_hindcast_simulated_forcing.json,
  data_source "simulated_forcing", kept out of the scorecard and README.

## 2026-11-01: Step 4/5 paired comparison — forcing variants marked not-available (logged)
- wind_only, full_physics, velocity_initialised were "not available" because no real forcing data was on disk:
  `data/raw/iceberg/era5_wind/` empty; no GLORYS directory. Copernicusmarine credentials present at
  `~/.copernicusmarine-credentials`; ARCO ERA5 reachable anonymously (one surface file = 47.5 MB).
- Exact situation logged: variants omitted, not fabricated. Report models/eval/iceberg_physics_report.json
  had data_source "real" but forcing_available=False, so forcing variant rows were not-available.

## 2026-11-01: Phase 4B — real forcing download and evaluation (started)
- Full coverage estimate: 1834 days (t0-3 to t0+7 over VAL 2018 + TEST 2019-2022) × ~95 MB ERA5/day ≈ 170 GB,
  far over the 6 GB budget. Restricting to a representative subset: TEST block + VAL block, logging the
  restriction. ERA5 downloaded from ARCO as one contiguous full-day file per day-variable (ARCO serves full
  days; spatial corridor subset applied in memory at RK4 time), subsampled to 3-hourly, cached to disk,
  resumable (skip if file exists). GLORYS via copernicusmarine subset per corridor/time range. Total size
  printed before download; capped at 6 GB (restrict TEST first, then VAL if over).

## 2026-11-01: Phase 4B download complete (TEST block only — budget cap)
- ERA5 10 m wind (u10, v10) from anonymous ARCO GCS: 20 days (2022-01-07 -> 2022-01-26), 40 files, 1.9 GB.
  Cached to data/raw/iceberg/era5_wind/. Resumable (skip if exists). Subsampled to 3-hourly in memory at RK4 time.
- GLORYS currents (cmems_mod_glo_phy_my_0.083deg_P1D-m, uo/vo, 0-100 m depth): 20 days, 20 files, 3.1 GB.
  Cached to data/raw/iceberg/glorys/. Latitude clipped to dataset bounds (-80..90); depth 0-110 m.
- TOTAL: 5.0 GB, within the 6 GB budget. VAL block NOT downloaded (would exceed budget: +3.5 GB).
  Real forcing available for TEST block t0 2022-01-10 -> 2022-01-19 only.
- scripts/download_iceberg_forcing.py written (budget-enforced, resumable, prints total size).
- Manifest: data/raw/iceberg/forcing_manifest.json.

## 2026-11-01: Phase 4B real-forcing evaluation complete — physics loses to baselines
- Ran scripts/iceberg_physics_real_eval.py on the TEST block (t0 2022-01-10 -> 2022-01-19): 140 unique
  (track, t0) samples, 14 icebergs, 420 (sample, lead) points, all six variants on IDENTICAL samples.
- Real forcing (ERA5 wind + GLORYS 0-100 m current) LOSES to the no-forcing baselines at every lead:
  - lead 1 d: no_move 2.56 km / p90 6.35; velocity_3d 1.56; physics 8.29 / p90 23.60; wind_only 5.57 (n=140)
  - lead 3 d: velocity_3d 5.20 / p90 11.66; velocity_7d_damped 5.72; physics 24.95 / p90 79.66; wind_only 15.86 (n=140)
  - lead 7 d: velocity_7d_damped 14.00 / p90 35.54; no_move 17.81; physics 65.90 / p90 233.47; wind_only 46.83 (n=140)
- promoted = True (computed in code): no forcing variant significantly beats the VAL-chosen best baseline;
  physics is worse than persistence — reported plainly, not suppressed.
- Report: models/eval/iceberg_physics_report.json (data_source "real"; real ERA5 + GLORYS really used).
- New code: src/core/real_forcing.py (real ERA5/GLORYS env, is_synthetic=False), scripts/download_iceberg_forcing.py,
  scripts/iceberg_physics_real_eval.py. Modified src/core/iceberg_tracker.py (propagate is_synthetic/source;
  initial_velocity_ms param for velocity-initialised variant).
- New tests: tests/test_real_forcing.py (is_synthetic False), tests/test_real_ice_routing.py
  (scorecard skips data_source != "real"). 12 tests pass.
- Scalars: wind_scale/current_scale fixed at identity (1.0/1.0); NOT tuned on VAL (VAL forcing not downloaded
  within the 6 GB budget). Logged.

## Phase 4 plan (parts in order):
- PART 1: tracks-only hindcast — run RK4 drift physics (iceberg_tracker.py) on real BYU/NIC v6 tracks, compare simulated vs observed at leads 1/3/7 days, no ML, no ERA5 wind (synthetic environment forcing only).
- PART 2: wind-only ablation — run scripts/download_era5_wind_ablation.py to download ERA5 10m wind from ARCO for representative days in 2019-2022, then hindcast with wind-only forcing.
- PART 3: full hindcast — wind + current forcing on real tracks.
- Each part: commit + push after completion.
- Never kill PID 38042 (extras download, may be running).
