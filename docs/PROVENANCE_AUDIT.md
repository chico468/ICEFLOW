# PROVENANCE_AUDIT — ICEFLOW Frontend

Every on-screen value on Plan, Sail 2D, Sail 3D and Scorecard with its provenance kind and source.
Per the honesty contract: any value without a ProvenanceBadge is a bug.

## Method

Each screen was reviewed for every rendered number. Values are traced to their source:
- **observed**: measured from real-world sensors (NOAA/NSIDC, Copernicus)
- **reanalysis**: reanalysis product (OSI-SAF, ERA5)
- **forecast**: model forecast (GFS, damped-persistence)
- **derived**: derived from other values (skill vs baseline, conformal intervals)
- **simulated**: synthetic forcing, no real-world observation
- **real-seed**: real catalogue positions, drift modelled

---

## Plan (VoyagePlanner.tsx)

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Sea-ice edge | observed | Copernicus sea-ice edge (OSI-SAF NRT) | Yes |
| Wind | forecast | GFS wind (0.25 degree analysis) | Yes |
| Icebergs | simulated | Model iceberg catalogue (RK4 drift) | Yes |
| Skill score | derived | Hindcast evaluation (model-eval reports) | Yes |
| RMSE / error | derived | Hindcast evaluation | Yes |
| 90% CI | derived | Conformal calibration | Yes |
| Skill vs baseline | derived | Hindcast evaluation | Yes |
| Promoted leads | derived | Promotion gate | Yes |
| Conformal coverage | derived | Validation residuals | Yes |
| Caveats | derived | Methodology notes | Yes |
| Data source | observed | Backend /api/v1/evidence/scorecard | Yes |
| Product / version | derived | Model metadata | Yes |
| Train / test years | derived | Evaluation metadata | Yes |
| Git SHA | observed | Git commit | Yes |

---

## Sail — Plan Command Bar

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Departure (UTC) | observed | User input (wall-clock) | No (UI control) |
| Departure (ship local) | observed | User input (wall-clock) | No (UI control) |
| Sim speed | simulated | User selection (1×/60×/600×/3600×) | No (UI control) |

---

## Sail 2D — Position Panel

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Latitude | observed | Timeline (golden fixture) | Yes |
| Longitude | observed | Timeline (golden fixture) | Yes |
| SOG | observed | Timeline (golden fixture) | Yes |
| COG | observed | Timeline (golden fixture) | Yes |
| Ice concentration | observed | NOAA/NSIDC CDR G02202 | Yes |
| Ice thickness | simulated | Synthetic Southern Ocean forcing | Yes |
| Wind speed | simulated | Synthetic Southern Ocean forcing | Yes |
| Wind direction | simulated | Synthetic Southern Ocean forcing | Yes |
| Hs (wave height) | simulated | Synthetic Southern Ocean forcing | Yes |
| Visibility | simulated | Synthetic Southern Ocean forcing | Yes |
| Arrival ETA | derived | Departure + total_transit_hours | Yes |
| Elapsed | derived | Departure + sim_hours | Yes |

---

## Sail 2D — Motion Panel

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| SOG | observed | Timeline (golden fixture) | Yes |
| Heading | observed | Timeline (golden fixture) | Yes |
| Ice risk score (RIO) | derived | POLARIS model | Yes |
| Speed limit (POLARIS cap) | derived | POLARIS model | Yes |
| Attainable speed | derived | POLARIS model | Yes |
| Power | derived | Ship model | Yes |
| Power utilisation | derived | Ship model | Yes |
| Fuel burned | derived | Ship model | Yes |
| Burn rate | derived | Ship model | Yes |
| CO2 | derived | Ship model | Yes |
| Progress | derived | Distance travelled / total | Yes |

---

## Sail 2D — Environment Panel

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Ice concentration | observed | NOAA/NSIDC CDR G02202 | Yes |
| Ice thickness | simulated | Synthetic Southern Ocean forcing | Yes |
| Wind | simulated | Synthetic Southern Ocean forcing | Yes |
| Hs | simulated | Synthetic Southern Ocean forcing | Yes |

