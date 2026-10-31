"""Build a resumable core sea-ice forecast pack from real data sources.

Downloads real data products into one cache directory and writes a
``manifest.json`` so that ``ReplayProvider`` can load them.

Data sources:
  1. ERA5 wind (u10/v10) at 3-hourly resolution from the ARCO-ERA5 v3 zarr store
     on Google Cloud Storage (no CDS API key required).
  2. ERA5 waves (swh) at 3-hourly resolution from the same ARCO-ERA5 store.
  3. GLORYS12V1 surface currents (uo/vo) at 3-hourly resolution from Copernicus
     Marine (``cmems_mod_glo_phy_anfc_merged-uv_PT1H-i``, version 202311).
  4. NSIDC Version 6 Antarctic sea-ice concentration (daily, 25 km polar
     stereographic) from the NSIDC HTTPS server (G02202 V6).

A GLORYS12V1 siconc daily field (``cmems_mod_glo_phy_my_0.083deg_P1D-m``) is also
fetched for ice-box validation of the NSIDC observations against the reanalysis.

Before downloading anything, the script prints the total estimated size and
aborts when the estimate exceeds 5 GB.  ``manifest.json`` records SHA-256,
provenance and local path for every output file.  Re-running skips products that
already exist and are verified.

Usage::

    python -m scripts.build_replay_pack \
        --start 2022-01-15 --days 33 \
        --bbox "-180,-90,180,-60" \
        --out /tmp/iceflow-replay-pack
"""

from __future__ import annotations

import argparse
import hashlib
import json
import sys
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import numpy as np
import xarray as xr

MAX_UNATTENDED_BYTES = 5 * 1024**3

ARCO_ERA5_URL = (
    "https://storage.googleapis.com/gcp-public-data-arco-era5"
    "/ar/full_37-1h-0p25deg-chunk-1.zarr-v3"
)

ERA5_VAR_MAP = {
    "u10": "10m_u_component_of_wind",
    "v10": "10m_v_component_of_wind",
    "swh": "significant_height_of_combined_wind_waves_and_swell",
    "t2m": "2m_temperature",
    "msl": "mean_sea_level_pressure",
}

ERA5_UNITS = {
    "u10": "m s-1",
    "v10": "m s-1",
    "swh": "m",
    "t2m": "K",
    "msl": "Pa",
}

ERA5_LONG_NAME = {
    "u10": "10 metre U wind component",
    "v10": "10 metre V wind component",
    "swh": "Significant height of combined wind waves and swell",
    "t2m": "2 metre temperature",
    "msl": "Mean sea level pressure",
}

ERA5_CITATION = (
    "Hersbach et al. (2023), ERA5 fifth generation of reanalysis, "
    "Copernicus Climate Change Service (C3S) Climate Data Store, "
    "https://doi.org/10.24381/cds.bd0915c6"
)

ERA5_PROVENANCE = "ERA5 hourly, subsampled to 3-hourly"

CMEMS_GLORYS_CURRENT_DS = "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
CMEMS_GLORYS_SIC_DS = "cmems_mod_glo_phy_my_0.083deg_P1D-m"
CMEMS_GLORYS_VERSION = "202311"
CMEMS_CITATION = "https://doi.org/10.48670/moi-00016"

NSIDC_BASE_URL = "https://noaadata.apps.nsidc.org/NOAA/G02202_V6/south/daily"
NSIDC_CITATION = "https://doi.org/10.7265/b18j-z797"

THREE_HOURLY_OFFSETS = [0, 3, 6, 9, 12, 15, 18, 21]

GLORYS_MAX_LAT = -80.0

# Extra ERA5 variables (optional, included only when pack stays under 5 GB).
EXTRA_ERA5_VARS: dict[str, str] = {
    "t2m": "2m_temperature",
    "msl": "mean_sea_level_pressure",
}

# Wind variables go in era5_wind_10m, wave vars go in era5_waves.
WIND_VARS = ["u10", "v10"]
WAVE_VARS = ["swh"]


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
    provenance_note: str | None
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
                    "provenance_note": p.provenance_note,
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
                    provenance_note=p.get("provenance_note"),
                    local_path=p["local_path"],
                    valid_from=p.get("valid_from"),
                    valid_to=p.get("valid_to"),
                )
                for p in data["products"]
            ],
        )

    def find(self, product: str) -> ProductRecord | None:
        for p in self.products:
            if p.product == product:
                return p
        return None


