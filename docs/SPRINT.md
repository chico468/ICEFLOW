# ICEFLOW Sprint specification

## Data provenance contract

Every response that carries modelled environmental data labels itself per data
layer (principle P2: honest labelling). The provenance `status` field is a
string union. Consumers (backend, frontend) must handle every kind; unknown
kinds are treated as `string` and displayed as-is.

### Provenance kinds

| Kind | Meaning | Where it is used |
|---|---|---|
| `real` | Directly measured, unprocessed observation | Observed iceberg snapshot (`src/data/observed_icebergs.py`) |
| `real-seed` | Observed data used to seed a model (not the model output itself) | Iceberg catalogue seed positions |
| `real-observation` | NRT observational product (e.g. OSI-SAF ice concentration) | NRT sea-ice concentration layer |
| `reanalysis` | Reanalysed historical data (e.g. ERA5) | ERA5 wind and waves in `ReplayProvider` |
| `derived` | Computed from one or more real sources (e.g. wind speed from u/v) | Derived scalars in `EnvSample` |
| `synthetic` | Seeded simulated stand-in | `SimulatedProvider` wrapping `EnvironmentModel` |

### Frontend handling

`frontend/src/api/types.ts` declares the union in `Provenance.status`:

```ts
status: 'real' | 'real-seed' | 'real-observation' | 'reanalysis' | 'derived' | 'synthetic' | string;
```

The map console and the health endpoint render `status` alongside `source` and
`note` so a reviewer can tell which numbers came from the world. No kind may be
silently remapped to another: `reanalysis` is not `real`, `derived` is not
`observation`, and `synthetic` is never substituted for a real source.

### Backend enforcement

`src/data/environment_provider.py` defines `EnvironmentProvider`, a runtime
protocol with three implementations:

- `ReplayProvider` — reads a replay pack (ERA5 reanalysis waves/wind, CMEMS
  current, NRT ice). `provenance_by_variable` carries `kind: "reanalysis"` or
  `"real-observation"` per variable.
- `LiveProvider` — live GFS + CMEMS forecast + NRT ice with a 14-day walk-back.
- `SimulatedProvider` — wraps `EnvironmentModel`, `is_synthetic=True`, only for
  `environment_mode="simulated"`.

Rules enforced in code and tests:

- Bilinear in space (antimeridian and polar wrapping handled).
- Linear in time between bracketing valid times.
- No extrapolation: `OutOfCoverage` names the variable and date.
- Maximum inter-variable skew of 12 h in replay.
- Waves missing under ice return `None` with `wave_valid=False`, never 0.
- No silent fallback from a real provider to `SimulatedProvider`.

## Icebergs API (observed by default)

`GET /api/v1/icebergs` returns **observed** icebergs by default (principle P2: the default path
shows real data, not simulated seeds):

- **Source**: the USNIC-format snapshot in `data/raw/iceberg/AntarcticIcebergs_YYYYMMDD.csv`
  (`src/data/observed_icebergs.py`), plus the BYU/NIC consolidated track (`src/ml/iceberg_dataset.py`)
  when a target time `at` is given.
- **BYU nearest-at-or-before-t0**: for `GET /api/v1/icebergs?at=<ISO>`, each berg is the latest
  observation at or before `at`. Source dates are Julian days `YYYYDDD`, parsed exactly — no
  approximate or interpolated matching. A berg with no on-or-before observation is omitted; a berg
  is never invented.
- **Each entry**: `id`/`berg_id`, `latitude`, `longitude`, `last_obs`, `age_days`, size
  `length_nm`/`width_nm` (nautical miles), and `provenance: "observed"`.
- **Forecast**: `lead_hours > 0` integrates each berg forward with the RK4 drift model and returns
  `forecast_latitude`/`forecast_longitude` with `kind: "real_forecast"` and `radii_nm`.
