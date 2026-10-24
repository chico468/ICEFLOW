"""Validated readers and local cache for real, non-synthetic flow fields.

This module never downloads data. The NOAA and Copernicus acquisition commands are
explicit; API requests only read files already present in the user cache.
"""
from __future__ import annotations

import json
import os
import sys
from dataclasses import dataclass
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import xarray as xr

FlowKind = Literal["wind", "current"]
SCHEMA_VERSION = 1
GFS_SOURCE = "NOAA National Centers for Environmental Prediction"
GFS_PRODUCT = "Global Forecast System (GFS) 0.25° 10 m wind"
CMEMS_SOURCE = "Copernicus Marine Service"
CMEMS_PRODUCT = "Global Total (COPERNICUS-GLOBCURRENT), surface current (NRT)"
CMEMS_DATASET = "cmems_obs-mob_glo_phy-cur_nrt_0.25deg_P1D-m"


class FlowDataError(RuntimeError):
    """A local flow file is malformed or incompatible with this reader."""


@dataclass(frozen=True)
class CachedFlow:
    kind: FlowKind
    lats: np.ndarray
    lons: np.ndarray
    u: np.ndarray
    v: np.ndarray
    metadata: dict[str, Any]
    path: Path


def default_flow_cache_dir() -> Path:
    configured = os.environ.get("ICEFLOW_FLOW_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()
    if sys.platform == "darwin":
        return Path.home() / "Library" / "Caches" / "ICEFLOW" / "flow"
    return Path(os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")).expanduser() / "iceflow" / "flow"


def _valid_axes(lats: np.ndarray, lons: np.ndarray, u: np.ndarray, v: np.ndarray) -> None:
    if lats.ndim != 1 or lons.ndim != 1 or lats.size < 2 or lons.size < 2:
        raise FlowDataError("Flow coordinates must be one-dimensional axes with at least two points.")
    if not np.isfinite(lats).all() or not np.isfinite(lons).all():
        raise FlowDataError("Flow coordinates contain non-finite values.")
    if not np.all(np.diff(lats) > 0) or not np.all(np.diff(lons) > 0):
        raise FlowDataError("Flow latitude and longitude axes must be strictly ascending.")
    if u.shape != (lats.size, lons.size) or v.shape != u.shape:
        raise FlowDataError("Flow velocity arrays do not match the latitude/longitude grid.")
    for axis, name in ((lats, "latitude"), (lons, "longitude")):
        steps = np.diff(axis)
        if not np.allclose(steps, np.median(steps), rtol=1e-4, atol=1e-7):
            raise FlowDataError(f"The {name} coordinate is not a regular grid.")
    if not (np.isfinite(u).any() and np.isfinite(v).any()):
        raise FlowDataError("The flow grid contains no valid velocity values.")
    if np.any(np.isfinite(u) != np.isfinite(v)):
        raise FlowDataError("Eastward and northward component masks do not match.")


def cache_flow(
    kind: FlowKind,
    lats: np.ndarray,
    lons: np.ndarray,
    u: np.ndarray,
    v: np.ndarray,
    metadata: dict[str, Any],
    *,
    cache_dir: str | Path | None = None,
) -> Path:
    """Validate then atomically store an NPZ grid and JSON provenance sidecar."""
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)
    u = np.asarray(u, dtype=np.float32)
    v = np.asarray(v, dtype=np.float32)
    _valid_axes(lats, lons, u, v)
    if metadata.get("units") != "m/s":
        raise FlowDataError("Flow velocity units must be metres per second.")
    if not metadata.get("valid_time") or not metadata.get("source") or not metadata.get("product"):
        raise FlowDataError("Flow provenance must include source, product, and valid_time.")
    valid_time = _parse_time(metadata["valid_time"])
    root = Path(cache_dir).expanduser() if cache_dir else default_flow_cache_dir()
    root.mkdir(parents=True, exist_ok=True)
    path = root / f"{kind}_{valid_time:%Y%m%dT%H%M%SZ}.npz"
    sidecar = path.with_suffix(".json")
    clean_metadata = dict(metadata)
    clean_metadata.update({"schema_version": SCHEMA_VERSION, "kind": kind, "valid_time": valid_time.isoformat()})
    tmp_npz = path.with_suffix(".npz.part")
    tmp_json = sidecar.with_suffix(".json.part")
    try:
        with tmp_npz.open("wb") as stream:
            np.savez_compressed(stream, lats=lats, lons=lons, u=u, v=v)
        tmp_json.write_text(json.dumps(clean_metadata, indent=2) + "\n", encoding="utf-8")
        os.replace(tmp_npz, path)
        os.replace(tmp_json, sidecar)
    finally:
        tmp_npz.unlink(missing_ok=True)
        tmp_json.unlink(missing_ok=True)
    return path


def _parse_time(value: str) -> datetime:
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except (TypeError, ValueError) as exc:
        raise FlowDataError("Flow valid_time must be an ISO-8601 timestamp.") from exc
    if parsed.tzinfo is None:
        raise FlowDataError("Flow valid_time must include a timezone.")
    return parsed.astimezone(timezone.utc)


def read_cached_flow(
    kind: FlowKind,
    *,
    valid_date: date | None = None,
    cache_dir: str | Path | None = None,
) -> CachedFlow | None:
    root = Path(cache_dir).expanduser() if cache_dir else default_flow_cache_dir()
    if not root.is_dir():
        return None
    candidates: list[tuple[datetime, Path]] = []
    for path in root.glob(f"{kind}_*.npz"):
        sidecar = path.with_suffix(".json")
        try:
            metadata = json.loads(sidecar.read_text(encoding="utf-8"))
            if metadata.get("schema_version") != SCHEMA_VERSION or metadata.get("kind") != kind:
                continue
            valid_time = _parse_time(metadata["valid_time"])
            if valid_date is not None and valid_time.date() != valid_date:
                continue
            candidates.append((valid_time, path))
        except (OSError, ValueError, KeyError, TypeError, FlowDataError):
            continue
    if not candidates:
        return None
    _, path = max(candidates, key=lambda item: (item[0], item[1].stat().st_mtime_ns))
    try:
        metadata = json.loads(path.with_suffix(".json").read_text(encoding="utf-8"))
        if path.stat().st_size == 0:
            raise FlowDataError("Cached file is empty.")
        with np.load(path, allow_pickle=False) as archive:
            required = {"lats", "lons", "u", "v"}
            if set(archive.files) != required:
                raise FlowDataError("Cached flow file has an unexpected set of arrays.")
            lats = np.asarray(archive["lats"], dtype=np.float64)
            lons = np.asarray(archive["lons"], dtype=np.float64)
            u = np.asarray(archive["u"], dtype=np.float32)
            v = np.asarray(archive["v"], dtype=np.float32)
        _valid_axes(lats, lons, u, v)
        return CachedFlow(kind, lats, lons, u, v, metadata, path)
    except (OSError, ValueError, KeyError) as exc:
        raise FlowDataError(f"Cached flow file is unusable: {exc}") from exc


def _bracket(axis: np.ndarray, value: float) -> tuple[int, int, float] | None:
    if value < axis[0] - 1e-8 or value > axis[-1] + 1e-8:
        return None
    if value >= axis[-1] - 1e-8:
        return axis.size - 2, axis.size - 1, 1.0
    hi = int(np.searchsorted(axis, value, side="right"))
    lo = max(0, hi - 1)
    return lo, hi, (value - axis[lo]) / (axis[hi] - axis[lo])


def sample_regular_flow(flow: CachedFlow, lat: float, lon: float) -> tuple[float, float] | None:
    """Bilinearly sample a regular geographic grid; missing corners stay missing."""
    lat_bracket = _bracket(flow.lats, lat)
    if lat_bracket is None:
        return None
    lon_axis = flow.lons
    periodic = np.isclose((lon_axis[-1] - lon_axis[0]) + np.median(np.diff(lon_axis)), 360.0, atol=1e-4)
    normalized_lon = ((lon - lon_axis[0]) % 360.0) + lon_axis[0] if periodic else lon
    lon_bracket = _bracket(lon_axis, normalized_lon)
    if lon_bracket is None and periodic and normalized_lon > lon_axis[-1]:
        j0, j1 = lon_axis.size - 1, 0
        tx = (normalized_lon - lon_axis[-1]) / (lon_axis[0] + 360.0 - lon_axis[-1])
    elif lon_bracket is not None:
        j0, j1, tx = lon_bracket
    else:
        return None
    i0, i1, ty = lat_bracket
    corners = (
        (i0, j0, (1 - ty) * (1 - tx)),
        (i0, j1, (1 - ty) * tx),
        (i1, j0, ty * (1 - tx)),
        (i1, j1, ty * tx),
    )
    u_value = 0.0
    v_value = 0.0
    for i, j, weight in corners:
        if weight <= 1e-12:
            continue
        u_cell, v_cell = flow.u[i, j], flow.v[i, j]
        if not np.isfinite(u_cell) or not np.isfinite(v_cell):
            return None
        u_value += float(u_cell) * weight
        v_value += float(v_cell) * weight
    return u_value, v_value


def grid_subset(
    flow: CachedFlow,
    lat_min: float,
    lat_max: float,
    lon_min: float,
    lon_max: float,
    resolution_deg: float,
) -> tuple[list[float], list[float], list[list[float | None]], list[list[float | None]]]:
    """Sample a bounded regular output grid without filling source missing cells."""
    lats = np.arange(lat_min, lat_max + 1e-9, resolution_deg, dtype=np.float64)
    lons = np.arange(lon_min, lon_max + 1e-9, resolution_deg * 2, dtype=np.float64)
    if lats.size < 2 or lons.size < 2:
        raise FlowDataError("Requested output grid must contain at least two points per axis.")
    out_u = np.full((lats.size, lons.size), np.nan, dtype=np.float32)
    out_v = np.full_like(out_u, np.nan)
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            sample = sample_regular_flow(flow, float(lat), float(lon))
            if sample is not None:
                out_u[i, j], out_v[i, j] = sample
    if not np.isfinite(out_u).any():
        raise FlowDataError("Requested area has no valid source coverage.")

    def as_nullable_rows(array: np.ndarray) -> list[list[float | None]]:
        return [[float(x) if np.isfinite(x) else None for x in row] for row in array]

    return lats.round(5).tolist(), lons.round(5).tolist(), as_nullable_rows(out_u), as_nullable_rows(out_v)


def read_copernicus_current_file(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, datetime]:
    """Read one Copernicus surface-current NetCDF subset and normalize axes to ascending lon/lat."""
    path = Path(path).expanduser()
    if not path.is_file():
        raise FlowDataError(f"Copernicus NetCDF does not exist: {path}")
    try:
        with xr.open_dataset(path, engine="netcdf4", decode_cf=True, mask_and_scale=True) as ds:
            if not {"uo", "vo", "latitude", "longitude", "time"}.issubset(ds.variables):
                raise FlowDataError("Expected Copernicus variables uo, vo, latitude, longitude, and time.")
            lat_coord, lon_coord = ds["latitude"], ds["longitude"]
            if lat_coord.attrs.get("units", "").lower() not in {"degrees_north", "degree_north"}:
                raise FlowDataError("Copernicus latitude coordinates must use degrees_north.")
            if lon_coord.attrs.get("units", "").lower() not in {"degrees_east", "degree_east"}:
                raise FlowDataError("Copernicus longitude coordinates must use degrees_east.")
            for name in ("uo", "vo"):
                if ds[name].attrs.get("units", "").replace(" ", "").lower() not in {"m/s", "ms-1", "m.s-1"}:
                    raise FlowDataError(f"Copernicus {name} units must be m/s.")
            time_values = np.asarray(ds["time"].values).reshape(-1)
            if time_values.size != 1:
                raise FlowDataError("Expected exactly one daily-mean Copernicus valid time.")
            time_seconds = int(np.datetime64(time_values[0], "s").astype("int64"))
            valid_time = datetime.fromtimestamp(time_seconds, tz=timezone.utc)
            lats = np.asarray(lat_coord.values, dtype=np.float64)
            lons = np.asarray(lon_coord.values, dtype=np.float64)
            def component(name: str) -> np.ndarray:
                variable = ds[name]
                selectors: dict[str, int] = {}
                for dim in variable.dims:
                    if dim == "time":
                        selectors[dim] = 0
                    elif dim in {"depth", "depthu", "depthv"}:
                        depth_axis = np.asarray(ds[dim].values, dtype=np.float64).reshape(-1)
                        selectors[dim] = int(np.argmin(np.abs(depth_axis)))
                return np.asarray(variable.isel(selectors).transpose("latitude", "longitude").values, dtype=np.float64)
            u, v = component("uo"), component("vo")
    except FlowDataError:
        raise
    except Exception as exc:
        raise FlowDataError(f"Could not read Copernicus NetCDF: {exc}") from exc
    if lats.ndim != 1 or lons.ndim != 1 or u.shape != (lats.size, lons.size) or v.shape != u.shape:
        raise FlowDataError("Copernicus current arrays do not match their coordinate dimensions.")
    lat_order = np.argsort(lats)
    lats = lats[lat_order]
    u, v = u[lat_order, :], v[lat_order, :]
    lons = ((lons + 180.0) % 360.0) - 180.0
    lon_order = np.argsort(lons, kind="stable")
    lons = lons[lon_order]
    u, v = u[:, lon_order], v[:, lon_order]
    unique_lons, unique_indices = np.unique(np.round(lons, 7), return_index=True)
    lons = unique_lons
    u, v = u[:, unique_indices], v[:, unique_indices]
    _valid_axes(lats, lons, u, v)
    return lats, lons, u, v, valid_time


def _regularize_gfs_grid(lats_flat: np.ndarray, lons_flat: np.ndarray, values_flat: np.ndarray) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    """Rebuild an ecCodes scan-order GRIB message into ascending geographic row/column order."""
    lats = np.asarray(lats_flat, dtype=np.float64)
    lons = ((np.asarray(lons_flat, dtype=np.float64) + 180.0) % 360.0) - 180.0
    values = np.asarray(values_flat, dtype=np.float64)
    if lats.ndim != 1 or lons.shape != lats.shape or values.shape != lats.shape:
        raise FlowDataError("GFS GRIB coordinate and value arrays have different shapes.")
    lat_axis = np.unique(np.round(lats, 6))
    lon_axis = np.unique(np.round(lons, 6))
    if lat_axis.size * lon_axis.size != lats.size:
        # A single duplicated 0/360 seam column is valid for a global grid.
        pairs = np.column_stack((np.round(lats, 6), np.round(lons, 6)))
        unique_pairs = np.unique(pairs, axis=0)
        if unique_pairs.shape[0] != lat_axis.size * lon_axis.size:
            raise FlowDataError("GFS GRIB coordinates do not form a complete regular grid.")
    out = np.full((lat_axis.size, lon_axis.size), np.nan, dtype=np.float32)
    row = np.searchsorted(lat_axis, np.round(lats, 6))
    col = np.searchsorted(lon_axis, np.round(lons, 6))
    for k, (i, j) in enumerate(zip(row, col, strict=True)):
        if np.isfinite(out[i, j]) and not np.isclose(out[i, j], values[k], atol=1e-5):
            raise FlowDataError("Duplicate GFS longitude seam cells have conflicting velocities.")
        out[i, j] = values[k]
    return lat_axis.astype(np.float64), lon_axis.astype(np.float64), out


def read_gfs_grib(path: str | Path) -> tuple[np.ndarray, np.ndarray, np.ndarray, np.ndarray, dict[str, Any]]:
    """Decode the two selected GFS GRIB2 10 m wind messages using ECMWF ecCodes."""
    try:
        import eccodes
    except ImportError as exc:
        raise FlowDataError("Install the required GRIB decoder with `pip install eccodes`.") from exc
    grids: dict[str, tuple[np.ndarray, np.ndarray, np.ndarray, dict[str, int]]] = {}
    try:
        with Path(path).open("rb") as stream:
            while True:
                gid = eccodes.codes_grib_new_from_file(stream)
                if gid is None:
                    break
                try:
                    short_name = str(eccodes.codes_get(gid, "shortName")).lower()
                    level_type = str(eccodes.codes_get(gid, "typeOfLevel"))
                    level = int(eccodes.codes_get(gid, "level"))
                    if level_type != "heightAboveGround" or level != 10 or short_name not in {"10u", "10v"}:
                        continue
                    units = str(eccodes.codes_get(gid, "units")).replace(" ", "").lower()
                    if units not in {"ms-1", "m/s", "m.s-1"}:
                        raise FlowDataError(f"Unexpected GFS wind unit: {units}.")
                    data_date = int(eccodes.codes_get(gid, "dataDate"))
                    data_time = int(eccodes.codes_get(gid, "dataTime"))
                    valid_date = int(eccodes.codes_get(gid, "validityDate"))
                    valid_time = int(eccodes.codes_get(gid, "validityTime"))
                    forecast_hour = int(eccodes.codes_get(gid, "forecastTime"))
                    latitudes = np.asarray(eccodes.codes_get_array(gid, "latitudes"), dtype=np.float64)
                    longitudes = np.asarray(eccodes.codes_get_array(gid, "longitudes"), dtype=np.float64)
                    values = np.asarray(eccodes.codes_get_array(gid, "values"), dtype=np.float64)
                    grids[short_name] = (latitudes, longitudes, values, {
                        "data_date": data_date,
                        "data_time": data_time,
                        "valid_date": valid_date,
                        "valid_time": valid_time,
                        "forecast_hour": forecast_hour,
                    })
                finally:
                    eccodes.codes_release(gid)
    except FlowDataError:
        raise
    except Exception as exc:
        raise FlowDataError(f"Could not decode NOAA GFS GRIB2 file: {exc}") from exc
    if set(grids) != {"10u", "10v"}:
        raise FlowDataError("GFS GRIB2 file must contain both 10 m eastward (10u) and northward (10v) wind.")
    u_item, v_item = grids["10u"], grids["10v"]
    if u_item[3] != v_item[3] or not (np.array_equal(u_item[0], v_item[0]) and np.array_equal(u_item[1], v_item[1])):
        raise FlowDataError("GFS wind components have inconsistent timestamps or grid orientation.")
    lats, lons, u = _regularize_gfs_grid(*u_item[:3])
    v_lats, v_lons, v = _regularize_gfs_grid(*v_item[:3])
    if not (np.array_equal(lats, v_lats) and np.array_equal(lons, v_lons)):
        raise FlowDataError("GFS wind component grids are not aligned.")
    _valid_axes(lats, lons, u, v)
    keys = u_item[3]
    valid_time = datetime.strptime(f"{keys['valid_date']:08d}{keys['valid_time']:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    run_time = datetime.strptime(f"{keys['data_date']:08d}{keys['data_time']:04d}", "%Y%m%d%H%M").replace(tzinfo=timezone.utc)
    return lats, lons, u, v, {
        "source": GFS_SOURCE,
        "product": GFS_PRODUCT,
        "classification": "forecast",
        "units": "m/s",
        "native_resolution_deg": 0.25,
        "model_run_time": run_time.isoformat(),
        "valid_time": valid_time.isoformat(),
        "forecast_lead_hours": keys["forecast_hour"],
    }


def import_copernicus_current_file(
    source_path: str | Path,
    *,
    cache_dir: str | Path | None = None,
    retrieved_at: datetime | None = None,
) -> Path:
    lats, lons, u, v, valid_time = read_copernicus_current_file(source_path)
    retrieved = retrieved_at or datetime.now(timezone.utc)
    return cache_flow("current", lats, lons, u, v, {
        "source": CMEMS_SOURCE,
        "product": CMEMS_PRODUCT,
        "dataset_id": CMEMS_DATASET,
        "classification": "observation_based_analysis",
        "units": "m/s",
        "native_resolution_deg": 0.25,
        "valid_time": valid_time.isoformat(),
        "retrieved_at": retrieved.astimezone(timezone.utc).isoformat(),
        "source_file": str(Path(source_path).expanduser().resolve()),
        "depth_m": 0.0,
        "time_meaning": "daily mean centred at 12:00 UTC",
        "crs": "EPSG:4326",
        "coordinate_units": "degrees_north, degrees_east",
    }, cache_dir=cache_dir)