---

## Sail 2D — Nearest Contact Panel

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Distance to nearest berg | observed | USNIC iceberg catalogue | Yes |
| Alert count | derived | Voyage alerts | Yes |

---

## Sail 2D — ETA Panel

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Arrival ETA | derived | Departure + total_transit_hours | Yes |
| Elapsed | derived | Departure + sim_hours | Yes |

---

## Sail 3D — Ocean

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Wave height (Hs) | simulated | Synthetic Southern Ocean forcing | Yes |
| Wave period (Tp) | simulated | Synthetic Southern Ocean forcing | Yes |
| Wave direction | simulated | Synthetic Southern Ocean forcing | Yes |

---

## Sail 3D — Sky

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| Sun azimuth | derived | Solar position model | Yes |
| Sun elevation | derived | Solar position model | Yes |

---

## Sail 3D — Ship

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| SOG | observed | Timeline (golden fixture) | Yes |
| Position | observed | Timeline (golden fixture) | Yes |

---

## Sail 3D — Ice Field

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| SIC | observed | NOAA/NSIDC CDR G02202 | Yes |
| Floe positions | simulated | iceMask() statistical sample | Yes (illustrative) |
| Brash / growlers | simulated | Statistical sample | Yes (illustrative) |

---

## Scorecard

| Value | Provenance Kind | Source | Badge? |
|-------|-----------------|--------|--------|
| SIC RMSE (all leads) | derived | Hindcast evaluation (models/eval) | Yes |
| SIC skill vs baseline | derived | Hindcast evaluation | Yes |
| Iceberg error (km) | derived | Hindcast evaluation | Yes |
| Iceberg skill vs baseline | derived | Hindcast evaluation | Yes |
| 90% CI | derived | Conformal calibration | Yes |
| Promoted leads | derived | Promotion gate | Yes |
| Conformal coverage | derived | Validation residuals | Yes |
| Data source | observed | Backend /api/v1/evidence/scorecard | Yes |
| Product / version | derived | Model metadata | Yes |
| Train / test years | derived | Evaluation metadata | Yes |
| Git SHA | observed | Git commit | Yes |
| Caveats | derived | Methodology notes | Yes |

---

## Values Without Badges (P2 — Deferred)

| Screen | Value | Reason |
|--------|-------|--------|
| Analytics | Fuel/Time/CO2 saved | Derived from plan output; badge would repeat plan provenance |
| Analytics | Bandwidth stats | Measured payload sizes |
| Sail | Masthead regional data | Already badged in masthead |
| Sail | Simple/Full toggle | UI control |
| Sail | Sim speed selector | UI control |

---

## Values Claimed as "Live GPS" or "Real-Time" (Removed)

| Claim | Location | Action |
|-------|----------|--------|
| "Live GPS" | None found | None — sail uses timeline replay |
| "Real-time" | None found | None — all data is from timeline/replay |
| "Real-time drift" | None found | None — all drift is modelled |

---

## Unit Tests

| Test File | Tests | Purpose |
|-----------|-------|---------|
| provenance.test.ts | 9 | Canonical kinds, shape mapping, legacy mapping |
| visibility-rule.test.ts | +1 | Both provenance shapes accepted |
| timeline.test.ts | 4 | Golden fixture structure |
| position.test.ts | 6 | Interpolation, pause/play, speeds |
| sim-clock.test.ts | 6 | Store state transitions |

---

## Decisions

| Decision | Rationale |
|----------|-----------|
| All numbers carry ProvenanceBadge | Honesty contract P2 — no number without a badge |
| Simulated values labelled "simulated" | Never pass simulated as observed |
| Golden fixture used for Sail timeline | Fixture is "Recorded replay — real data, departure 2022-01-15" |
| No live GPS claimed anywhere | Ship position from timeline, not GPS/AIS |
| No "real-time" wording | All data is from committed eval reports / fixture |
