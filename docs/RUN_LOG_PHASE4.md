# RUN LOG PHASE 4 — iceberg physics hindcast (branch: real-icebergs-physics)

## 2026-11-01: Phase 4 start on real-icebergs-physics (e9ad615)
- Inherited from RUN_LOG.md (origin/real-voyage): Phase 0-3 complete. Phase 0 closeout (replay pack, ice-box test) done. Phase 1 (real provider wired into routing) done. Phase 2 (timeline API + golden fixture) done. Phase 3 (BE-2 closeout) done.
- Branch real-icebergs-physics is at e9ad615, up to date with origin/main.
- Untracked: scripts/download_era5_wind_ablation.py (PART 2 wind-only ablation ERA5 download, era5_wind/ dir empty).
- Full pytest: 340 passed, 1 warning. Frontend typecheck + 118 unit tests + build all green.
- Stashed BE-2 eval infrastructure (src/eval/*, scripts/eval_sic.py, fetch_real_sic.py, NSIDC reader fixes) already applied to tree; eval tests pass (28 passed).
- models/eval/ contains iceberg_audit_report.json, iceberg_ml_report.json, real_sic_report.json, real_sic_report.md.

## 2026-11-01: PART 1 complete (tracks-only hindcast)
- Ran scripts/hindcast_tracks_only.py on 30 sampled moving BYU/NIC v6 tracks, sparse t0 sampling (stride 7, max 8 t0s/track), one 168h RK4 forecast per t0 covering leads 1/3/7 days against observed truth.
- 340 (t0, lead) forecasts in 485s. Report: models/eval/iceberg_hindcast_tracks_only.json
  - lead 1d: n=123, n_icebergs=21, median=20.12 km, p90=54.81 km
  - lead 3d: n=118, n_icebergs=21, median=56.61 km, p90=162.87 km
  - lead 7d: n=99, n_icebergs=19, median=106.15 km, p90=414.85 km
- Fixed script: was launching one forecast per (t0, lead) (~36k calls, timed out >10 min) and could not verify lead 7 inside a 72h forecast; now one 168h forecast per t0, correct lead-7 verification.
- PART 1: tracks-only hindcast — run RK4 drift physics (iceberg_tracker.py) on real BYU/NIC v6 tracks, compare simulated vs observed at leads 1/3/7 days, no ML, no ERA5 wind (synthetic environment forcing only).
- PART 2: wind-only ablation — run scripts/download_era5_wind_ablation.py to download ERA5 10m wind from ARCO for representative days in 2019-2022, then hindcast with wind-only forcing.
- PART 3: full hindcast — wind + current forcing on real tracks.
- Each part: commit + push after completion.
- Never kill PID 38042 (extras download, may be running).
