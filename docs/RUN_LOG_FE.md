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

## STAGE A — DONE (committed: ed178ee)
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
- Evidence: typecheck PASS, unit tests PASS, build PASS, Playwright tests PASS.
- Screenshots:
  - frontend/e2e/evidence-screenshots/taskA-regional-map.png
  - frontend/e2e/evidence-screenshots/taskC-plan-screen.png
  - frontend/e2e/evidence-screenshots/taskC-scorecard.png

## STAGE B — DONE (committed: a5685f7)
- TimelineSource interface (frontend/src/lib/timeline.ts): RecordedTimelineSource from
  golden fixture ("Recorded replay — real data, departure 2022-01-15") and
  LiveTimelineSource (GET /api/v1/voyage/{id}/timeline). Live failure shows error, never
  silently swaps to recording. No live GPS claimed.
- Sim clock store (frontend/src/store/useSimClock.ts): starts at first t_utc; speeds
  1x/60x/600x/3600x; pause, seek slider; interpolation between steps; respects reduced motion.
- SimulatedPositionSource (frontend/src/lib/position.ts): PositionSource{subscribe, now}
  implementation; interpolation between steps; smoothed heading/SOG.
- Sail screen (frontend/src/screens/Sail.tsx): panels with ProvenanceBadge for lat/lon,
  SOG, COG, ice conc, wind, Hs; arrival ETA; per-waypoint ETAs; sim clock controls;
  empty state "Plan a route first"; 2D map synced to clock via MapStage/ChartViews.
- FE-4 (departure date-time + arrival ETA): UTC picker in Plan command bar; arrival ETA
  badge (departure + total_transit_hours); per-waypoint ETAs; backend stamps departure_iso,
  arrival_iso, waypoint_etas on /route/alternatives.
- Unit tests: frontend/tests/timeline.test.ts, position.test.ts, sim-clock.test.ts.
- E2e: frontend/e2e/sail.spec.ts (plan → sail → seek), etadisplay.spec.ts (FE-4).
- Evidence: typecheck PASS, unit tests 152/152 PASS, build PASS, Playwright PASS.
- Screenshots:
  - frontend/e2e/evidence-screenshots/taskB-sail.png (Sail screen with sim clock)
  - frontend/e2e/evidence-screenshots/taskD-etadeparture.png (FE-4 departure picker)

## STAGE C — DONE (committed: see below)
- 3D dependencies installed: three ^0.160.1, @react-three/fiber ^8.18.0, @react-three/drei ^9.122.0 (React 18 compatible)
- C1: Ocean (Gerstner-sum shader from Hs/Tp/wave_dir), sky (sun azimuth/elevation), ship (side third-person procedural hull)
- C2: iceMask() pure function (boolean floe grid matching SIC ±0.05), floes from path ahead
- C3: Sky/day-night cycle, ship in side third-person view
- Shared clock with 2D view via useSimClock
- 2D/3D toggle (ViewModeToggle)
- ThreeDee screen with error boundary
- ATTRIBUTIONS.md: procedural hull (no external asset)
- Evidence: typecheck PASS, unit tests 152/152 PASS, build PASS (chunk size warning only)
## STAGE D — PENDING

Compare URL: https://github.com/chico468/ICEFLOW/compare/main...voyage-bridge
