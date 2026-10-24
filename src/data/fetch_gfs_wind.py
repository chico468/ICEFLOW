"""Explicitly download one small NOAA NOMADS 10 m wind subset into ICEFLOW's local cache."""
from __future__ import annotations

import argparse
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from urllib.parse import urlencode

import httpx

from src.data.real_flow import cache_flow, read_gfs_grib

URL = "https://nomads.ncep.noaa.gov/cgi-bin/filter_gfs_0p25.pl"


def fetch(date: str, cycle: str, lead_hours: int, cache_dir: str | None = None) -> Path:
    datetime.strptime(date, "%Y-%m-%d")
    if cycle not in {"00", "06", "12", "18"}:
        raise ValueError("GFS cycle must be 00, 06, 12, or 18 UTC.")
    if not 0 <= lead_hours <= 120:
        raise ValueError("For this subset command, forecast lead must be between 0 and 120 hours.")
    ymd = date.replace("-", "")
    file_name = f"gfs.t{cycle}z.pgrb2.0p25.f{lead_hours:03d}"
    query = {
        "file": file_name,
        "var_UGRD": "on",
        "var_VGRD": "on",
        "lev_10_m_above_ground": "on",
        "subregion": "",
        "leftlon": "0",
        "rightlon": "359.75",
        "toplat": "-25",
        "bottomlat": "-90",
        "dir": f"/gfs.{ymd}/{cycle}/atmos",
    }
    with tempfile.TemporaryDirectory(prefix="iceflow-gfs-") as temp:
        grib_path = Path(temp) / file_name
        with httpx.stream("GET", URL, params=query, timeout=180, follow_redirects=True) as response:
            response.raise_for_status()
            content_type = response.headers.get("content-type", "").lower()
            length = int(response.headers.get("content-length", "0") or 0)
            if "text/html" in content_type or length > 100_000_000:
                raise RuntimeError("NOMADS returned an HTML error or an unexpectedly large file.")
            total = 0
            with grib_path.open("wb") as output:
                for chunk in response.iter_bytes():
                    total += len(chunk)
                    if total > 100_000_000:
                        raise RuntimeError("NOMADS response exceeded the 100 MB safety limit.")
                    output.write(chunk)
        with grib_path.open("rb") as stream:
            if stream.read(4) != b"GRIB":
                raise RuntimeError("NOMADS response is not a GRIB file; no cache entry was written.")
        lats, lons, u, v, metadata = read_gfs_grib(grib_path)
        metadata.update({
            "retrieved_at": datetime.now(timezone.utc).isoformat(),
            "source_url": str(response.url),
            "crs": "EPSG:4326",
            "coordinate_units": "degrees_north, degrees_east",
        })
        return cache_flow("wind", lats, lons, u, v, metadata, cache_dir=cache_dir)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--date", required=True, help="GFS model run date, UTC, YYYY-MM-DD")
    parser.add_argument("--cycle", required=True, help="GFS model run cycle: 00, 06, 12, or 18")
    parser.add_argument("--lead-hours", required=True, type=int, help="Forecast lead (0-120 hours)")
    parser.add_argument("--cache-dir", help="Override ICEFLOW_FLOW_CACHE_DIR")
    args = parser.parse_args()
    print(fetch(args.date, args.cycle, args.lead_hours, args.cache_dir))


if __name__ == "__main__":
    main()
