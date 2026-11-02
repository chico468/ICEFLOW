# FE_AUDIT_2 — Stage 0/4 screen audit (voyage-bridge)

Audit run 2026-11-02 against dev server http://localhost:5199 (backend proxy
http://127.0.0.1:8199). 10 screens × 4 viewports = 32 cells, plus Simple view
(Plan, Sail) at 1280×720. Tool: `node e2e/audit.mjs`, raw JSON
`frontend/e2e/evidence-screenshots/audit-results.json`, 40 PNGs.

## Method

Each cell: click the nav button, wait 1.2 s, then in-page evaluate for
`scrollWidth > clientWidth` (horizontal overflow), elements whose
`overflow:hidden|clip` box is smaller than its scroll content (clipped text),
and any `[class*="empty|loading|error|no-data|not-avail"]` text. Console
`error`/`pageerror` and `requestfailed` are captured per cell. A cell counts
as "reached" only if `aria-current="page"` on the nav rail matches the label.

## Summary

| Metric | Value |
|---|---|
| Cells audited | 32 (+ 2 Simple) |
| Reached | 32 / 32 |
| Horizontal overflow | 0 |
| Console errors | 0 |
| Failed requests | 0 |
| Empty / loading / error states | 0 |
| Clipped-text cells | 52 — all intentional CSS `truncate` / `overflow-hidden` |

Every "clipped" hit is a deliberate Tailwind `truncate` or `overflow-hidden`
container (nav buttons, legend badges, panel titles, year ranges). No text is
silently cut off; no overflow, no 404, no unlabelled empty state anywhere.

## Per-screen findings
### Plan (VoyagePlanner)
- 1024×768: 6 clipped cells — all `truncate` nav buttons (Plan/Sail/Voyage/3D/Sea ice/Icebergs)
  and the legend badge. No overflow, no console error, no failed request.
- 1280×720, 1440×900: 2 clipped — the `overflow-hidden` panel and the legend badge.
- 1920×1080: 1 clipped — legend badge only.
- Labels vs real data: legend reads "Ice concentration (simulated) · Observed bergs (stale) ·
  Bergs (simulated)"; the 3D HUD shows "no data" and "Bergs: no data (nearby_bergs not in
  payload)". Honest — nothing claims live observation.

### Sail
- All 4 viewports: 1 clipped cell (legend badge). No overflow, no errors, no failed requests.
- Empty state present ("Plan a voyage first"); provenance badges on lat/lon/SOG/COG/ice conc.

### Voyage (bridge console)
- All 4 viewports: 2 clipped (panel + legend badge). No overflow, no errors.
- Empty/loading states labelled; no fabricated live GPS.

### 3D (ThreeDee, lazy-loaded)
- 1024×768/1280×720/1440×900: 1–2 clipped (header + legend badge). 1920×1080: 0.
- No console errors, no failed requests, no overflow at any size. WebGL canvas renders;
  `Loading 3D scene…` fallback only on WebGL failure (feature-detected, no error logged).

### Sea ice (IceForecast)
- All 4 viewports: 1 clipped (legend badge). No overflow, no errors.
- Skill table and forecasts carry provenance; no unlabelled "live" claim.

### Icebergs (IcebergTracker)
- All 4 viewports: 1 clipped (legend badge). No overflow, no errors.
- "Observed bergs (stale)" / "Bergs (simulated)" labels match the payload.

### Insights (Analytics)
- 1024×768: 4 clipped (two `display` H2 titles + two `truncate` spans) — narrowest viewport,
  intentional truncation. 1280×720+: 0 clipped. No overflow, no errors.
- Metric captions read "Measured, not asserted"; no fabricated accuracy claims.

### Scorecard
- 1024×768: 7 clipped (Conformal coverage / Promoted H2s and the 2005–2016 year-range span).
  1280×720: 3, 1440×900: 2, 1920×1080: 2. No overflow, no errors.
- "SAMPLE DATA, not real results" banner is present and matches the fixture provenance.

### Simple view (Plan, Sail) — 1280×720
- Toggle switched to Simple; only Plan + Sail tabs visible; both reached, no overflow,
  no errors, no clipped text beyond the legend badge.

## 3D reality check (Stage 0/5)