- **Simulated mode**: `GET /api/v1/icebergs?mode=simulated` returns the seeded catalogue
  (`src/data/icebergs.py`, `provenance: "iceberg_catalogue"`). The old catalogue is simulated-mode
  only; it is no longer the default path.

## Sprint plan & tasks (merged from origin/main)

Goal: honest real-data demo for SIH26059: forecast Antarctic sea-ice concentration (SIC), predict iceberg drift, route research vessels.
Rules: AGENTS.md applies. One branch per task, PR to main, CI green before merge, raw output as evidence. Contract below is binding; changes are additive only.

### Shared contract (update backend pydantic models and frontend/src/api/types.ts together)
Provenance = {layer, kind: "observed"|"real_forecast"|"simulated"|"experimental_ml"|"real-seed", source, product?, valid_time (UTC iso), age_hours|null}
Every new or changed response carries `provenance: Provenance[]`. The frontend evidence badges render from it.

### Provenance kinds actually in use
- `"observed"` — real NSIDC G02202 V6 sea-ice concentration (real_ice / replay modes with a cached observation). `src/core/provenance.py:observed_provenance`.
- `"simulated"` — synthetic sea-ice field or Southern-Ocean atmosphere/ocean forcing. `simulated_provenance` and `build_provenance`. This is also what `real_ice` is reduced to when no cached observation exists (the fall-back is explicit: `is_synthetic_environment=true` and the sea-ice layer kind is `"simulated"`, never `"observed"` — see `_load_observed_ice` / `build_provenance` `has_observed_ice`).
- `"real-seed"` — **additional kind kept from the contract**. The iceberg catalogue is not an observation of position: real iceberg names and calving origins (`src/core/constants.py` `DATA_PROVENANCE["iceberg_catalogue"]["status"]="real-seed"`) whose positions are seeded then propagated by the RK4 drift model. It must be rendered neither as a real observation nor as synthetic — the frontend must treat it as a distinct `real-seed` class.
- `"real_forecast"` and `"experimental_ml"` are declared in the `ProvenanceKind` Literal (`src/core/provenance.py:14`) but are not emitted yet. `real_forecast` is reserved for the SIC forecast product (BE-2) and `experimental_ml` for the per-lead residual model (BE-2); both must appear here once those models are promoted.

Where the frontend must handle `real-seed` (no edit required — already additive in `frontend/src/api/types.ts`):
- `frontend/src/api/types.ts:12` `Provenance.status` union includes `'real-seed'`.
- `frontend/src/components/ProvenanceBar.tsx:62` filters `real-seed` entries separately from `synthetic` and from genuine `real` observations, so a seeded iceberg is never mis-badged as an observed position.
- `src/api/main.py` health response `data_provenance` (and `frontend/src/api/types.ts:133` `HealthResponse.data_provenance`) surfaces `iceberg_catalogue` with status `real-seed`.

GET /api/v1/evidence/scorecard -> {generated_at, git_sha, data_source: "real"|"none", product, version, train_years, test_years, rows: [{task: "sic"|"iceberg", lead_days, domain, season, model, rmse|error_km, ci: [lo, hi], skill_vs_baseline, n}], promoted: {sic: {"3": {"promoted": bool|null, "model": "gbm_residual"}, ...}, iceberg: {"1": {"promoted": bool|null, "model": "residual_ml"}, ...}}, coverage: {lead_days: {target: 0.9, empirical}}, caveats: [str]}
GET /api/v1/forecast/sic?lead_days=1..14 -> the existing ice-field grid type plus {mean, lo, hi, model: "damped_persistence"|"gbm_residual", model_version, issued_from_date, valid_date, provenance}
GET /api/v1/icebergs/forecast?name=&lead_days= -> {name, last_obs: {lat, lon, date, source}, predicted: {lat, lon}, radius_km: {p50, p90}, model, provenance}
Voyage plan (existing endpoint): request adds {departure_iso (UTC), environment_mode: "simulated"|"real_ice"|"replay", replay_date?}; response adds {departure_iso, arrival_iso, waypoint_etas: [{index, eta_iso}], environment_mode, provenance}. arrival = departure + total_transit_hours (UTC primary, ship-local secondary). First check what the plan request already accepts (departure_time_hours, departure_iso) and extend, do not duplicate.