# ---------------------------------------------------------------------------
# Utilities
# ---------------------------------------------------------------------------

def _sha256_of_file(path: Path) -> str:
    h = hashlib.sha256()
    with path.open("rb") as fh:
        for chunk in iter(lambda: fh.read(1 << 20), b""):
            h.update(chunk)
    return h.hexdigest()


def _product_filename(product: str, start: date, days: int) -> str:
    return f"{product}_{start:%Y%m%d}_{days}d.nc"


def _estimate_era5_bytes(lat_deg: float, lon_deg: float, days: int, n_vars: int) -> int:
    grid_cells = int(lat_deg / 0.25) * int(lon_deg / 0.25)
    time_steps = len(THREE_HOURLY_OFFSETS) * days
    return grid_cells * time_steps * 4 * n_vars  # float32


def _estimate_pack_bytes(
    start: date,
    days: int,
    bbox: tuple[float, float, float, float],
    include_extras: bool,
) -> int:
    lat_deg = abs(bbox[3] - bbox[1])
    lon_deg = abs(bbox[2] - bbox[0])

    era5_vars = len(WIND_VARS) + len(WAVE_VARS)
    if include_extras:
        era5_vars += len(EXTRA_ERA5_VARS)
    era5_bytes = _estimate_era5_bytes(lat_deg, lon_deg, days, era5_vars)

    g_lat_deg = min(lat_deg, abs(bbox[3] - GLORYS_MAX_LAT)) if bbox[1] < GLORYS_MAX_LAT else lat_deg
    g_lat = max(bbox[1], GLORYS_MAX_LAT)
    glorys_cells = int((bbox[3] - g_lat) / 0.0833) * int(lon_deg / 0.0833)
    glorys_time = len(THREE_HOURLY_OFFSETS) * days
    glorys_bytes = glorys_cells * glorys_time * 4 * 2  # uo, vo

    nsidc_bytes = 340_000 * days
    glorys_sic_bytes = glorys_cells * days * 4

    return era5_bytes + glorys_bytes + glorys_sic_bytes + nsidc_bytes


def _three_hourly_time_indices(start: date, days: int) -> np.ndarray:
    base_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    arr = []
    for d in range(days):
        for h in THREE_HOURLY_OFFSETS:
            ts = base_dt + timedelta(days=d, hours=h)
            arr.append(np.datetime64(ts.replace(tzinfo=None), "ns"))
    return np.array(arr)


def _nsidc_filename(day: date) -> str:
    if day.year >= 2025:
        sensor = "am2"
    elif day.year >= 2008:
        sensor = "F17"
    elif day.year >= 1995:
        sensor = "F13"
    elif day.year >= 1992:
        sensor = "F11"
    elif day.year >= 1987:
        sensor = "F08"
    else:
        sensor = "n07"
    return f"sic_pss25_{day:%Y%m%d}_{sensor}_v06r00.nc"


