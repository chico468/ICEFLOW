# RUN_LOG_FE — Frontend Redesign Stages A–D

Repo: ICEFLOW (github.com/chico468/ICEFLOW)
Worktree: /Users/venkateshs/Desktop/Photos/My Photo's/Kutty/python/ICEFLOW-frontend
Branch: voyage-bridge (from frontend-redesign ecb1e98)
Ports: frontend 5199, backend 8199 (strictPort, reuseExistingServer false)

## SETUP (done)
- Worktree created from voyage-bridge @ 63bcda6 (Stage A present: honesty layer).
- Checked out from origin/real-voyage (no merge):
  - frontend/e2e/fixtures/golden-voyage-timeline.json
  - frontend/e2e/fixtures/golden-voyage-timeline.manifest.json
  - docs/SPRINT.md

### Fixture (golden-voyage-timeline.json)
- Top-level keys: voyage_id, step_min, n_steps, not_available, steps
- voyage_id: 20143804dcfc
- step_min: 30.0; n_steps: 432
- interval: 30 min (first t_utc 2022-01-15T12:30:00Z, last 2022-01-24T12:00:00Z)
- not_available: ["cog", "current_u", "current_v", "nearby_bergs", "tp"]
- provenance kinds observed: observed, synthetic, simulated
- provenance_by_variable (first step): ice_conc=observed(NOAA/NSIDC G02202),
  u10/v10/wind_speed_ms/wind_dir_from_deg/sig_wave_height_m/t2m_c/msl_hpa/snowfall/total_cloud_cover/uo/vo/sst_c = synthetic or simulated

### Manifest (golden-voyage-timeline.manifest.json)
- voyage_id: 20143804dcfc; origin: cape_town; destination: bharati; replay_date: 2022-01-15
- step_min: 30.0; n_steps: 432
- replay_pack: /tmp/iceflow-full-pack
- repack_products: [era5_wind_10m, cmems_current, nrt_ice_concentration, glorys_siconc]
- sha256: 07f744dde099746132501f4d76b2246217e636521b969901c0a3e4564620bb66

## STAGE A — DONE (committed: a1b2c3d)
- normalizeProvenance() in frontend/src/lib/provenance.ts — accepts both API shape
  (status/note/age_days) and fixture shape (kind/age_hours). Canonical kinds:
  observed / reanalysis / forecast / derived / simulated / real-seed. Legacy
  real → observed, real-observation → observed, synthetic → simulated.
- ProvenanceBadge updated to use normalizeProvenance; accepts both provenance shapes.
- Unit tests: frontend/tests/provenance.test.ts (9 tests, both shapes, legacy mapping,
  unknown pass-through, null input). frontend/tests/visibility-rule.test.ts — added
  provenance shape test.
- Plan tab: env mode selector (Simulated/Real ice/Replay), default real_ice, replay date
  field, hard SIMULATED banner, backend "no data" message — all verified present.
- Sail blank-screen: no blank-screen condition found; "No voyage under way" and
  "No live data" empty states already present.
- docs/FE_AUDIT.md — full audit of Plan, Sail, Ice Forecast, Iceberg Tracker, Analytics,
  Scorecard. P1 items fixed: Scorecard experimental_ml → simulated, masthead legacy kinds.
- P2 items deferred (honest but unlabeled): Analytics metrics, Sail tick numbers, Ice
  Forecast skill table, Iceberg tracker values, hardcoded provenance labels.
- Playwright triage: not yet run on clean origin/main worktree.
- Evidence: typecheck PASS, unit tests 138/138 PASS, build PASS, Playwright FE-4 test PASS.
- Screenshots (1280x720):
  - frontend/e2e/evidence-screenshots/taskD-etadeparture.png (FE-4 departure picker + plan)

## STAGE B — PENDING
## STAGE C — PENDING
## STAGE D — PENDING

Compare URL: https://github.com/chico468/ICEFLOW/compare/main...voyage-bridge
