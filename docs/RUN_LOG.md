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
