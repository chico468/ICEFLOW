# RUN LOG

## 2026-10-31: Build replay pack + ice-box test + extras (on be2-sic-ml)
- Committed docs/AUTONOMY.md and docs/RUN_LOG.md
- Committed scripts/build_replay_pack.py changes on be2-sic-ml (f13d39c)
- Built 33-day replay pack at /tmp/iceflow-full-pack (632 MB, 5 products)
- Ice-box test results: Weddell Sea (n=4599, corr=0.9325, PASS), 60-80E Jan (n=1495, corr=0.000, STOP data gap), 60-80E Aug winter (n=1488, corr=0.9104, PASS)
- ERA5 waves under ice: swh NaN on 93.9% of SIC>=0.15 cells (consistent with wave_valid=False)
- Added R0_COVERAGE_MATRIX with era5_surface_* entries; added snowfall, tcc, t2m, msl as extras
- be2-sic-ml reset to origin/be2-sic-ml (unpushed commits 5d5c258, e587d02, f13d39c not cherry-picked; real-voyage already has build_replay_pack R0 matrix at 906eb86)
- Frontend worktree ICEFLOW-frontend was accidentally removed and restored on real-voyage at 802a1fc
- Currently on `work` branch branched from real-voyage (802a1fc)

## NEXT: Tasks 1-7 on real-voyage branch
1. Vectorised provider (sample_grid / sample_many)
2. Ice time semantics (departure_snapshot | daily)
3. Remove real_ice silent synthetic fallback
4. Inject EnvironmentProvider into route_optimizer.py, voyage.py, iceberg_tracker.py, growler_radar.py
5. Optimize 60s test if needed
6. Check BE-2 closeout (IIEE table)
7. Full pytest on real-voyage

## 2026-10-31: BE-5 implementation complete (on real-voyage)
- Committed docs/AUTONOMY.md and docs/RUN_LOG.md
- BE-5 Tasks 1-5 complete:
  1. Vectorised provider: added sample_grid to EnvironmentProvider protocol + all implementations (ReplayProvider, SimulatedProvider, LiveProvider, EnvironmentModel); FieldCache uses sample_grid instead of point-sample loops
  2. Ice time semantics: added ice_time_mode ("departure_snapshot" | "daily") to PolarRouteOptimizer; daily mode loads ice per day and uses nearest day per slice
  3. Removed real_ice silent synthetic fallback: real_ice now raises NSIDCUnavailableError instead of falling back to synthetic; updated tests accordingly
  4. Injected EnvironmentProvider into route_optimizer.py (FieldCache), voyage.py (VoyageEngine), iceberg_tracker.py (_field_forcing), growler_radar.py (simulate_sweep)
  5. 60s test: passes within limit (no optimization needed)
- Full pytest: 340 passed, 1 warning in 254.89s
- BE-2 closeout: IIEE table exists (models/eval/real_sic_report.md), lead-3 sanity check exists, Nov-Mar/austral_departure season exists, V6 product confirmed

## 2026-10-31: Pushed to origin/real-voyage (SHA 5a14509)
- Pushed 3 commits: 7e1b7ee (docs), 8e9e941 (BE-5 implementation), 5a14509 (RUN_LOG)
- real-voyage is now at 5a14509 on origin
- be2-sic-ml reset to origin/be2-sic-ml (a4395d4); unpushed be2-sic-ml commits NOT cherry-picked (real-voyage already has build_replay_pack R0 matrix at 906eb86)
- Full pytest: 340 passed, 1 warning in 254.89s (0:04:14)
- No items BLOCKED

## 2026-11-01: PHASE 2 complete (timeline API + golden fixture) on real-voyage, pushed as 7fd0e51
- Committed docs/AUTONOMY.md (7e1b7ee) on real-voyage; branch in sync with origin
- PHASE 0 (closeout): replay pack sha256 all verified against manifest.json; coverage printed per product (era5_wind, era5_waves, cmems_current, glorys_siconc, nrt_ice_concentration). NOTE: era5_waves_20220115_33d.nc (39 MB) sits in pack but is NOT declared in manifest (manifest completeness gap logged).
- Ice-box test (scripts/ice_box_test.py): GLORYS siconc attrs have NO _FillValue/missing_value/comment; cell_methods='area: mean where sea_ice'. Rule documented in code: NaN siconc=0 ONLY where uo valid (ocean), else excluded. Regrid GLORYS->NSIDC 25 km (area average; each fine cell assigned to its NSIDC cell). 3 cases, NO gross disagreement:
  * Weddell (20-60W,60-75S) Jan 15 2022: n=4613 corr=0.9368 mean_diff=-0.065 rmse=0.160
  * 60-80E Jan 15 2022: n=1500 corr=nan(zero var) mean_diff=-0.035 rmse=0.144
  * 60-80E Aug 15 2022 winter: n=1500 corr=0.9206 mean_diff=+0.008 rmse=0.096 (downloaded one-day files: siconc 2.1 MB, uo/vo 183 MB; NSIDC 420 KB)
