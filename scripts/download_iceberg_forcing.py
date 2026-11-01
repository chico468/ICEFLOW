#!/usr/bin/env python
"""
Phase 4B — download REAL iceberg forcing (ERA5 wind + GLORYS current) for a
budget-capped set of contiguous forcing days.

Design
------
* ERA5 10 m wind (u10, v10) from the anonymous ARCO GCS store
  (gs://gcp-public-data-arco-era5), one contiguous full-day file per day-variable.
  ARCO serves whole days, so the "contiguous slice per time range" is one day file;
  the per-track corridor (+-3 deg) spatial subset is taken in memory when the field
  is loaded for RK4 (never per-point HTTP calls).
* Files are cached to disk under data/raw/iceberg/{era5_wind,glorys}/ and the run is
  resumable: already-present files are skipped and re-counted.
* A combined 6 GB budget is enforced: downloads stop (and are logged) before the
  cumulative bytes exceed the cap. TEST windows are downloaded first; VAL only if
  budget remains.

Output
------
Prints per-file sizes and a running total, then the grand total size. Writes
a download manifest to data/raw/iceberg/forcing_manifest.json.

Usage
-----
python scripts/download_iceberg_forcing.py
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ARCO = "gs://gcp-public-data-arco-era5"
ERA5_VARS = ["10m_u_component_of_wind", "10m_v_component_of_wind"]
GLORYS_DATASET = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
GLORYS_VARS = ["uo", "vo"]

ERA5_DIR = REPO / "data" / "raw" / "iceberg" / "era5_wind"
GLORYS_DIR = REPO / "data" / "raw" / "iceberg" / "glorys"
ERA5_DIR.mkdir(parents=True, exist_ok=True)
GLORYS_DIR.mkdir(parents=True, exist_ok=True)

MANIFEST_PATH = REPO / "data" / "raw" / "iceberg" / "forcing_manifest.json"

TOTAL_BUDGET_BYTES = 6 * 1024**3  # 6 GB

DOWNLOAD_LOG: list[str] = []
TOTAL_BYTES = 0


def log(msg: str) -> None:
    print(msg, flush=True)
    DOWNLOAD_LOG.append(msg)


def daterange(lo: date, hi: date):
    cur = lo
    while cur <= hi:
        yield cur
        cur += timedelta(days=1)


# ---------------------------------------------------------------------------
# Day selection: contiguous forcing windows covering unique (track, t0) blocks.
# A t0 block [D1..D2] needs forcing [D1-3 .. D2+7].
# TEST first (per budget instruction); VAL only if budget remains.
# ---------------------------------------------------------------------------
TEST_T0_LO, TEST_T0_HI = date(2022, 1, 10), date(2022, 1, 19)   # 10 t0 days
VAL_T0_LO, VAL_T0_HI = date(2018, 1, 10), date(2018, 1, 14)    # 5 t0 days


def forcing_days(t0_lo: date, t0_hi: date):
    return [d for d in daterange(t0_lo - timedelta(days=3), t0_hi + timedelta(days=7))]


TEST_FORCING_DAYS = forcing_days(TEST_T0_LO, TEST_T0_HI)
VAL_FORCING_DAYS = forcing_days(VAL_T0_LO, VAL_T0_HI)

log(f"TEST t0 block: {TEST_T0_LO} -> {TEST_T0_HI}; forcing days: {len(TEST_FORCING_DAYS)} "
    f"({TEST_FORCING_DAYS[0]} -> {TEST_FORCING_DAYS[-1]})")
log(f"VAL t0 block: {VAL_T0_LO} -> {VAL_T0_HI}; forcing days: {len(VAL_FORCING_DAYS)} "
    f"({VAL_FORCING_DAYS[0]} -> {VAL_FORCING_DAYS[-1]})")
log(f"Budget: {TOTAL_BUDGET_BYTES / 1024**3:.1f} GB total (ERA5 + GLORYS combined)")


# ---------------------------------------------------------------------------
# ERA5 from ARCO (anonymous)
# ---------------------------------------------------------------------------
def era5_url(var: str, d: date) -> str:
    return f"{ARCO}/raw/date-variable-single_level/{d:%Y/%m/%d}/{var}/surface.nc"


def era5_local(var: str, d: date) -> Path:
    return ERA5_DIR / f"{var.split('/')[-1].replace(' ', '_')}_{d:%Y%m%d}.nc"


def download_era5(days) -> int:
    from gcsfs import GCSFileSystem
    fs = GCSFileSystem(token="anon")
    fetched = 0
    for d in days:
        for var in ERA5_VARS:
            local = era5_local(var, d)
            if local.is_file():
                size = local.stat().st_size
                log(f"[cache] ERA5 {var} {d:%Y-%m-%d} {size/1024**2:.1f} MB (exists)")
                fetched += size
                continue
            url = era5_url(var, d)
            t0 = time.perf_counter()
            try:
                fs.get(url, local)
            except Exception as e:
                log(f"[ERR] ERA5 {var} {d:%Y-%m-%d}: {type(e).__name__} {e}")
                raise
            elapsed = time.perf_counter() - t0
            size = local.stat().st_size
            fetched += size
            log(f"[get] ERA5 {var} {d:%Y-%m-%d} {size/1024**2:.1f} MB in {elapsed:.1f}s")
    return fetched


# ---------------------------------------------------------------------------
# GLORYS current via copernicusmarine (0-100 m mean; surface taken from same file)
# ---------------------------------------------------------------------------
def glorys_local(d: date) -> Path:
    return GLORYS_DIR / f"glorys_{d:%Y%m%d}.nc"


def download_glorys(days) -> int:
    import copernicusmarine
    fetched = 0
    for d in days:
        local = glorys_local(d)
        if local.is_file():
            size = local.stat().st_size
            log(f"[cache] GLORYS {d:%Y-%m-%d} {size/1024**2:.1f} MB (exists)")
            fetched += size
            continue
        t0 = time.perf_counter()
        try:
            copernicusmarine.subset(
                dataset_id=GLORYS_DATASET,
                variables=GLORYS_VARS,
                minimum_longitude=-180, maximum_longitude=180,
                minimum_latitude=-82, maximum_latitude=-48,
                minimum_depth=0, maximum_depth=110,
                start_datetime=f"{d:%Y-%m-%d}T00:00:00",
                end_datetime=f"{d:%Y-%m-%d}T00:00:00",
                output_directory=str(GLORYS_DIR),
                output_filename=f"glorys_{d:%Y%m%d}.nc",
                disable_progress_bar=True,
            )
        except Exception as e:
            log(f"[ERR] GLORYS {d:%Y-%m-%d}: {type(e).__name__} {e}")
            raise
        elapsed = time.perf_counter() - t0
        size = local.stat().st_size
        fetched += size
        log(f"[get] GLORYS {d:%Y-%m-%d} {size/1024**2:.1f} MB in {elapsed:.1f}s")
    return fetched


def main() -> int:
    global TOTAL_BYTES
    plan = [
        ("TEST", TEST_FORCING_DAYS),
        ("VAL", VAL_FORCING_DAYS),
    ]
    results = {}
    for block_name, days in plan:
        log(f"\n=== {block_name} forcing window ===")
        before = TOTAL_BYTES
        era5_bytes = download_era5(days)
        TOTAL_BYTES += era5_bytes
        if TOTAL_BYTES > TOTAL_BUDGET_BYTES:
            log(f"[BUDGET] ERA5 pushed {block_name} over {TOTAL_BUDGET_BYTES/1024**3:.1f} GB "
                f"(cumulative {TOTAL_BYTES/1024**3:.2f} GB); stopping GLORYS for this block.")
            results[block_name] = {"era5_bytes": era5_bytes, "glorys_bytes": 0, "stopped": True}
            break
        glorys_bytes = download_glorys(days)
        TOTAL_BYTES += glorys_bytes
        if TOTAL_BYTES > TOTAL_BUDGET_BYTES:
            log(f"[BUDGET] cumulative {TOTAL_BYTES/1024**3:.2f} GB exceeds {TOTAL_BUDGET_BYTES/1024**3:.1f} GB; "
                "no further blocks will be downloaded.")
            results[block_name] = {"era5_bytes": era5_bytes, "glorys_bytes": glorys_bytes, "stopped": True}
            break
        results[block_name] = {"era5_bytes": era5_bytes, "glorys_bytes": glorys_bytes, "stopped": False}

    log("\n=== DOWNLOAD SUMMARY ===")
    for block_name, r in results.items():
        log(f"  {block_name}: ERA5 {r['era5_bytes']/1024**3:.2f} GB + GLORYS "
            f"{r['glorys_bytes']/1024**3:.2f} GB = "
            f"{(r['era5_bytes']+r['glorys_bytes'])/1024**3:.2f} GB  stopped={r['stopped']}")
    log(f"  TOTAL downloaded/cached: {TOTAL_BYTES/1024**3:.2f} GB "
        f"(budget {TOTAL_BUDGET_BYTES/1024**3:.1f} GB)")

    manifest = {
        "budget_gb": TOTAL_BUDGET_BYTES / 1024**3,
        "total_gb": TOTAL_BYTES / 1024**3,
        "era5_vars": ERA5_VARS,
        "glorys_dataset": GLORYS_DATASET,
        "glorys_vars": GLORYS_VARS,
        "glorys_depth_m": "0-110",
        "blocks": results,
        "test_t0": [str(d) for d in daterange(TEST_T0_LO, TEST_T0_HI)],
        "val_t0": [str(d) for d in daterange(VAL_T0_LO, VAL_T0_HI)],
    }
    MANIFEST_PATH.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    log(f"Manifest written to {MANIFEST_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