### Backend tasks
BE-1 Verify Stage 2. Print the variable-ice-zone table (5-95% train climatology), per lead, all-season and Nov-Mar, with 95% CIs, n and IIEE, plus the Indian Ocean sector. Explain why "persistence lead 7" is 0.2223, 0.0821 and 0.0844 in three places (domain, dates, cells). Fix if inconsistent. Done when the tables are pasted and consistent.
BE-2 SIC model. Branch stage-3-ml. Baseline to beat: damped-anomaly persistence with tau tuned per lead on 2005-2019 (not fixed 30). Splits: train 2005-2019, val 2020-2021 (early stopping and conformal calibration), test 2022-2024 untouched until frozen; 14-day embargo between blocks. Model: HistGradientBoostingRegressor per lead (3, 7, 14) predicting residual vs the tuned baseline. Features, SIC-only: SIC at t0, anomaly vs train climatology, SIC change over 1/3/7 days, 3x3 and 7x7 neighbourhood means, climatology at target date, sin/cos day-of-year, sin/cos longitude, latitude, sector id. Rows: all variable-ice-zone cells from a random 10% of training days plus a small sample of other cells; training under 30 min. Uncertainty: split conformal on validation residuals, stratified by lead and forecast-concentration bin, 90% intervals clipped to [0,1]; report empirical coverage on 2022-2024 overall, per season, per sector. Promotion gate in code: promoted for a lead only if RMSE beats the tuned baseline with the CI of the difference excluding zero, in BOTH all-season and Nov-Mar, on the variable-ice zone. Sensor check: also evaluate on 2025-01 to latest V6 days (AMSR2 era, about 650 files) and report separately; training data is SSMIS-era. Registry: ml_status shows trained_on "real", report path, per-lead promoted, coverage. Artifacts (*.joblib) stay out of git; metadata JSON committed.
BE-3 Icebergs. Data: BYU/NIC consolidated Antarctic iceberg database v6 (daily positions, one file per iceberg, ~3.5 MB zip, to 2022-12-31; page ftp.mers.byu.edu/data/iceberg/database1.html). FIRST inspect the zip and report columns, units, date coverage and iceberg count before writing code. Keep only moving segments (drop grounded: speed below a threshold you justify). Split by iceberg ID and time (train to 2018, test 2019-2022). Leads 1, 3, 7 days. Baselines: (a) no movement, (b) constant velocity from the last 3 days, (c) from the last 7 days damped. ML residual on velocity only if it beats (b) under the same gate (CI by iceberg). Radii p50/p90 from empirical error quantiles. Metric: great-circle error km, median and p90.
BE-4 API per the contract; scorecard builder reads models/eval/*.json (only reports whose metadata says data_source "real"); fixtures for tests; no network in tests.
BE-5 Real-ice routing. Find how the route optimizer gets ice concentration. Add environment_mode "real_ice" (latest observed field; live path uses the near-real-time product, walks back at most 14 days, labels the date) and "replay" (observed V6 field for replay_date). Wind and waves stay simulated and are labelled simulated in provenance. POLARIS constraint unchanged. Done when: Cape Town to Bharati with replay_date 2024-01-15 returns arrival_iso and provenance within 60 s; test with fixtures.
BE-6 README evidence section from the real reports; clean-clone CI green; no fixture reports in models/eval.

### Frontend tasks (frontend/src and frontend/e2e only)
FE-0 Sea-ice overlay renders correctly (details from the owner's screenshot). FE-1 theme and tokens: keep existing --c-* names, navy/white/ice-blue brand, data colours untouched, no raw hex outside tokens, palette.ts in sync. FE-2 side docks (left layers, right inspector), update layout tests for widths. FE-3 ProvenanceBadge component (kind and age) used on every number or layer, plus a Scorecard screen from /evidence/scorecard, built first against a fixture JSON. FE-4 departure date-time picker (UTC plus ship-local) and arrival ETA plus per-waypoint ETAs; bounded to the forecast horizon, else replay mode only; reuse lib/environmentTime.ts. FE-5 ship animation: time-based interpolation between ticks, smoothed heading, speed and seek controls, respect reduced motion. FE-6 replay date selector and uncertainty bands (lo/hi). FE-7 stretch: terrain toggle (Mapbox Terrain-DEM, elevation only, works only in Mapbox GL JS; fails gracefully; the canvas map stays the fallback).

### Gates
Tue 18:00 BE-2 numbers in and FE-1/FE-2 merged. Wed 12:00 decide wind (ERA5 via CDS, needs the owner's token) and iceberg ML go/no-go. Wed 18:00 API live and FE-3 wired. Thu 18:00 BE-5 and FE-4/FE-5 merged. Fri 14:00 freeze.

## Voyage timeline API (PHASE 2)

`GET /api/v1/voyage/{id}/timeline?step_min=10` (gzip via `GZipMiddleware`, size-capped by `step_min`).

Response shape (top-level keys: `voyage_id`, `step_min`, `n_steps`, `not_available`, `steps`):

Each step carries:
- `t_utc` (ISO), `lat`, `lon`, `sog_kn`, `cog` (course over ground from previous fix), `heading`
- `ice_conc` (sea-ice concentration)
- `wind_u`, `wind_v` (m/s, derived from speed + FROM-direction)
- `hs` (significant wave height, m; `null` under ice), `tp` (not available -> `null`), `wave_dir`
- `current_u`, `current_v` (not available -> `null`)
- `nearby_bergs`: [{name, lat, lon, length_nm, width_nm, age, kind}] (observed catalogue, never invented)
- `alerts`: active alert codes at the tick
- `sun_azimuth_deg`, `sun_elevation_deg` (astronomical algorithm, `src/core/solar.py`)
- `provenance_by_variable`: {var: {kind, source, product, valid_time, age_hours}}

`not_available` lists every variable omitted because the data cannot supply it (e.g. `tp`,
`current_u`, `current_v`, `nearby_bergs`, `cog` on the first step).

### Provenance conventions: legacy `status`/`note` vs `kind`/`age_hours`

Two provenance representations coexist:

- **Legacy `Provenance` pydantic model** (`src/core/provenance.py`): fields `layer`, `kind`,
  `source`, `product`, `valid_time`, `age_hours`, `note`. Emitted by `VoyageState.provenance`
  (route plan) and `build_provenance`. `kind` is a `ProvenanceKind` literal
  (`observed` \| `real_forecast` \| `simulated` \| `experimental_ml` \| `real-seed`).
- **Per-variable `provenance_by_variable`** (`EnvSample`, `src/data/environment_provider.py`):
  maps variable name -> {kind, source, product, valid_time, age_hours}. Emitted on every
  timeline step. No `note` field; kind uses the same literal set plus `"synthetic"` for the
  `SimulatedProvider`.

Endpoints emitting **legacy `status`/`note`-style provenance**: `GET /api/v1/voyage`
(`VoyageState.provenance` with `note`), `GET /api/v1/health` (`data_provenance`).
Endpoints emitting **`kind`/`age_hours` per-variable provenance**: `GET
/api/v1/voyage/{id}/timeline` (`provenance_by_variable` on each step). Consumers must handle
both; unknown kinds render as-is.

Golden fixture: `frontend/e2e/fixtures/golden-voyage-timeline.json` (Cape Town -> Bharati
replay on 2022-01-15, 30-minute steps, under 5 MB) plus its manifest
`frontend/e2e/fixtures/golden-voyage-timeline.manifest.json`. Regenerated by
`scripts/export_golden_timeline.py` (no network; reads the cached replay pack).