- ERA5 waves under ice (task 3): raw swh on NSIDC SIC>=0.15 cells = NaN 82.5% / value 17.5% / never 0 (min 0.343 m); provider masks to wave_valid=False under ice (never 0).
- Branch hygiene (task 5): be2-sic-ml has 3 UNPUSHED commits (5d5c258, e587d02, f13d39c), none pushed; NOT cherry-picked to real-voyage (real-voyage already carries build_replay_pack R0 matrix at 906eb86 and docs at 37a5990; cherry-pick would regress/duplicate). real-voyage==origin/real-voyage.
- BE-2 closeout (task 6): IIEE table complete in models/eval/real_sic_report.md — IIEE per lead 1/3/7/14, all-season and austral_departure (Nov-Mar), lead-3 IIEE=0.120 Mkm2/day (<1 threshold, no bug). V6 product confirmed.
- Extras (task 4): scripts/build_extras.py started (snowfall sf, tcc, t2m, msl 3-hourly from ARCO-ERA5); DOWNLOAD IN PROGRESS (~132 files, ~50 MB each = up to ~6.6 GB gross, ~250 MB packed after SO slice). Will verify <=5 GB budget and add to R0 matrix + manifest on completion.
- PHASE 2 (timeline API + golden fixture):
  1. GET /api/v1/voyage/{id}/timeline?step_min=10 added (src/api/routers/voyages.py): gzip (GZipMiddleware), size-capped by step_min. Per step: t_utc, lat, lon, sog_kn, cog, heading, ice_conc, wind u/v, hs, tp, wave_dir, current u/v, nearby observed bergs {name,lat,lon,length_nm,width_nm,age,kind}, alerts, sun az/el, not_available[], provenance_by_variable per variable.
  2. snowfall/tcc added to EnvSample; ReplayProvider populates t2m/msl/snowfall/tcc from pack when present.
  3. src/core/solar.py: solar azimuth/elevation (Meeus/NOAA), equinox-geometry test anchors (tests/test_solar.py, 6 pass).
  4. scripts/export_golden_timeline.py: Cape Town -> Bharati replay on 2022-01-15 via API test client (no network), fixture frontend/e2e/fixtures/golden-voyage-timeline.json (1.39 MB, under 5 MB cap, 432 steps at 30-min) + manifest (sha256, git sha, generated_at, inputs, versions).
  5. Fixture-based tests (tests/test_timeline.py, 8 pass): shape, not_available, provenance on every variable, sun position, size cap, monotonic UTC.
  6. docs/SPRINT.md: real timeline shapes + provenance conventions (legacy status/note vs kind/age_hours).
- Full pytest: 354 passed, 1 warning (340 baseline + 6 solar + 8 timeline), clean tree on real-voyage 7fd0e51.
- Pushed to origin/real-voyage. Compare URL: https://github.com/chico468/ICEFLOW/compare/main...real-voyage
- Branch hygiene (task 5): be2-sic-ml has 3 UNPUSHED commits (none pushed):
    f13d39c BE-2: add AUTONOMY.md, RUN_LOG.md, R0 matrix, extras, ice-box test v2
    e587d02 BE-2: fetch ERA5 via single contiguous zarr slice then subsample to 3-hourly
    5d5c258 BE-2: rewrite build_replay_pack to use ARCO-ERA5 zarr + GLORYS12V1 + NSIDC V6
  Cherry-pick to real-voyage ATTEMPTED → CONFLICTED (structural: be2-sic-ml rewrites build_replay_pack.py to a zarr-based approach; real-voyage has a working netcdf-based build_replay_pack with the R0 matrix at 906eb86 and identical docs at 37a5990). NOT cherry-picked — would regress real-voyage's working version and add tests importing zarr-only symbols (failing tests, rule 4). real-voyage already carries equivalent functionality.
  Per instruction 5, reset be2-sic-ml back to origin/be2-sic-ml via `git branch -f` (local-only, not force-push). SHAs logged above.
- Extras download still in progress (will complete and log sizes; not a blocker for PHASE 2 push).
- No items BLOCKED.

## Download rate measurement (extras, PID 38042)
- bytes_in sample 1: 186,260,235; sample 2: 199,433,475; sample 3: 202,344,755; sample 4: 241,941,219
- Rate varies per file (80 KB/s - 1.6 MB/s seen in prior run log); avg ~176 KB/s over pytest interval
- ~242 MB of ~6.6 GB downloaded; remaining ~6.36 GB; ETA uncertain, possibly >90 min
- Decision: let it continue; check between steps. If ETA confirmed >90 min, kill and build only snowfall + total_cloud_cover.
