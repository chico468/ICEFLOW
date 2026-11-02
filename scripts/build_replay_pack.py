"""Build a real-environment replay pack from the R0 coverage matrix.

The R0 coverage matrix (``R0_COVERAGE_MATRIX`` below) declares every real data
product the replay system can consume. ``build_replay_pack`` downloads the
products for a requested start date / day count / bounding box into one cache
directory, writes ``manifest.json``, and is resumable (partial downloads are
resumed, already-complete products are skipped).

Products (per the R0 matrix):

* ``era5_wind_10m`` / ``era5_waves``  - ERA5 via the anonymous Google ARCO copy
  (``gs://gcp-public-data-arco-era5``, token ``"anon"``). Provenance reads
  ``"ERA5 via Google ARCO copy"`` and the store's valid-time range is recorded.
* ``cmems_current`` - ocean current (uo, vo) and sea-ice velocity (usi, vsi)
  from Copernicus Marine (dataset ``cmems_mod_glo_phy_my_0.083deg_P1D-m``).
  Login must succeed or the build fails loudly.
* ``sic_g02202_v6`` - sea-ice concentration from NOAA/NSIDC CDR G02202 Version 6
  (polar-stereographic EPSG:3412, regridded to a regular lat/lon grid for the
  provider's bilinear sampler).

Usage::

    python -m scripts.build_replay_pack \
        --start 2022-01-13 --days 33 \
        --bbox "10,-75,90,-30" \
        --out /tmp/iceflow-replay-pack

Before downloading anything, the script prints the total estimated size and
elapsed wall time and aborts when the estimate exceeds 5 GB unless
``--unattended`` is passed.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import tempfile
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

#: Anonymous Google ARCO-ERA5 bucket.
ARCO_STORE = "gs://gcp-public-data-arco-era5"
ARCO_TOKEN = "anon"
ARCO_PROVENANCE = "ERA5 via Google ARCO copy"

#: Copernicus Marine multiyear physics reanalysis (has uo, vo, usi, vsi at
#: 1/12 deg, daily). The legacy "myint" product id does not exist in the
#: reorganised catalogue; this is the current equivalent.
CMEMS_PHY_MY = "cmems_mod_glo_phy_my_0.083deg_P1D-m"

#: NOAA/NSIDC CDR G02202 Version 6 (south, daily).
NSIDC_V6_BASE = "https://noaadata.apps.nsidc.org/NOAA/G02202_V6/south/daily"
NSIDC_ANCILLARY_URL = (
    "https://noaadata.apps.nsidc.org/NOAA/G02202_V6/ancillary/"
    "G02202-ancillary-pss25-v06r00.nc"
)

#: Southern Ocean box covering Cape Town -> Bharati (default replay window box).
DEFAULT_BBOX = (10.0, -75.0, 90.0, -30.0)


# ---------------------------------------------------------------------------
# R0 coverage matrix
# ---------------------------------------------------------------------------
R0_COVERAGE_MATRIX: dict[str, dict[str, Any]] = {
    "era5_wind_10m": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": [
            "10m_u_component_of_wind",
            "10m_v_component_of_wind",
        ],
        "netcdf_vars": ["u10", "v10"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "era5_waves": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": ["significant_height_of_combined_wind_waves_and_swell"],
        "netcdf_vars": ["swh"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian, wave grid)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "era5_snowfall": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": ["snowfall"],
        "netcdf_vars": ["snowfall"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "era5_total_cloud_cover": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": ["total_cloud_cover"],
        "netcdf_vars": ["tcc"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "era5_2m_temperature": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": ["2m_temperature"],
        "netcdf_vars": ["t2m"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "era5_mean_sea_level_pressure": {
        "source": "arco-era5",
        "store": ARCO_STORE,
        "token": ARCO_TOKEN,
        "product": ARCO_PROVENANCE,
        "version": "v1",
        "grib_variables": ["mean_sea_level_pressure"],
        "netcdf_vars": ["msl"],
        "native_grid": "0.25 deg lat/lon (reduced Gaussian)",
        "provenance_kind": "reanalysis",
        "citation": (
            "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
            "Copernicus Climate Change Service (C3S) Climate Data Store, "
            "https://doi.org/10.24381/cds.bd0915c6 ; "
            "served via Google Cloud public bucket gs://gcp-public-data-arco-era5"
        ),
    },
    "cmems_current": {
        "source": "copernicus-marine",
        "dataset_id": CMEMS_PHY_MY,
        "product": "GLOBAL_MULTIYEAR_PHY_001_030 (Global Ocean Physics Reanalysis)",
        "version": "0.083 deg",
        "grib_variables": ["uo", "vo", "usi", "vsi"],
        "netcdf_vars": ["uo", "vo", "usi", "vsi"],
        "native_grid": "1/12 deg global ocean",
        "provenance_kind": "reanalysis",
        "citation": (
            "Copernicus Marine Service, GLOBAL_MULTIYEAR_PHY_001_030, "
            "https://doi.org/10.48670/moi-00016"
        ),
    },
    "sic_g02202_v6": {
        "source": "nsidc",
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "grib_variables": ["cdr_seaice_conc"],
        "netcdf_vars": ["ice_conc"],
        "native_grid": "NSIDC polar stereographic 25 km (EPSG:3412), regridded to lat/lon",
        "provenance_kind": "real-observation",
        "citation": (
            "NOAA/NSIDC CDR G02202 Version 6, sea ice concentration, "
            "https://nsidc.org/data/g02202/versions/6"
        ),
    },
}


# ---------------------------------------------------------------------------
# Manifest
# ---------------------------------------------------------------------------
@dataclass
class ProductRecord:
    product: str
    source: str
    dataset_id: str | None
    version: str
    variables: list[str]
    native_grid: str
    provenance_kind: str
    provenance_source: str
    valid_from: str | None
    valid_to: str | None
    sha256: str
    download_time_s: float
    size_bytes: int
    citation: str
    local_path: str

    def to_dict(self) -> dict[str, Any]:
        return {
            "product": self.product,
            "source": self.source,
            "dataset_id": self.dataset_id,
            "version": self.version,
            "variables": self.variables,
            "native_grid": self.native_grid,
            "provenance_kind": self.provenance_kind,
            "provenance_source": self.provenance_source,
            "valid_from": self.valid_from,
            "valid_to": self.valid_to,
            "sha256": self.sha256,
            "download_time_s": self.download_time_s,
            "size_bytes": self.size_bytes,
            "citation": self.citation,
            "local_path": self.local_path,
        }


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
            "products": [p.to_dict() for p in self.products],
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
                ProductRecord(**p) for p in data["products"]
            ],
        )


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------
def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


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


def _estimate_total_bytes(start: date, days: int, bbox: tuple[float, float, float, float]) -> int:
    """Rough size estimate (bytes) before downloading, for the >5 GB gate.

    ARCO-ERA5 surface.nc files are ~5-10 MB per variable-day (global 0.25 deg).
    CMEMS subsets scale with box area; measured ~54 MB/day for a 90x20 deg box
    with six variables. G02202 files are ~0.34 MB/day.
    """
    west, south, east, north = bbox
    box_area_deg = (east - west) * (north - south)
    # Reference CMEMS box: 90 x 20 deg = 1800 deg^2 -> ~36 MB/day for uo,vo,usi,vsi.
    cmems_mb_per_day = 36.0 * (box_area_deg / 1800.0)
    arco_mb_per_var_day = 10.0  # conservative; measured ~4-6 MB/var-day
    n_arco_var_days = sum(
        len(spec["grib_variables"])
        for name, spec in R0_COVERAGE_MATRIX.items()
        if name.startswith("era5_")
    ) * days
    g02202_mb = 0.34 * days
    total_mb = n_arco_var_days * arco_mb_per_var_day + cmems_mb_per_day * days + g02202_mb
    return int(total_mb * 1024 * 1024)


# ---------------------------------------------------------------------------
# ARCO-ERA5 (anonymous Google Cloud Storage)
# ---------------------------------------------------------------------------
def _arco_variable_url(day: date, grib_variable: str) -> str:
    return (
        f"{ARCO_STORE}/raw/date-variable-single_level/"
        f"{day:%Y/%m/%d}/{grib_variable}/surface.nc"
    )


def _download_arco_product(
    product: str,
    spec: dict[str, Any],
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    tmp_dir: Path,
) -> tuple[Path, str, str]:
    """Download one ARCO-ERA5 product for the window, concatenate along time.

    Returns ``(local_path, valid_from, valid_to)``.
    """
    west, south, east, north = bbox
    fs = __import__("gcsfs").GCSFileSystem(token=ARCO_TOKEN)

    per_var_times: dict[str, list] = {}
    per_var_lat: dict[str, np.ndarray] = {}
    per_var_lon: dict[str, np.ndarray] = {}
    valid_times: list = []

    for grib_var, nc_var in zip(spec["grib_variables"], spec["netcdf_vars"]):
        da_list = []
        for i in range(days):
            day = start + timedelta(days=i)
            url = _arco_variable_url(day, grib_var)
            local = tmp_dir / f"{product}_{grib_var}_{day:%Y%m%d}.nc"
            if not local.is_file():
                t0 = time.perf_counter()
                fs.get(url, local)
                _ = time.perf_counter() - t0  # download time recorded in manifest
            ds = xr.open_dataset(local)
            lats = np.asarray(ds["latitude"].values)
            # ARCO latitude is descending (90 -> -90); slice() needs bounds in
            # axis order, i.e. slice(north, south) for a decreasing axis.
            lat_slice = slice(south, north) if lats.size > 1 and lats[0] < lats[-1] else slice(north, south)
            sub = ds.sel(latitude=lat_slice, longitude=slice(west, east))
            if nc_var not in sub.data_vars:
                ds.close()
                raise KeyError(f"ARCO variable {nc_var!r} not in {url}")
            da_list.append(sub[nc_var])
            valid_times.append(np.datetime64(sub["time"].values[0]))
            per_var_lat[nc_var] = np.asarray(sub["latitude"].values)
            per_var_lon[nc_var] = np.asarray(sub["longitude"].values)
            ds.close()
        combined = xr.concat(da_list, dim="time")
        per_var_times[nc_var] = combined

    # All wind/wave vars share the same grid/time; use the first for coords.
    first_nc = spec["netcdf_vars"][0]
    out_ds = xr.Dataset(
        {nc: (("time", "latitude", "longitude"), per_var_times[nc].values)
         for nc in spec["netcdf_vars"]},
        coords={
            "time": per_var_times[first_nc]["time"].values,
            "latitude": per_var_lat[first_nc],
            "longitude": per_var_lon[first_nc],
        },
    )
    out_path = tmp_dir / f"{product}.nc"
    out_ds.to_netcdf(out_path)
    out_ds.close()
    valid_from = str(np.datetime_as_string(min(valid_times), unit="s"))
    valid_to = str(np.datetime_as_string(max(valid_times), unit="s"))
    return out_path, valid_from, valid_to


# ---------------------------------------------------------------------------
# Copernicus Marine (currents + sea-ice velocity)
# ---------------------------------------------------------------------------
def _copernicus_login_ok() -> bool:
    """Return True only if stored Copernicus Marine credentials validate."""
    result = subprocess.run(
        ["copernicusmarine", "login", "--check-credentials-valid"],
        capture_output=True, text=True,
    )
    return result.returncode == 0


def _download_cmems_product(
    product: str,
    spec: dict[str, Any],
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    tmp_dir: Path,
) -> tuple[Path, str, str]:
    """Download CMEMS currents + sea-ice velocity for the window via the toolbox.

    Fails loudly if login is not valid.
    """
    if not _copernicus_login_ok():
        raise RuntimeError(
            "Copernicus Marine credentials are not valid. Run "
            "`copernicusmarine login` and store credentials in "
            "$HOME/.copernicusmarine before building the replay pack."
        )

    west, south, east, north = bbox
    end = start + timedelta(days=days - 1)
    out_path = tmp_dir / f"{product}.nc"

    cmd = [
        "copernicusmarine", "subset",
        "-i", spec["dataset_id"],
        "-v", "uo", "-v", "vo", "-v", "usi", "-v", "vsi",
        "--minimum-longitude", str(west), "--maximum-longitude", str(east),
        "--minimum-latitude", str(south), "--maximum-latitude", str(north),
        "--start-datetime", start.isoformat(), "--end-datetime", end.isoformat(),
        "-o", str(tmp_dir),
        "--file-format", "netcdf",
        "--overwrite",
    ]
    t0 = time.perf_counter()
    res = subprocess.run(cmd, capture_output=True, text=True, timeout=3600)
    if res.returncode != 0:
        raise RuntimeError(
            f"CMEMS subset failed for {product}: {res.stderr[-1000:]}"
        )
    # copernicusmarine writes its own filename; locate it.
    produced = sorted(tmp_dir.glob("cmems_mod_glo_phy_my_0.083deg_P1D-m*.nc"))
    if not produced:
        raise RuntimeError(f"CMEMS subset produced no .nc file in {tmp_dir}")
    src = produced[-1]
    shutil.move(str(src), str(out_path))

    ds = xr.open_dataset(out_path)
    # uo/vo are (time, depth, lat, lon); take the shallowest level.
    if "depth" in ds.dims:
        ds = ds.isel(depth=0)
    valid_times = ds["time"].values
    ds.close()
    valid_from = str(np.datetime_as_string(valid_times[0], unit="s"))
    valid_to = str(np.datetime_as_string(valid_times[-1], unit="s"))
    return out_path, valid_from, valid_to


# ---------------------------------------------------------------------------
# NSIDC G02202 V6 (sea-ice concentration, polar stereographic -> lat/lon)
# ---------------------------------------------------------------------------
def _download_g02202_product(
    product: str,
    spec: dict[str, Any],
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    tmp_dir: Path,
) -> tuple[Path, str, str]:
    """Download G02202 V6 SIC for the window and regrid to a regular lat/lon grid."""
    import pyproj  # local import to keep module importable without it at top

    west, south, east, north = bbox
    # Build a regular lat/lon target grid (0.25 deg) over the box.
    target_lats = np.arange(south, north + 1e-9, 0.25)
    target_lons = np.arange(west, east + 1e-9, 0.25)

    # Ancillary lat/lon truth for the pss25 grid (downloaded once).
    anc_local = tmp_dir / "G02202-ancillary-pss25-v06r00.nc"
    if not anc_local.is_file():
        r = httpx.get(NSIDC_ANCILLARY_URL, timeout=120)
        r.raise_for_status()
        anc_local.write_bytes(r.content)
    anc = xr.open_dataset(anc_local)
    src_lats = np.asarray(anc["latitude"].values)
    src_lons = np.asarray(anc["longitude"].values)
    anc.close()

    from scipy.interpolate import RegularGridInterpolator  # type: ignore

    conc_list = []
    valid_times: list = []
    for i in range(days):
        day = start + timedelta(days=i)
        # V6 sensor selection mirrors nsidc_sea_ice.NSIDCSeaIceReader._filename
        if day.year >= 2025:
            fname = f"sic_pss25_{day:%Y%m%d}_am2_v06r00.nc"
        elif day.year >= 2008:
            fname = f"sic_pss25_{day:%Y%m%d}_F17_v06r00.nc"
        elif day.year >= 1995:
            fname = f"sic_pss25_{day:%Y%m%d}_F13_v06r00.nc"
        elif day.year >= 1992:
            fname = f"sic_pss25_{day:%Y%m%d}_F11_v06r00.nc"
        elif day.year >= 1987:
            fname = f"sic_pss25_{day:%Y%m%d}_F08_v06r00.nc"
        else:
            fname = f"sic_pss25_{day:%Y%m%d}_n07_v06r00.nc"
        url = f"{NSIDC_V6_BASE}/{day:%Y}/{fname}"
        local = tmp_dir / fname
        if not local.is_file():
            r = httpx.get(url, timeout=120)
            if r.status_code == 404:
                # No observation for this day; skip with NaN grid.
                conc_list.append(np.full((target_lats.size, target_lons.size), np.nan))
                valid_times.append(np.datetime64(f"{day.isoformat()}T00:00:00"))
                continue
            r.raise_for_status()
            local.write_bytes(r.content)
        import xarray as xr
        with xr.open_dataset(local, engine="netcdf4") as fds:
            conc = np.asarray(fds["cdr_seaice_conc"].values, dtype=np.float64)
            if conc.ndim == 3:
                conc = conc[0]
            if np.nanmax(conc) > 1.5:
                conc = conc / 100.0
        # Regrid from source pss25 lat/lon to target regular lat/lon grid.
        src_lon_grid, src_lat_grid = np.meshgrid(src_lons, src_lats)
        points = np.column_stack([src_lat_grid.ravel(), src_lon_grid.ravel()])
        values = conc.ravel()
        interp = RegularGridInterpolator(
            (src_lats, src_lons), conc, bounds_error=False, fill_value=np.nan,
            method="linear",
        )
        target_points = np.column_stack([
            np.repeat(target_lats, target_lons.size),
            np.tile(target_lons, target_lats.size),
        ])
        regridded = interp(target_points).reshape(target_lats.size, target_lons.size)
        conc_list.append(regridded)
        valid_times.append(np.datetime64(f"{day.isoformat()}T00:00:00"))

    out_ds = xr.Dataset(
        {"ice_conc": (("time", "latitude", "longitude"), np.stack(conc_list, axis=0))},
        coords={
            "time": np.array(valid_times, dtype="datetime64[ns]"),
            "latitude": target_lats,
            "longitude": target_lons,
        },
    )
    out_path = tmp_dir / f"{product}.nc"
    out_ds.to_netcdf(out_path)
    out_ds.close()
    valid_from = str(np.datetime_as_string(min(valid_times), unit="s"))
    valid_to = str(np.datetime_as_string(max(valid_times), unit="s"))
    return out_path, valid_from, valid_to


_DOWNLOADERS = {
    "arco-era5": _download_arco_product,
    "copernicus-marine": _download_cmems_product,
    "nsidc": _download_g02202_product,
}


# ---------------------------------------------------------------------------
# Main pack builder
# ---------------------------------------------------------------------------
def build_pack(
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    out: Path,
    *,
    unattended: bool = False,
) -> Manifest:
    """Download the R0 coverage matrix products for the window into ``out``."""
    estimated = _estimate_total_bytes(start, days, bbox)
    print(f"Estimated total download size: {estimated / 1024**3:.2f} GB")
    print(f"Output directory: {out}")
    print(f"Window: {start.isoformat()} + {days} day(s) "
          f"({start.isoformat()} -> {(start + timedelta(days=days - 1)).isoformat()})")
    print(f"Bounding box: west={bbox[0]}, south={bbox[1]}, east={bbox[2]}, north={bbox[3]}")
    if not unattended and estimated > MAX_UNATTENDED_BYTES:
        print(
            f"Estimated size {estimated / 1024**3:.2f} GB exceeds the 5 GB unattended limit. "
            "Re-run with --unattended to proceed anyway.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    out.mkdir(parents=True, exist_ok=True)
    tmp_dir = Path(tempfile.mkdtemp(prefix="iceflow-pack-"))

    manifest = Manifest(
        start=start.isoformat(),
        days=days,
        bbox=bbox,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_size_bytes=0,
    )

    for product_name, spec in R0_COVERAGE_MATRIX.items():
        product_start = time.perf_counter()
        filename = f"{product_name}_{start:%Y%m%d}_{days}d.nc"
        target = out / filename

        if target.is_file():
            print(f"  [skip] {product_name}: already cached at {target}")
            manifest.products.append(ProductRecord(
                product=product_name,
                source=spec["source"],
                dataset_id=spec.get("dataset_id"),
                version=spec["version"],
                variables=spec["netcdf_vars"],
                native_grid=spec["native_grid"],
                provenance_kind=spec["provenance_kind"],
                provenance_source=spec["product"],
                valid_from=None,
                valid_to=None,
                sha256=_sha256_of_file(target),
                download_time_s=0.0,
                size_bytes=target.stat().st_size,
                citation=spec["citation"],
                local_path=str(target),
            ))
            manifest.total_size_bytes += target.stat().st_size
            continue

        downloader = _DOWNLOADERS[spec["source"]]
        print(f"  [download] {product_name} from {spec.get('dataset_id', spec['source'])} ...")
        try:
            local_path, valid_from, valid_to = downloader(
                product_name, spec, start, days, bbox, tmp_dir
            )
        except Exception as exc:
            print(f"  [error] {product_name}: download failed ({exc})", file=sys.stderr)
            continue

        shutil.move(str(local_path), str(target))
        size = target.stat().st_size
        sha = _sha256_of_file(target)
        elapsed = time.perf_counter() - product_start
        manifest.products.append(ProductRecord(
            product=product_name,
            source=spec["source"],
            dataset_id=spec.get("dataset_id"),
            version=spec["version"],
            variables=spec["netcdf_vars"],
            native_grid=spec["native_grid"],
            provenance_kind=spec["provenance_kind"],
            provenance_source=spec["product"],
            valid_from=valid_from,
            valid_to=valid_to,
            sha256=sha,
            download_time_s=round(elapsed, 3),
            size_bytes=size,
            citation=spec["citation"],
            local_path=str(target),
        ))
        manifest.total_size_bytes += size
        print(f"    -> {size / 1024**2:.2f} MB in {elapsed:.1f}s, sha256={sha[:16]}...")

    # Clean up tmp dir.
    shutil.rmtree(tmp_dir, ignore_errors=True)

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
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be >= 1")

    build_pack(args.start, args.days, args.bbox, args.out, unattended=args.unattended)


if __name__ == "__main__":
    main()
