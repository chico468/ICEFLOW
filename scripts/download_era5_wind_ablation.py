"""Phase 4 Part 2: Download ERA5 10m wind (u10, v10) from ARCO for selected
representative days in the iceberg test period (2019-2022).

Logs each download size. Restricts to a subset of days to stay within the
8 GB total budget (extras download already consumed ~468 MB).
"""
from __future__ import annotations

import hashlib
import sys
import tempfile
import time
from datetime import date, timedelta
from pathlib import Path

import gcsfs
import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ARCO = "gs://gcp-public-data-arco-era5"
TOKEN = "anon"
OUT_DIR = REPO / "data" / "raw" / "iceberg" / "era5_wind"
OUT_DIR.mkdir(parents=True, exist_ok=True)

DOWNLOAD_LOG = []
TOTAL_BYTES = 0

# Select ~30 representative days spread across 2019-2022 test period.
# One day per month would be ~48 days; we cap at ~30 for budget.
SELECTED_DAYS = [
    date(2019, 1, 15), date(2019, 4, 15), date(2019, 7, 15), date(2019, 10, 15),
    date(2020, 1, 15), date(2020, 4, 15), date(2020, 7, 15), date(2020, 10, 15),
    date(2021, 1, 15), date(2021, 4, 15), date(2021, 7, 15), date(2021, 10, 15),
    date(2022, 1, 15), date(2022, 4, 15), date(2022, 7, 15), date(2022, 10, 15),
    date(2019, 2, 1), date(2019, 8, 1), date(2020, 2, 1), date(2020, 8, 1),
    date(2021, 2, 1), date(2021, 8, 1), date(2022, 2, 1), date(2022, 8, 1),
    date(2019, 11, 1), date(2020, 11, 1), date(2021, 11, 1), date(2022, 11, 1),
    date(2019, 6, 1), date(2020, 6, 1), date(2021, 6, 1), date(2022, 6, 1),
]


def sha256(p: Path) -> str:
    h = hashlib.sha256()
    with p.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def download_var_day(var: str, day: date) -> int:
    """Download one ARCO ERA5 surface file. Returns bytes downloaded."""
    url = f"{ARCO}/raw/date-variable-single_level/{day:%Y/%m/%d}/{var}/surface.nc"
    local = OUT_DIR / f"{var}_{day:%Y%m%d}.nc"
    if local.is_file():
        size = local.stat().st_size
        DOWNLOAD_LOG.append(f"{url} -> {local.name} (cached, {size} bytes)")
        return size
    fs = gcsfs.GCSFileSystem(token=TOKEN)
    tmp = Path(tempfile.mktemp(suffix=".nc"))
    t0 = time.perf_counter()
    fs.get(url, tmp)
    elapsed = time.perf_counter() - t0
    size = tmp.stat().st_size
    tmp.replace(local)
    DOWNLOAD_LOG.append(f"{url} -> {local.name} ({size} bytes, {elapsed:.1f}s, sha256={sha256(local)[:12]}...)")
    print(f"    [download] {var} {day:%Y-%m-%d} {size/1024**2:.1f} MB in {elapsed:.1f}s")
    return size


def main():
    global TOTAL_BYTES
    print(f"Selected {len(SELECTED_DAYS)} days for ERA5 wind download")
    print(f"Variables: 10m_u_component_of_wind, 10m_v_component_of_wind")
    print(f"Estimated: {len(SELECTED_DAYS)} days × 2 vars × ~50 MB = {len(SELECTED_DAYS) * 2 * 50 / 1024:.1f} GB")
    print()

    fs = gcsfs.GCSFileSystem(token=TOKEN)
    # Quick size check on one file
    test_url = f"{ARCO}/raw/date-variable-single_level/2022/01/15/10m_u_component_of_wind/surface.nc"
    try:
        info = fs.info(test_url)
        print(f"Single file size: {info['size'] / 1024**2:.1f} MB")
        per_day = info['size'] * 2 / 1024**2  # 2 vars
        est_total = len(SELECTED_DAYS) * per_day
        print(f"Estimated total: {est_total:.1f} MB = {est_total / 1024:.1f} GB")
    except Exception as e:
        print(f"Size check failed: {e}")
        per_day = 100  # MB estimate
        est_total = len(SELECTED_DAYS) * per_day
        print(f"Estimated total (approx): {est_total / 1024:.1f} GB")

    print()
    for day in SELECTED_DAYS:
        for var in ["10m_u_component_of_wind", "10m_v_component_of_wind"]:
            size = download_var_day(var, day)
            TOTAL_BYTES += size

    print(f"\n=== DOWNLOAD SUMMARY ===")
    print(f"Total downloaded: {TOTAL_BYTES / 1024**3:.2f} GB")
    print(f"Files: {len(DOWNLOAD_LOG)}")
    print(f"Output dir: {OUT_DIR}")
    print("\nDownload log:")
    for line in DOWNLOAD_LOG:
        print(f"  {line}")


if __name__ == "__main__":
    main()
