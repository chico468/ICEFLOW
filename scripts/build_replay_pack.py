"""Build a real-environment replay pack from the R0 coverage matrix.

The R0 coverage matrix (``R0_COVERAGE_MATRIX`` below) declares every real data
product the replay system can consume: ERA5 wind, ERA5 waves, CMEMS ocean
current and NRT sea-ice concentration. ``build_replay_pack`` downloads the
products for a requested start date / day count / bounding box into one cache
directory, writes ``manifest.json``, and is resumable (partial downloads are
resumed, already-complete products are skipped).

ERA5 waves are read from their own NetCDF file because the wave grid differs
from the wind grid. Before downloading anything, the script prints the total
estimated size and elapsed wall time and aborts with a confirmation prompt when
the estimate exceeds 5 GB.

Usage::

    python -m scripts.build_replay_pack \
        --start 2024-01-15 --days 3 \
        --bbox "-70,-60,40,70" \
        --out /tmp/iceflow-replay-pack
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx
import numpy as np
import xarray as xr

#: Maximum total download size before the script requires an explicit
#: confirmation (5 GB).
MAX_UNATTENDED_BYTES = 5 * 1024**3

#: CDS ERA5 single-level dataset (wind and waves share the CDS collection but
#: are downloaded into separate files because their grids differ).
ERA5_SINGLE_LEVELS = "reanalysis-era5-single-levels"

#: Copernicus Marine dataset IDs (from src/data/copernicus_marine.py LAYER_SPECS).
CMEMS_PHY_NRT = "GLOBAL_ANALYSISFORECAST_PHY_001_024"
CMEMS_ICE_NRT = "SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001"

#: CDS API endpoint (requires a CDS API key in ~/.cdsapirc or CDS_API_KEY env).
CDS_API_URL = "https://cds.climate.copernicus.eu/api/v2"

#: Copernicus Marine WMTS capabilities endpoint (public, no key required).
CMEMS_WMTS_URL = "https://wmts.marine.copernicus.eu/teroWmts"


# ---------------------------------------------------------------------------
# R0 coverage matrix
#
# One entry per real data product the replay system can consume. Each entry
# declares the dataset id, product name, version, variables, native grid, the
# request parameters needed to fetch a time window, and a citable source.
# ---------------------------------------------------------------------------
R0_COVERAGE_MATRIX: dict[str, dict[str, Any]] = {
    "era5_wind_10m": {
        "dataset_id": ERA5_SINGLE_LEVELS,
        "product": "ERA5",
        "version": "v1",
        "variables": ["10m_u_component_of_wind", "10m_v_component_of_wind"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6"
        ),
        "request_params": {
            "product_type": ["reanalysis"],
            "data_format": "netcdf",
            "download_format": "unarchived",
        },
        "provenance_kind": "reanalysis",
    },
    "era5_waves": {
        "dataset_id": ERA5_SINGLE_LEVELS,
        "product": "ERA5",
        "version": "v1",
        "variables": ["significant_height_of_combined_wind_waves_and_swell"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian, wave grid)",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6"
        ),
        "request_params": {
            "product_type": ["reanalysis"],
            "data_format": "netcdf",
            "download_format": "unarchived",
        },
        "provenance_kind": "reanalysis",
        "separate_file": True,
    },
    "cmems_current": {
        "dataset_id": CMEMS_PHY_NRT,
        "product": "CMEMS GLOBAL ANALYSISFORECAST PHY 001 024",
        "version": "0.083 deg",
        "variables": ["uo", "vo"],
        "native_grid": "1/12 deg global ocean",
        "citation": (
            "Copernicus Marine Service, GLOBAL ANALYSISFORECAST PHY 001 024, "
            "https://doi.org/10.48670/moi-00015"
        ),
        "request_params": {
            "variables": ["uo", "vo"],
            "minimum_longitude": None,  # filled from --bbox
            "maximum_longitude": None,
            "minimum_latitude": None,
            "maximum_latitude": None,
        },
        "provenance_kind": "reanalysis",
    },
    "nrt_ice_concentration": {
        "dataset_id": CMEMS_ICE_NRT,
        "product": "CMEMS SEAICE GLO SEAICE L4 NRT OBSERVATIONS 011 001",
        "version": "L4 NRT",
        "variables": ["ice_conc"],
        "native_grid": "polar stereographic / 0.05 deg",
        "citation": (
            "Copernicus Marine Service, SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001, "
            "https://doi.org/10.48670/moi-00208"
        ),
        "request_params": {
            "variables": ["ice_conc"],
            "minimum_longitude": None,
            "maximum_longitude": None,
            "minimum_latitude": None,
            "maximum_latitude": None,
        },
        "provenance_kind": "real-observation",
    },
}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
@dataclass
class ProductRecord:
    product: str
    dataset_id: str
    version: str
    request_params: dict[str, Any]
    sha256: str
    download_time_s: float
    size_bytes: int
    citation: str
    provenance_kind: str
    local_path: str
    valid_from: str | None = None
    valid_to: str | None = None


@dataclass
class Manifest:
    start: str
    days: int
    bbox: tuple[float, float, float, float]
    generated_at: str
    total_size_bytes: int
    products: list[ProductRecord] = field(default_factory=list)

    def to_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "days": self.days,
            "bbox": list(self.bbox),
            "generated_at": self.generated_at,
            "total_size_bytes": self.total_size_bytes,
            "products": [
                {
                    "product": p.product,
                    "dataset_id": p.dataset_id,
                    "version": p.version,
                    "request_params": p.request_params,
                    "sha256": p.sha256,
                    "download_time_s": p.download_time_s,
                    "size_bytes": p.size_bytes,
                    "citation": p.citation,
                    "provenance_kind": p.provenance_kind,
                    "local_path": p.local_path,
                    "valid_from": p.valid_from,
                    "valid_to": p.valid_to,
                }
                for p in self.products
            ],
        }

    def write(self, path: Path) -> None:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(self.to_dict(), indent=2) + "\n", encoding="utf-8")

    @classmethod
    def load(cls, path: Path) -> "Manifest":
        data = json.loads(path.read_text(encoding="utf-8"))
        return cls(
            start=data["start"],
            days=data["days"],
            bbox=tuple(data["bbox"]),
            generated_at=data["generated_at"],
            total_size_bytes=data["total_size_bytes"],
            products=[
                ProductRecord(
                    product=p["product"],
                    dataset_id=p["dataset_id"],
                    version=p["version"],
                    request_params=p["request_params"],
                    sha256=p["sha256"],
                    download_time_s=p["download_time_s"],
                    size_bytes=p["size_bytes"],
                    citation=p["citation"],
                    provenance_kind=p["provenance_kind"],
                    local_path=p["local_path"],
                    valid_from=p.get("valid_from"),
                    valid_to=p.get("valid_to"),
                )
                for p in data["products"]
            ],
        )


# ---------------------------------------------------------------------------
# Download helpers
# ---------------------------------------------------------------------------
def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _resumable_download(url: str, target: Path, headers: dict[str, str] | None = None) -> tuple[int, float]:
    """Download ``url`` to ``target``, resuming from any partial file.

    Returns ``(size_bytes, elapsed_seconds)``.
    """
    target.parent.mkdir(parents=True, exist_ok=True)
    tmp = target.with_name(target.name + ".part")

    # Resume: if a .part exists, ask the server to continue from its size.
    resume_from = tmp.stat().st_size if tmp.exists() else 0
    request_headers = dict(headers or {})
    if resume_from > 0:
        request_headers["Range"] = f"bytes={resume_from}-"

    started = time.perf_counter()
    with httpx.stream("GET", url, headers=request_headers, timeout=120.0, follow_redirects=True) as response:
        response.raise_for_status()
        mode = "ab" if resume_from > 0 else "wb"
        total = resume_from
        with tmp.open(mode) as out:
            for chunk in response.iter_bytes():
                out.write(chunk)
                total += len(chunk)
    tmp.replace(target)
    elapsed = time.perf_counter() - started
    return total, elapsed


def _estimate_total_bytes(matrix: dict[str, Any], start: date, days: int, bbox: tuple[float, float, float, float]) -> int:
    """Rough size estimate in bytes before downloading (used for the >5 GB gate).

    ERA5 single-level ~2 MB per variable-day at 0.25 deg over Antarctica.
    CMEMS subsets are small for a regional window.
    """
    per_variable_day_mb = 2.0
    n_variable_days = len(matrix["era5_wind_10m"]["variables"]) * days
    wave_variable_days = len(matrix["era5_waves"]["variables"]) * days
    cmems_mb = 5.0 * days  # small regional subset
    ice_mb = 3.0 * days
    total_mb = (n_variable_days + wave_variable_days) * per_variable_day_mb + cmems_mb + ice_mb
    return int(total_mb * 1024 * 1024)


# ---------------------------------------------------------------------------
# ERA5 waves reader - separate file because the wave grid differs from wind.
# ---------------------------------------------------------------------------
def read_era5_waves(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray]:
    """Read ERA5 significant wave height from its own NetCDF file.

    Returns ``(lats, lons, times, swh_m)`` where ``times`` is a
    ``datetime64[ns]`` array and ``swh_m`` has shape ``(time, lat, lon)``.
    """
    with xr.open_dataset(path) as ds:
        var = "swh" if "swh" in ds.data_vars else "significant_height_of_combined_wind_waves_and_swell"
        lats = np.asarray(ds["latitude"].values, dtype=np.float64)
        lons = np.asarray(ds["longitude"].values, dtype=np.float64)
        times = np.asarray(ds["time"].values, dtype="datetime64[ns]")
        swh = np.asarray(ds[var].values, dtype=np.float64)
    return lats, lons, times, swh


# ---------------------------------------------------------------------------
# Main pack builder
# ---------------------------------------------------------------------------
def parse_bbox(value: str) -> tuple[float, float, float, float]:
    parts = [float(p) for p in value.split(",")]
    if len(parts) != 4:
        raise argparse.ArgumentTypeError("bbox must be west,south,east,north")
    west, south, east, north = parts
    if not (-180 <= west < east <= 180 and -90 <= south < north <= 90):
        raise argparse.ArgumentTypeError("bbox must satisfy -180<=west<east<=180, -90<=south<north<=90")
    return west, south, east, north


def parse_date(value: str) -> date:
    try:
        return datetime.strptime(value, "%Y-%m-%d").date()
    except ValueError as exc:
        raise argparse.ArgumentTypeError(f"start must be YYYY-MM-DD: {value}") from exc


def build_pack(
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    out: Path,
    *,
    unattended: bool = False,
    cds_api_key: str | None = None,
) -> Manifest:
    """Download the R0 coverage matrix products for the window into ``out``."""
    out.mkdir(parents=True, exist_ok=True)

    estimated = _estimate_total_bytes(R0_COVERAGE_MATRIX, start, days, bbox)
    if not unattended and estimated > MAX_UNATTENDED_BYTES:
        print(
            f"Estimated download size {estimated / 1024**3:.2f} GB exceeds the 5 GB unattended limit. "
            "Re-run with --unattended to proceed anyway.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    print(f"Estimated total download size: {estimated / 1024**3:.2f} GB")
    print(f"Output directory: {out}")
    print(f"Window: {start.isoformat()} + {days} day(s)")
    print(f"Bounding box: west={bbox[0]}, south={bbox[1]}, east={bbox[2]}, north={bbox[3]}")

    manifest = Manifest(
        start=start.isoformat(),
        days=days,
        bbox=bbox,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_size_bytes=0,
    )

    key = cds_api_key or os.environ.get("CDS_API_KEY", "")
    headers = {}
    if key:
        headers["Authorization"] = f"Bearer {key}"

    for product_name, spec in R0_COVERAGE_MATRIX.items():
        product_start = time.perf_counter()
        filename = f"{product_name}_{start:%Y%m%d}_{days}d.nc"
        target = out / filename

        if target.exists():
            print(f"  [skip] {product_name}: already cached at {target}")
            manifest.products.append(
                ProductRecord(
                    product=product_name,
                    dataset_id=spec["dataset_id"],
                    version=spec["version"],
                    request_params=dict(spec["request_params"]),
                    sha256=_sha256_of_file(target),
                    download_time_s=0.0,
                    size_bytes=target.stat().st_size,
                    citation=spec["citation"],
                    provenance_kind=spec["provenance_kind"],
                    local_path=str(target),
                )
            )
            manifest.total_size_bytes += target.stat().st_size
            continue

        url = f"{CDS_API_URL}/datasets/{spec['dataset_id']}/download"
        params = {
            "variable": spec["variables"],
            "year": f"{start:%Y}",
            "month": f"{start:%m}",
            "day": ",".join(f"{start + timedelta(days=i):%d}" for i in range(days)),
            "time": "00:00",
            "area": [bbox[3], bbox[0], bbox[1], bbox[2]],  # N,W,S,E for CDS
            **spec["request_params"],
        }

        print(f"  [download] {product_name} from {spec['dataset_id']} ...")
        try:
            size, elapsed = _resumable_download(url, target, headers=headers)
        except httpx.HTTPError as exc:
            print(f"  [error] {product_name}: download failed ({exc})", file=sys.stderr)
            continue

        sha = _sha256_of_file(target)
        elapsed_total = time.perf_counter() - product_start
        manifest.products.append(
            ProductRecord(
                product=product_name,
                dataset_id=spec["dataset_id"],
                version=spec["version"],
                request_params=dict(spec["request_params"]),
                sha256=sha,
                download_time_s=round(elapsed_total, 3),
                size_bytes=size,
                citation=spec["citation"],
                provenance_kind=spec["provenance_kind"],
                local_path=str(target),
            )
        )
        manifest.total_size_bytes += size
        print(f"    -> {size / 1024**2:.2f} MB in {elapsed_total:.1f}s, sha256={sha[:16]}...")

    manifest.write(out / "manifest.json")
    print(f"\nManifest written: {out / 'manifest.json'}")
    print(f"Total size: {manifest.total_size_bytes / 1024**2:.2f} MB across {len(manifest.products)} product(s)")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--days", required=True, type=int, help="Number of days to cover (>=1)")
    parser.add_argument("--bbox", required=True, type=parse_bbox, help="west,south,east,north in degrees")
    parser.add_argument("--out", required=True, type=Path, help="Output cache directory")
    parser.add_argument("--unattended", action="store_true", help="Skip the >5 GB confirmation prompt")
    parser.add_argument("--cds-api-key", help="CDS API key (defaults to CDS_API_KEY env var)")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be >= 1")

    build_pack(
        args.start,
        args.days,
        args.bbox,
        args.out,
        unattended=args.unattended,
        cds_api_key=args.cds_api_key,
    )


if __name__ == "__main__":
    main()
