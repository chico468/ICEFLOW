# R0 data-coverage matrix

Real-data products consumable by the replay system. This matrix is the input to
`scripts/build_replay_pack` and the basis for approving a replay window. It is
kept in `docs/` for review; the machine-readable declaration lives in
`scripts/build_replay_pack.py` (`R0_COVERAGE_MATRIX`).

## Convention

- `kind`: provenance kind carried on every sample (`reanalysis`, `real-observation`, `derived`, `synthetic` — see `src/data/environment_provider.py` and `docs/SPRINT.md`).
- Never mix products in one sample: live uses G10016 V4 / ERA5, replay uses G02202 V6 / ERA5.
- No silent fallback from a real provider to `SimulatedProvider`; missing data raises `OutOfCoverage` naming the variable and date.

## Products

| Key | Product | Version | Variables | Native grid | Valid-time range | Provenance kind | Source / citation |
|-----|---------|---------|-----------|-------------|------------------|-----------------|-------------------|
| `era5_wind_10m` | ERA5 (reanalysis) | v1 (CDS `reanalysis-era5-single-levels`) | 10 m u/v wind | 0.25 deg lat/lon, reduced Gaussian | 1940-01-01 → present (reanalysis; ~5-day lag on latest) | `reanalysis` | Hersbach et al. 2023, C3S CDS, doi:10.24381/cds.bd0915c6 |
| `era5_waves` | ERA5 waves (reanalysis) | v1 (same CDS collection, separate file) | significant height of combined wind waves and swell | 0.25 deg lat/lon, wave grid | 1940-01-01 → present | `reanalysis` | Hersbach et al. 2023, C3S CDS, doi:10.24381/cds.bd0915c6 |
| `cmems_current` | CMEMS GLOBAL ANALYSISFORECAST PHY 001 024 | 0.083 deg (1/12 deg) | uo, vo (ocean current) | 1/12 deg global ocean | analysis+forecast, NRT (present; historical via reprocessing) | `reanalysis` | CMEMS, doi:10.48670/moi-00015 |
| `nrt_ice_concentration` | CMEMS SEAICE GLO SEAICE L4 NRT OBSERVATIONS 011 001 | L4 NRT | ice_conc | polar stereographic / 0.05 deg | NRT (present day) | `real-observation` | CMEMS/OSI-SAF, doi:10.48670/moi-00208 |
| `sic_replay` | NOAA/NSIDC CDR G02202 Version 6 | v06r00 | cdr_seaice_conc | NSIDC polar stereographic 25 km (EPSG:3412) | 1978-10-25 → present; sensor changes n07/F08/F11/F13/F17, AMSR2 (am2) from 2025-01-01 | `real-observation` | NSIDC G02202 V6 |

> Replay SIC override (per sprint step 1): replay sea ice comes from **G02202 V6**, not the CMEMS NRT layer. The matrix row `nrt_ice_concentration` is the live/NRT path only.

## Iceberg observations (context, not part of the replay pack)

| Product | Source | Range | Notes |
|---------|--------|-------|-------|
| USNIC Antarctic iceberg snapshot | `data/raw/iceberg/AntarcticIcebergs_YYYYMMDD.csv` | file-date dependent | observed-by-default icebergs API |
| BYU/NIC consolidated track | `data/raw/iceberg/consolidated_database_v6.zip` | tracks end **2022-12-31** | nearest-at-or-before `at`, Julian-day `YYYYDDD`; a berg with no on-or-before observation is omitted, never invented |

## Replay-window coverage check (candidate: January 2022)

The candidate replay window is **January 2022** (user candidate). Coverage:

- G02202 V6 SIC: covers January 2022 (record 1978-10-25 → present). ✅
- ERA5 wind + waves: covers January 2022 (reanalysis 1940 → present). ✅
- CMEMS current (uo/vo): January 2022 historical current requires the reprocessed/analysis product; confirm the NRT dataset alone is insufficient for a historical window and use the appropriate historical CMEMS product or confirm availability. ⚠️ confirm
- BYU iceberg tracks: January 2022 is within the track record (ends 2022-12-31). ✅ and it falls inside the untouched SIC test period (test years: [2024], train through 2023).

**Approve or adjust the replay window before step 1 (build_replay_pack).** Do not build the pack until the window is approved.

## Notes

- Anonymous ARCO-ERA5 source (`gs://gcp-public-data-arco-era5`, token `anon`) is to be added to `build_replay_pack` in step 1; provenance must read "ERA5 via Google ARCO copy" and record the store's valid-time range. Not yet implemented in this branch.
- Currents and sea-ice velocity come from Copernicus Marine; login must succeed or the build fails loudly (verify credentials with `copernicusmarine --help` credential-check flag).
- Maximum inter-variable skew in replay: 12 h. Waves missing under ice return `None` with `wave_valid=False`, never 0.