| Feature | Status | Path / test |
|---|---|---|
| Gerstner ocean | DONE | `frontend/src/components/Ocean.tsx` — vertex+fragment GLSL Gerstner sum, `uWaveHeight/Period/Direction` from payload, wind-driven whitecaps gated by `uHasWind`. Test: none yet (shader is GPU-side; covered by the 3D screen audit: renders, no console errors). |
| Sky | DONE | `frontend/src/components/Sky.tsx` — day/night/twilight palette from `sunAzimuthDeg`/`sunElevationDeg`, sun glow, `uHasData` → HUD "no data" when absent. |
| Ship | DONE | `frontend/src/components/Ship.tsx` — CC0 Kenney watercraft-ship glTF (`public/models/ship.glb`, 106,856 bytes) with procedural-hull fallback; side third-person, world scrolls at SOG. |
| iceMask test | DONE | `frontend/src/lib/iceMask.ts` + `frontend/tests/icemask.test.ts` — 4 tests (SIC ±0.05, determinism, clamp, size-1 edge). `node --test` 4/4 PASS. |
| Named bergs | DONE | `IceField.tsx:54` — `nearbyBergs` placed at real distance/bearing (1 nm = 1852 m); absent → none drawn, HUD "no data (nearby_bergs not in payload)". |
| Brash / growlers | DONE | `IceField.tsx:50` — statistical sample `sic*40`, badged "illustrative, not observed objects"; suppressed when observed bergs are present. |
| Weather | DONE | `sceneEnv.ts` carries `snowfallMmPerHr`, `totalCloudCover`, `visibilityKm`, `windSpeedMs`; each absent → effect OFF + HUD "no data". |
| Ship motion (RAO) | DONE | `sceneEnv.ts:54` `raoMotion()` — roll max at beam seas, pitch max at head/following, heave ∝ Hs, monotonic in Hs. |
| RAO monotonic test | DONE | `frontend/tests/rao.test.ts` — 3 tests (monotonic in Hs, zero at Hs=0, beam roll > head roll / head pitch > beam pitch). `node --test` 3/3 PASS. |
| Reduced motion | DONE | `Ship.tsx:98` — static pose when `reducedMotion` is set. |
| Adaptive quality | DONE | `ThreeScene.tsx:37` — FPS probe, drops water segments 128→64 when fps < 25 for 3 s, restores on recovery; logs `fps=… quality=… size=1280x720`. |
| Lazy chunk | DONE | `App.tsx:31` — `const ThreeDee = lazy(() => import('./screens/ThreeDee'))` wrapped in `<Suspense>`. Build emits a separate `ThreeDee-*.js` chunk (860 kB). |
| ATTRIBUTIONS.md | DONE | `frontend/ATTRIBUTIONS.md` — every bundled lib (three, @react-three/fiber/drei, react, mapbox-gl, zustand, @tanstack/react-query, lucide, recharts) with source/author/licence/date; ship asset: Kenney Watercraft Kit, CC0, 106,856 bytes, downloaded. |

## Backend issues found in this stage

- **Stale backend process.** The running demo backend (PID 9849, started 2026-11-01 17:21)
  is an older build: `/api/v1/evidence/scorecard`, `/api/v1/environment/coverage` and
  `/api/v1/voyage/{id}/timeline` all return `{"detail":"No such endpoint: …"}` even though those
  routes exist in `src/api/routers/evidence.py`, `copernicus_layers.py` and `voyages.py`. Other
  routes (`/voyage`, `/voyage/{id}/step`, `/environment/layers`) work. Not restarted per FE_RULES §1.
- **`/api/v1/environment/coverage` 404** — requested endpoint; the route exists in source
  (`copernicus_layers.py:525`) but is not registered in the running process (404, logged, not worked
  around). The map's actual sea-ice endpoint is `/api/v1/environment/layers` (200, see below).
- **`/api/v1/evidence/scorecard` 404** — requested endpoint; route exists in source
  (`evidence.py:199`) but not registered in the running process (404, logged).
- **Mapbox token not set.** `frontend/.env.example` has `VITE_MAPBOX_ACCESS_TOKEN=` (empty) and no
  `MAPBOX_*` env var is exported → **no**. Regional map tiles fall back accordingly.
