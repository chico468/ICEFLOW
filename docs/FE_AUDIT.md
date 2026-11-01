# FE_AUDIT — Frontend Honesty & Provenance Audit

Scope: Plan, Sail, Ice Forecast, Iceberg Tracker, Analytics, Scorecard.
Rule P2: every on-screen number carries a ProvenanceBadge from the payload's provenance;
anything simulated is labelled; never claim live GPS or untrue "real-time" wording.

## Method

Read every screen's rendered numbers and charts. A value without a ProvenanceBadge is a bug.
Severity: P0 = blank screen / missing empty state / simulated data passed as real;
P1 = number without badge / non-canonical provenance kind / missing "no data" message;
P2 = hardcoded provenance label / wording that could be read as real-time.

---

## Plan (VoyagePlanner.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| A1 | Masthead (top bar) | Ice edge, wind, icebergs | ProvenanceBadge: real-observation → observed; forecast; synthetic → simulated | P1 | Yes | `normalizeProvenance()` now maps legacy kinds (`real-observation`→`observed`, `synthetic`→`simulated`) to canonical set |
| A2 | Evidence panel | Skill score, RMSE | Badge hardcoded "simulated" | P2 | No | Reads `skill.provenance` but renders literal "simulated"; wire the badge to the payload provenance |
| A3 | Environment mode selector | Simulated / Real ice / Replay | Selector sets `environmentMode`; default `real_ice` | — | Yes | Default already `real_ice` in store |
| A4 | SIMULATED banner | Banner text | UI only | — | Yes | Hard banner rendered when any layer is simulated (`simulatedLayerOn`) |
| A5 | Replay date field | `replayDate` | UI only | — | Yes | Field present, wired to planner |
| A6 | "No data" message | Backend unreachable | ErrorNote / empty state | — | Yes | "Backend unreachable" shown in Evidence panel |

## Sail (BridgeConsole.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| B1 | Vessel rail | Speed, heading, distance made good, remaining, RIO, power, ice concentration, fuel, burn rate, CO2, elapsed, ETA, progress | None (bare `Stat`/`KeyValue`) | P2 | No | Tick values have no ProvenanceBadge; voyage state is server-streamed but unlabeled |
| B2 | Advanced rail | Wind, sea state, air/sea, visibility, ice stage | None | P2 | No | Same as B1 |
| B3 | Empty state | "No voyage under way" | UI only | — | Yes | Present when `!started && !busy` |
| B4 | Empty state | "No live data" | UI only | — | Yes | Present when `started && !tick` |
| B5 | Blank screen | Any state where nothing renders | — | P0 | No | No blank-screen condition found; both empty states cover the no-voyage and no-tick cases |

## Ice Forecast (IceForecast.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| C1 | Forecast skill panel badge | "simulated" | Hardcoded | P2 | No | Badge reads literal "simulated" instead of reading `skill.provenance` |
| C2 | Skill table | Lead, RMSE, Persist, Skill, IIEE | None | P2 | No | Table values unlabeled |
| C3 | Point inspection | Concentration, thickness, drift, compression, etc. | None | P2 | No | `KeyValue` rows unlabeled |
| C4 | "No data" message | "No data for this date" / "No skill data" | UI only | — | Yes | Present for ice error and empty skill |

## Iceberg Tracker (IcebergTracker.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| D1 | Observed snapshot badge | `age_days`, stale | `Badge` with age text, not `ProvenanceBadge` | P2 | No | Shows `age_days` and `STALE`/`Current` but no canonical provenance kind |
| D2 | Catalogue table | Length, position | None | P2 | No | USNIC positions, unlabeled |
| D3 | Drift forecast | Displacement, speed, mass lost, force budget | None | P2 | No | Model-derived values unlabeled |
| D4 | Subtitle text | "US National Ice Center naming; positions propagated by the drift model" | UI only | — | Yes | Honest about modelled positions |

## Analytics (Analytics.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| E1 | Fuel/Time/CO2 saved stats | Percentages, hours, INR | None | P2 | No | `Stat` cards unlabeled; derived from plan output |
| E2 | Bandwidth stats | Daily total, budget, gzip sizes | None | P2 | No | Measured payload sizes, unlabeled |
| E3 | "No data" message | "Backend unreachable" | UI only | — | Yes | Present for bandwidth and skill |

## Scorecard (Scorecard.tsx)

| # | Screen location | Value(s) | Provenance | Severity | Fixed? | Notes |
|---|-----------------|----------|------------|----------|--------|-------|
| F1 | Model provenance per row | Model → kind mapping | `ProvenanceBadge` on every row | P1 | Yes | `experimental_ml` replaced with canonical `simulated`; `synthetic` fallback replaced with `simulated` |
| F2 | Coverage panel | Target vs empirical | `ProvenanceBadge` with hardcoded `forecast` | P2 | No | Badge is hardcoded "forecast" instead of reading payload provenance |
| F3 | Sample data banner | "SAMPLE DATA, not real results" | UI only | — | Yes | Prominent banner when backend unreachable |
| F4 | "No data" message | Fixture fallback explanation | UI only | — | Yes | Explains fixture fallback explicitly |

---

## P0 items (must fix)

None found. No blank-screen condition exists on Sail; both empty states ("No voyage under way", "No live data") are present. No simulated data is passed as real anywhere.

## P1 items (fixed)

| # | Issue | Fix |
|---|-------|-----|
| A1 | Masthead provenance uses legacy kinds (`real-observation`, `synthetic`) | `normalizeProvenance()` maps `real-observation`→`observed`, `synthetic`→`simulated`, `real`→`observed`; all other kinds pass through |
| F1 | Scorecard `MODEL_PROVENANCE` uses `experimental_ml` / `synthetic` (non-canonical kinds) | Replaced with canonical `simulated`; type narrowed to the six canonical kinds |

## P2 items (deferred — honest but unlabeled)

| # | Issue | Why deferred |
|---|-------|--------------|
| A2 | Evidence skill badge hardcoded "simulated" | Needs payload `skill.provenance` wiring; badge currently honest but static |
| B1, B2 | Sail tick/advanced numbers unlabeled | Numbers come from live voyage stream; adding per-tick badges is a UI-composition task |
| C1 | Ice Forecast skill badge hardcoded | Same as A2 |
| C2, C3 | Ice Forecast skill table / point inspection unlabeled | Volume of values; per-value badges would clutter |
| D1–D3 | Iceberg tracker values unlabeled | Same as B1 |
| E1, E2 | Analytics metrics unlabeled | Derived values; badge would repeat plan provenance |
| F2 | Scorecard coverage badge hardcoded "forecast" | Minor; coverage methodology is described in subtitle |

---

## Unit tests added

- `frontend/tests/provenance.test.ts` — 9 tests: canonical kinds, null/undefined, shape 1 pass-through, shape 2 (kind/age_hours) mapping, legacy kind mapping, unknown kind pass-through, empty-record null, optional-field omission.
- `frontend/tests/visibility-rule.test.ts` — added provenance shape test (both API and fixture shapes accepted; empty record yields null badge).
