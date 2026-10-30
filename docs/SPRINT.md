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

