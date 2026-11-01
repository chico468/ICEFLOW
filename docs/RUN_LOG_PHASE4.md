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

## Phase 4 plan (parts in order):
- PART 1: tracks-only hindcast — run RK4 drift physics (iceberg_tracker.py) on real BYU/NIC v6 tracks, compare simulated vs observed at leads 1/3/7 days, no ML, no ERA5 wind (synthetic environment forcing only).
- PART 2: wind-only ablation — run scripts/download_era5_wind_ablation.py to download ERA5 10m wind from ARCO for representative days in 2019-2022, then hindcast with wind-only forcing.
- PART 3: full hindcast — wind + current forcing on real tracks.
- Each part: commit + push after completion.
- Never kill PID 38042 (extras download, may be running).