def _download_nsidc_file(url: str, target: Path, timeout: float = 30.0) -> bool:
    request = urllib.request.Request(
        url, headers={"User-Agent": "ICEFLOW NSIDC observational reader"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read()
    except urllib.error.HTTPError as exc:
        return False
    except (urllib.error.URLError, TimeoutError, OSError):
        return False
    if not payload:
        return False
    tmp = target.with_name(target.name + ".part")
    tmp.write_bytes(payload)
    tmp.replace(target)
    return True


# ---------------------------------------------------------------------------
# Downloaders
# ---------------------------------------------------------------------------

def _era5_three_hourly(
    start: date,
    days: int,
    lat_slice: slice,
    lon_slice: slice,
    out: Path,
    wind_vars: list[str],
    wave_vars: list[str],
    extra_vars: list[str],
) -> tuple[dict[str, Path], float]:
    import warnings
    warnings.filterwarnings("ignore", category=FutureWarning)

    product_start = time.perf_counter()
    # Open WITHOUT dask for fast metadata read; data is fetched lazily per day.
    ds = xr.open_dataset(ARCO_ERA5_URL, engine="zarr", consolidated=True)

    # Build per-day time index arrays.
    base_dt = datetime(start.year, start.month, start.day, tzinfo=timezone.utc)
    day_time_indices: list[np.ndarray] = []
    for d in range(days):
        day_ts = []
        for h in THREE_HOURLY_OFFSETS:
            ts = base_dt + timedelta(days=d, hours=h)
            day_ts.append(np.datetime64(ts.replace(tzinfo=None), "ns"))
        day_time_indices.append(np.array(day_ts))

    all_vars = wind_vars + wave_vars + extra_vars
    selected: dict[str, list[np.ndarray]] = {k: [] for k in all_vars}

    for day_idx in range(days):
        day_ts = day_time_indices[day_idx]
        for short_name in all_vars:
            arco_var = ERA5_VAR_MAP[short_name]
            if arco_var not in ds.variables:
                raise RuntimeError(f"ARCO-ERA5 does not have variable {arco_var}")
            data = ds[arco_var].sel(
                latitude=lat_slice,
                longitude=lon_slice,
                time=day_ts,
            ).values.astype(np.float32)
            selected[short_name].append(data)

    lats = np.asarray(ds["latitude"].sel(latitude=lat_slice).values, dtype=np.float64)
    lons = np.asarray(ds["longitude"].sel(longitude=lon_slice).values, dtype=np.float64)

    # Concatenate daily data and flip latitude to ascending.
    lat_order = np.argsort(lats)
    lats = lats[lat_order]
    final_selected: dict[str, np.ndarray] = {}
    for short_name in all_vars:
        arr = np.stack(selected[short_name], axis=0)  # (days, 8, lat, lon)
        arr = arr.reshape(-1, arr.shape[2], arr.shape[3])  # (days*8, lat, lon)
        arr = arr[:, lat_order, :]  # flip latitude to ascending
        final_selected[short_name] = arr

    # Build full time coordinate.
    all_time_indices = np.concatenate(day_time_indices)

    def _write_vars(vars_to_write: list[str], filename: str) -> Path:
        target = out / filename
        out_ds = xr.Dataset()
        for short_name in vars_to_write:
            out_ds[short_name] = xr.DataArray(
                final_selected[short_name],
                dims=("time", "latitude", "longitude"),
                coords={"time": all_time_indices, "latitude": lats, "longitude": lons},
                attrs={
                    "units": ERA5_UNITS[short_name],
                    "long_name": ERA5_LONG_NAME[short_name],
                },
            )
        out_ds.attrs = {
            "title": f"ERA5 3-hourly {filename.split('_')[0]} subset",
            "source": "ECMWF ERA5 (ARCO-ERA5 v3)",
            "provenance": ERA5_PROVENANCE,
            "citation": ERA5_CITATION,
        }
        out_ds.to_netcdf(
            target,
            engine="netcdf4",
            encoding={v: {"zlib": True, "complevel": 2} for v in out_ds.data_vars},
        )
        return target

    elapsed_total = time.perf_counter() - product_start
    paths: dict[str, Path] = {}

    if wind_vars:
        paths["era5_wind_10m"] = _write_vars(wind_vars, _product_filename("era5_wind_10m", start, days))

    if wave_vars:
        wave_all = list(wave_vars) + list(extra_vars)
        paths["era5_waves"] = _write_vars(wave_all, _product_filename("era5_waves", start, days))

    return paths, elapsed_total


def _glorys_currents_three_hourly(
    start: date,
    days: int,
    west: float,
    south: float,
    east: float,
    north: float,
    out: Path,
) -> tuple[Path, float]:
    from copernicusmarine import open_dataset

    product_start = time.perf_counter()
    target = out / _product_filename("cmems_current", start, days)

    end_dt = f"{(start + timedelta(days=days - 1)).isoformat()}T21:00:00Z"

    ds = open_dataset(
        dataset_id=CMEMS_GLORYS_CURRENT_DS,
        variables=["uo", "vo"],
        start_datetime=f"{start.isoformat()}T00:00:00Z",
        end_datetime=end_dt,
        minimum_longitude=west,
        maximum_longitude=east,
        minimum_latitude=max(south, GLORYS_MAX_LAT),
        maximum_latitude=north,
    )

    time_indices = _three_hourly_time_indices(start, days)
    ds_3h = ds.sel(time=time_indices)

    # Drop the depth dimension (surface currents at 0.49 m, single level).
    if "depth" in ds_3h.dims:
        ds_3h = ds_3h.isel(depth=0).drop_vars("depth")

    out_ds = ds_3h[["uo", "vo"]].astype(np.float32).compute()
    out_ds.attrs = {
        "title": "GLORYS12V1 merged hourly surface currents, subsampled to 3-hourly",
        "source": "MERCATOR GLO12, mfwamglo, FES2014",
        "provenance": f"GLORYS12V1 reanalysis, version {CMEMS_GLORYS_VERSION}",
        "provenance_note": "surface current, not keel-depth",
        "license": "Copernicus Marine Service",
        "citation": CMEMS_CITATION,
    }
    out_ds.to_netcdf(
        target,
        engine="netcdf4",
        encoding={v: {"zlib": True, "complevel": 2} for v in out_ds.data_vars},
    )
    elapsed = time.perf_counter() - product_start
    return target, elapsed


def _glorys_siconc_daily(
    start: date,
    days: int,
    west: float,
    south: float,
    east: float,
    north: float,
    out: Path,
) -> tuple[Path, float]:
    from copernicusmarine import open_dataset

    product_start = time.perf_counter()
    target = out / _product_filename("glorys_siconc", start, days)

    end_date = (start + timedelta(days=days - 1)).isoformat()
    end_dt = f"{end_date}T12:00:00Z"

    ds = open_dataset(
        dataset_id=CMEMS_GLORYS_SIC_DS,
        variables=["siconc"],
        start_datetime=f"{start.isoformat()}T00:00:00Z",
        end_datetime=end_dt,
        minimum_longitude=west,
        maximum_longitude=east,
        minimum_latitude=max(south, GLORYS_MAX_LAT),
        maximum_latitude=north,
    )

    out_ds = ds[["siconc"]].astype(np.float32).compute()
    out_ds.attrs = {
        "title": "GLORYS12V1 daily sea-ice concentration",
        "source": "MERCATOR GLORYS12V1",
        "provenance": f"GLORYS12V1 reanalysis, version {CMEMS_GLORYS_VERSION}",
        "citation": CMEMS_CITATION,
    }
    out_ds.to_netcdf(
        target,
        engine="netcdf4",
        encoding={"siconc": {"zlib": True, "complevel": 2}},
    )
    elapsed = time.perf_counter() - product_start
    return target, elapsed


def _nsidc_sic_daily(
    start: date,
    days: int,
    out: Path,
) -> tuple[Path, float]:
    from src.data.nsidc_sea_ice import NSIDCDataError, NSIDCUnavailableError, read_nsidc_file

    product_start = time.perf_counter()
    target = out / _product_filename("nrt_ice_concentration", start, days)

    cache_dir = out / "nsidc_raw_cache"
    cache_dir.mkdir(parents=True, exist_ok=True)

    observations: list[dict] = []

    for d in range(days):
        day = start + timedelta(days=d)
        filename = _nsidc_filename(day)
        url = f"{NSIDC_BASE_URL}/{day:%Y}/{filename}"
        local_path = cache_dir / filename

        if not local_path.is_file():
            ok = _download_nsidc_file(url, local_path)
            if not ok:
                print(f"  [warn] NSIDC: file not available for {day.isoformat()} ({filename})", file=sys.stderr)
                continue

        try:
            obs = read_nsidc_file(local_path, source_url=url, retrieved_from_cache=True)
        except (NSIDCDataError, NSIDCUnavailableError) as exc:
            print(f"  [warn] NSIDC: cannot read {filename}: {exc}", file=sys.stderr)
            continue

        observations.append({
            "date": day.isoformat(),
            "concentration": obs.concentration,
            "x_m": obs.x_m,
            "y_m": obs.y_m,
            "source_url": obs.source_url,
        })

    if not observations:
        raise RuntimeError("No NSIDC observations downloaded")

    first = observations[0]
    conc = np.stack([o["concentration"] for o in observations])
    times = np.array([np.datetime64(o["date"], "D") for o in observations])

    out_ds = xr.Dataset(
        {"ice_conc": (["time", "y", "x"], conc.astype(np.float32))},
        coords={
            "time": times,
            "x": first["x_m"],
            "y": first["y_m"],
        },
    )
    out_ds.attrs = {
        "title": "NOAA/NSIDC CDR V6 Antarctic sea-ice concentration",
        "source": "NSIDC/NOAA",
        "provenance": "observed",
        "citation": NSIDC_CITATION,
    }
    out_ds["ice_conc"].attrs = {
        "units": "1",
        "long_name": "Sea ice concentration",
        "grid_mapping": "crs",
    }
    out_ds.to_netcdf(
        target,
        engine="netcdf4",
        encoding={"ice_conc": {"zlib": True, "complevel": 2}},
    )
    elapsed = time.perf_counter() - product_start
    return target, elapsed


# ---------------------------------------------------------------------------
# CLI
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
    include_extras: bool = True,
) -> Manifest:
    """Download the core sea-ice forecast pack for the requested window into ``out``."""
    out.mkdir(parents=True, exist_ok=True)
    west, south, east, north = bbox

    estimated = _estimate_pack_bytes(start, days, bbox, include_extras)
    if not unattended and estimated > MAX_UNATTENDED_BYTES:
        print(
            f"Estimated download size {estimated / 1024**3:.2f} GB exceeds the 5 GB unattended limit. "
            "Re-run with --unattended to proceed anyway.",
            file=sys.stderr,
        )
        raise SystemExit(2)

    print(f"Estimated total download size: {estimated / 1024**3:.4f} GB")
    print(f"Output directory: {out}")
    print(f"Window: {start.isoformat()} + {days} day(s)")
    print(f"Bounding box: west={west}, south={south}, east={east}, north={north}")
    print(f"Time resolution: 3-hourly (00, 03, 06, 09, 12, 15, 18, 21 UTC)")
    print()

    # --- Resume: load existing manifest ---
    manifest_path = out / "manifest.json"
    existing: dict[str, ProductRecord] = {}
    if manifest_path.exists():
        existing_manifest = Manifest.load(manifest_path)
        for p in existing_manifest.products:
            ppath = out / Path(p.local_path).name
            if ppath.is_file() and _sha256_of_file(ppath) == p.sha256:
                existing[p.product] = p
        print(f"Resuming: {len(existing)} existing product(s) verified")

    manifest = Manifest(
        start=start.isoformat(),
        days=days,
        bbox=bbox,
        generated_at=datetime.now(timezone.utc).isoformat(),
        total_size_bytes=0,
    )

    def _record(product_name: str, ds_id: str, version: str, params: dict,
                sha: str, elapsed: float, sz: int, citation: str,
                provenance_kind: str, provenance_note: str | None,
                path: Path, vf=None, vt=None) -> None:
        manifest.products.append(ProductRecord(
            product=product_name,
            dataset_id=ds_id,
            version=version,
            request_params=params,
            sha256=sha,
            download_time_s=round(elapsed, 3),
            size_bytes=sz,
            citation=citation,
            provenance_kind=provenance_kind,
            provenance_note=provenance_note,
            local_path=str(path),
            valid_from=vf,
            valid_to=vt,
        ))
        manifest.total_size_bytes += sz

    def _skip_or_download(
        product_name: str,
        download_fn,
        ds_id: str,
        version: str,
        params: dict,
        citation: str,
        provenance_kind: str,
        provenance_note: str | None,
    ) -> None:
        if product_name in existing:
            print(f"  [skip] {product_name}: already cached and verified")
            _record(
                product_name, ds_id, version, params,
                existing[product_name].sha256, existing[product_name].download_time_s,
                existing[product_name].size_bytes, citation, provenance_kind, provenance_note,
                Path(existing[product_name].local_path),
                existing[product_name].valid_from, existing[product_name].valid_to,
            )
            return

        print(f"  [download] {product_name} from {ds_id} ...")
        try:
            result = download_fn()
            if isinstance(result, tuple) and isinstance(result[0], dict):
                paths, elapsed = result
                for sub_name, path in paths.items():
                    sha = _sha256_of_file(path)
                    sz = path.stat().st_size
                    print(f"    -> {path.name}: {sz / 1024**2:.2f} MB in {elapsed:.1f}s, sha256={sha[:16]}...")
                    _record(
                        sub_name, ds_id, version, params, sha, elapsed, sz,
                        citation, provenance_kind, provenance_note, path,
                    )
            else:
                path, elapsed = result
                sha = _sha256_of_file(path)
                sz = path.stat().st_size
                print(f"    -> {path.name}: {sz / 1024**2:.2f} MB in {elapsed:.1f}s, sha256={sha[:16]}...")
                _record(
                    product_name, ds_id, version, params, sha, elapsed, sz,
                    citation, provenance_kind, provenance_note, path,
                )
        except Exception as exc:
            print(f"  [error] {product_name}: {exc}", file=sys.stderr)

    # --- ARCO-ERA5 zarr ---
    lon_west = west if west >= 0 else west + 360.0
    lon_east = east if east >= 0 else east + 360.0
    if lon_east >= lon_west or (east - west) >= 360.0:
        lon_slice = slice(None)
    else:
        lon_slice = slice(lon_west, lon_east)
    lat_slice = slice(north, south)

    extra_vars = list(EXTRA_ERA5_VARS.keys()) if include_extras else []
    _skip_or_download(
        product_name="era5_wind_10m",
        download_fn=lambda: _era5_three_hourly(
            start, days, lat_slice, lon_slice, out,
            list(WIND_VARS), list(WAVE_VARS), extra_vars,
        ),
        ds_id="ARCO-ERA5 v3",
        version="ARCO-ERA5 v3",
        params={"bbox": list(bbox), "variables": WIND_VARS + WAVE_VARS + extra_vars, "freq": "3-hourly"},
        citation=ERA5_CITATION,
        provenance_kind="reanalysis",
        provenance_note=ERA5_PROVENANCE,
    )

    # --- GLORYS12V1 surface currents (3-hourly subset) ---
    _skip_or_download(
        product_name="cmems_current",
        download_fn=lambda: _glorys_currents_three_hourly(
            start, days, west, south, east, north, out,
        ),
        ds_id=CMEMS_GLORYS_CURRENT_DS,
        version=CMEMS_GLORYS_VERSION,
        params={"bbox": list(bbox), "variables": ["uo", "vo"]},
        citation=CMEMS_CITATION,
        provenance_kind="observation_based_analysis",
        provenance_note="surface current, not keel-depth",
    )

    # --- NSIDC V6 sea-ice concentration (daily) ---
    _skip_or_download(
        product_name="nrt_ice_concentration",
        download_fn=lambda: _nsidc_sic_daily(start, days, out),
        ds_id="NSIDC G02202 V6",
        version="V6",
        params={"bbox": list(bbox), "variables": ["ice_conc"]},
        citation=NSIDC_CITATION,
        provenance_kind="observation",
        provenance_note=None,
    )

    # --- GLORYS12V1 siconc (daily, for ice-box validation) ---
    _skip_or_download(
        product_name="glorys_siconc",
        download_fn=lambda: _glorys_siconc_daily(
            start, days, west, south, east, north, out,
        ),
        ds_id=CMEMS_GLORYS_SIC_DS,
        version=CMEMS_GLORYS_VERSION,
        params={"bbox": list(bbox), "variables": ["siconc"]},
        citation=CMEMS_CITATION,
        provenance_kind="reanalysis",
        provenance_note=None,
    )

    manifest.write(manifest_path)
    print(f"\nManifest written: {manifest_path}")
    print(f"Total size: {manifest.total_size_bytes / 1024**2:.2f} MB across {len(manifest.products)} product(s)")
    return manifest


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--start", required=True, type=parse_date, help="Start date, YYYY-MM-DD")
    parser.add_argument("--days", required=True, type=int, help="Number of days to cover (>=1)")
    parser.add_argument("--bbox", required=True, type=parse_bbox, help="west,south,east,north in degrees")
    parser.add_argument("--out", required=True, type=Path, help="Output cache directory")
    parser.add_argument("--unattended", action="store_true", help="Skip the >5 GB confirmation prompt")
    parser.add_argument("--no-extras", action="store_true", help="Skip extra ERA5 variables (t2m, msl)")
    args = parser.parse_args()

    if args.days < 1:
        parser.error("--days must be >= 1")

    build_pack(
        args.start,
        args.days,
        args.bbox,
        args.out,
        unattended=args.unattended,
        include_extras=not args.no_extras,
    )


if __name__ == "__main__":
    main()
