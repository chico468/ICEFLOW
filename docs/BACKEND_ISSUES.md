# BACKEND_ISSUES — Backend problems found from the frontend worktree

Found 2026-11-02. Each entry: endpoint, request, response, what is wrong. No workarounds
invented — problems are reported, never papered over with fabricated data.

## 1. Stale running backend process

- **Endpoint:** all of `/api/v1/`
- **Request:** `curl http://127.0.0.1:8199/<route>`
- **Response:** `{"detail":"No such endpoint: /api/v1/<route>"}` for some routes
- **What is wrong:** The demo backend running under this worktree is an older build
  (PID 9849, started 2026-11-01 17:21). Routes that exist in source are missing from the
  live process:
  - `/api/v1/evidence/scorecard` — exists at `src/api/routers/evidence.py:199`, not registered
  - `/api/v1/environment/coverage` — exists at `src/api/routers/copernicus_layers.py:525`, not registered
  - `/api/v1/voyage/{voyage_id}/timeline` — exists at `src/api/routers/voyages.py:197`, not registered
- Routes that DO work in the running process: `/health`, `/voyage`, `/voyage/{id}`, `/voyage/{id}/step`,
  `/environment/layers`, `/ice/point`, `/observations/sea-ice/point`, `/env/field`.
- **Not restarted** (FE_RULES §1: never start/stop/restart the demo backend).

## 2. `/api/v1/environment/coverage` returns 404

- **Request:** `GET /api/v1/environment/coverage`
- **Response:** `{"detail":"No such endpoint: /api/v1/environment/coverage"}` (HTTP 404)
- **What is wrong:** The route is defined in `src/api/routers/copernicus_layers.py:525`
  (`def environment_coverage() -> CoverageResponse`) but the router is included only once in
  `src/api/main.py:167` — the running process predates the route being registered.
- **Logged, not worked around.** The map does not call this endpoint; it calls
  `/api/v1/environment/layers` instead.

## 3. `/api/v1/evidence/scorecard` returns 404

- **Request:** `GET /api/v1/evidence/scorecard`
- **Response:** `{"detail":"No such endpoint: /api/v1/evidence/scorecard"}` (HTTP 404)
- **What is wrong:** Route defined at `src/api/routers/evidence.py:199`; the running process is
  stale (see issue 1). The frontend `Scorecard` screen shows "SAMPLE DATA, not real results"
  because the endpoint is unavailable — honest fallback, not a fabricated scorecard.

## 4. Mapbox token not set

- **Request:** runtime read of `VITE_MAPBOX_ACCESS_TOKEN`
- **Response:** empty string (`frontend/.env.example` has `VITE_MAPBOX_ACCESS_TOKEN=`; no
  `MAPBOX_*` env var exported)
- **What is wrong:** The regional map has no Mapbox token configured in this environment.
  Regional tiles fall back accordingly; no URL is invented.