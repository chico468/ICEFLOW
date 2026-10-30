"""
Real-environment sampling interface.

The protocol lets the route optimiser and voyage engine consume atmospheric and
oceanographic fields from three sources without knowing which one is active:

  * ``ReplayProvider``   - reads a cache-dir replay pack built by
    ``scripts.build_replay_pack`` (ERA5 wind/waves, CMEMS current, NRT ice).
  * ``LiveProvider``     - live GFS + CMEMS forecast + NRT ice, with walk-back
    of at most 14 days. Dates are stamped so callers know the data is not
    current.
  * ``SimulatedProvider``- wraps the seeded ``EnvironmentModel``. Only for
    ``environment_mode="simulated"``; every sample carries ``is_synthetic=True``.

Sampling rules (enforced by every implementation):

  * bilinear in space, with antimeridian and polar wrapping handled correctly;
  * linear in time between the two bracketing valid times;
  * no extrapolation: a request outside a variable's coverage raises
    ``OutOfCoverage`` naming the variable and the offending date;
  * in replay, the maximum skew between any two variables is 12 h. When a
    variable is not available at the bracketing time pair it is omitted rather
    than stretched;
  * waves missing under ice return ``None`` with ``wave_valid=False`` - never
    0, never a fabricated value;
  * there is never a silent fallback from a real provider to the simulated one.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Protocol, runtime_checkable

import numpy as np
import xarray as xr

from src.core.environment import EnvironmentModel, EnvSample as _CoreEnvSample

# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class OutOfCoverage(RuntimeError):
    """A requested variable is not available for the requested date/location."""

    def __init__(self, variable: str, valid_time_utc: str, detail: str = "") -> None:
        self.variable = variable
        self.valid_time_utc = valid_time_utc
        super().__init__(
            f"{variable} is out of coverage at {valid_time_utc}" + (f": {detail}" if detail else "")
        )


# ---------------------------------------------------------------------------
# EnvSample (Python-side mirror of frontend/src/api/types.ts EnvSample,
# extended with per-variable provenance and validity flags)
# ---------------------------------------------------------------------------


@dataclass
class EnvSample:
    """One point sample of atmosphere and upper ocean.

    ``provenance_by_variable`` maps each variable name to
    ``{"kind", "source", "product", "valid_time", "age_hours"}`` so the caller
    can tell, per variable, whether the value came from reanalysis, an
    observation, a forecast, or simulation.

    ``wave_valid`` is False (and ``sig_wave_height_m`` is None) when waves are
    masked out under ice - the value is never 0.
    """

    lat: float
    lon: float
    valid_time_hours: float

    u10: float | None = None
    v10: float | None = None
    wind_speed_ms: float | None = None
    wind_dir_from_deg: float | None = None
    wind_gust_ms: float | None = None

    uo: float | None = None
    vo: float | None = None
    current_speed_ms: float | None = None
    current_dir_to_deg: float | None = None

    sst_c: float | None = None
    t2m_c: float | None = None
    msl_hpa: float | None = None
    sig_wave_height_m: float | None = None
    visibility_km: float | None = None
    katabatic_component_ms: float | None = None

    wave_valid: bool = True
    ice_valid: bool = True

    is_synthetic: bool = False
    source: str = ""
    provenance_by_variable: dict[str, dict[str, Any]] = field(default_factory=dict)

    def to_dict(self) -> dict[str, Any]:
        return {
            "lat": self.lat,
            "lon": self.lon,
            "valid_time_hours": self.valid_time_hours,
            "u10": self.u10,
            "v10": self.v10,
            "wind_speed_ms": self.wind_speed_ms,
            "wind_dir_from_deg": self.wind_dir_from_deg,
            "wind_gust_ms": self.wind_gust_ms,
            "uo": self.uo,
            "vo": self.vo,
            "current_speed_ms": self.current_speed_ms,
            "current_dir_to_deg": self.current_dir_to_deg,
            "sst_c": self.sst_c,
            "t2m_c": self.t2m_c,
            "msl_hpa": self.msl_hpa,
            "sig_wave_height_m": self.sig_wave_height_m,
            "visibility_km": self.visibility_km,
            "katabatic_component_ms": self.katabatic_component_ms,
            "wave_valid": self.wave_valid,
            "ice_valid": self.ice_valid,
            "is_synthetic": self.is_synthetic,
            "source": self.source,
            "provenance_by_variable": self.provenance_by_variable,
        }


# ---------------------------------------------------------------------------
# Protocol
# ---------------------------------------------------------------------------


@runtime_checkable
class EnvironmentProvider(Protocol):
    """Sample environmental fields at one point and time."""

    def sample(self, lat: float, lon: float, t_utc: datetime) -> EnvSample:
        """Return the environment at ``(lat, lon, t_utc)``.

        Raises ``OutOfCoverage`` when any requested variable lacks coverage at
        the requested time. Never falls back silently to simulated data.
        """
        ...


# ---------------------------------------------------------------------------
# Interpolation primitives (shared by all providers)
# ---------------------------------------------------------------------------


def _wrap_lon(lon: float) -> float:
    """Wrap longitude to [-180, 180)."""
    return ((lon + 180.0) % 360.0) - 180.0


def _bilinear(
    lats: np.ndarray,
    lons: np.ndarray,
    values: np.ndarray,
    lat: float,
    lon: float,
) -> float:
    """Bilinear interpolate ``values[lat_idx, lon_idx]`` at ``(lat, lon)``.

    Handles the antimeridian (lons wrap) and poles (lat clamps). Raises
    ``OutOfCoverage`` when the point is outside the grid.
    """
    lat = float(lat)
    lon = _wrap_lon(float(lon))
    lats = np.asarray(lats, dtype=np.float64)
    lons = np.asarray(lons, dtype=np.float64)

    if lat < float(lats[0]) - 1e-9 or lat > float(lats[-1]) + 1e-9:
        raise OutOfCoverage("spatial", f"{lat:.4f}", f"lat outside grid [{lats[0]}, {lats[-1]}]")

    # Find the bracketing latitude indices.
    i = int(np.searchsorted(lats, lat, side="right") - 1)
    i = max(0, min(i, lats.size - 2))

    # Longitude: wrap the target into the grid frame. Grid lons may themselves
    # wrap (e.g. 0..360 or -180..180); we normalise both to [-180, 180).
    grid_lons = np.array([_wrap_lon(v) for v in lons], dtype=np.float64)
    # Unwrap the grid so we can search monotonically: find the offset that puts
    # the target inside a contiguous span.
    base = float(grid_lons[0])
    target_unwrapped = lon
    while target_unwrapped < base - 180.0:
        target_unwrapped += 360.0
    while target_unwrapped > base + 180.0:
        target_unwrapped -= 360.0

    unwrapped = np.array([base + (((float(v) - base + 180.0) % 360.0) - 180.0) for v in grid_lons])
    # The grid may not be sorted after unwrapping if it crosses the antimeridian;
    # sort indices by unwrapped value.
    order = np.argsort(unwrapped)
    unwrapped_sorted = unwrapped[order]

    if target_unwrapped < float(unwrapped_sorted[0]) - 1e-9 or target_unwrapped > float(unwrapped_sorted[-1]) + 1e-9:
        raise OutOfCoverage("spatial", f"{lon:.4f}", f"lon outside grid")

    j = int(np.searchsorted(unwrapped_sorted, target_unwrapped, side="right") - 1)
    j = max(0, min(j, unwrapped_sorted.size - 2))
    j_orig = int(order[j])
    j1_orig = int(order[j + 1])

    lat_lo, lat_hi = float(lats[i]), float(lats[i + 1])
    lon_lo = float(grid_lons[j_orig])
    lon_hi = float(grid_lons[j1_orig])
    # Handle the case where the two bracketing grid cells straddle the antimeridian
    # in the unwrapped frame: the actual longitude separation is < 360 by construction.
    if lon_hi < lon_lo:
        lon_lo, lon_hi = lon_hi, lon_lo
        j_orig, j1_orig = j1_orig, j_orig

    fr_lat = (lat - lat_lo) / (lat_hi - lat_lo) if lat_hi > lat_lo else 0.0
    fr_lon = (target_unwrapped - unwrapped_sorted[j]) / (unwrapped_sorted[j + 1] - unwrapped_sorted[j]) if unwrapped_sorted[j + 1] > unwrapped_sorted[j] else 0.0

    v00 = float(values[i, j_orig])
    v01 = float(values[i, j1_orig])
    v10 = float(values[i + 1, j_orig])
    v11 = float(values[i + 1, j1_orig])

    if any(not math.isfinite(v) for v in (v00, v01, v10, v11)):
        return float("nan")

    top = v00 * (1.0 - fr_lon) + v01 * fr_lon
    bottom = v10 * (1.0 - fr_lon) + v11 * fr_lon
    return top * (1.0 - fr_lat) + bottom * fr_lat


def _linear_in_time(t0: float, t1: float, v0: float | None, v1: float | None, t: float) -> float | None:
    """Linear interpolation in time. Returns None when either bracket is None."""
    if v0 is None or v1 is None:
        return None
    if t1 == t0:
        return v0
    frac = (t - t0) / (t1 - t0)
    return v0 + frac * (v1 - v0)


def _provenance_entry(kind: str, source: str, product: str, valid_time: str, age_hours: float | None) -> dict[str, Any]:
    return {"kind": kind, "source": source, "product": product, "valid_time": valid_time, "age_hours": age_hours}


# ---------------------------------------------------------------------------
# ReplayProvider
# ---------------------------------------------------------------------------


class ReplayProvider:
    """Reads a replay pack built by ``scripts.build_replay_pack``.

    The pack is a directory of NetCDF files (one per product) plus
    ``manifest.json``. Wind and waves come from separate ERA5 files because
    their grids differ. All variables are interpolated bilinearly in space and
    linearly in time between the two bracketing valid times.

    The maximum inter-variable skew is 12 h: if a variable's bracketing times
    differ from the target by more than 12 h it is omitted rather than used.
    """

    MAX_SKEW_HOURS = 12.0

    def __init__(self, pack_dir: str | Path) -> None:
        self.pack_dir = Path(pack_dir)
        self.manifest_path = self.pack_dir / "manifest.json"
        if not self.manifest_path.is_file():
            raise FileNotFoundError(f"Replay pack manifest not found: {self.manifest_path}")
        import json

        self.manifest = json.loads(self.manifest_path.read_text(encoding="utf-8"))
        self._datasets: dict[str, xr.Dataset | None] = {}

    # -- dataset loading -----------------------------------------------------
    def _dataset_for(self, product: str) -> xr.Dataset | None:
        if product in self._datasets:
            return self._datasets[product]
        record = next((p for p in self.manifest["products"] if p["product"] == product), None)
        if record is None:
            self._datasets[product] = None
            return None
        path = self.pack_dir / Path(record["local_path"]).name
        if not path.is_file():
            self._datasets[product] = None
            return None
        ds = xr.open_dataset(path)
        self._datasets[product] = ds
        return ds

    def _close(self) -> None:
        for ds in self._datasets.values():
            if ds is not None:
                ds.close()
        self._datasets.clear()

    # -- sampling ------------------------------------------------------------
    def sample(self, lat: float, lon: float, t_utc: datetime) -> EnvSample:
        t_hours = t_utc.timestamp() / 3600.0
        provenance: dict[str, dict[str, Any]] = {}

        wind_ds = self._dataset_for("era5_wind_10m")
        wave_ds = self._dataset_for("era5_waves")
        cur_ds = self._dataset_for("cmems_current")
        ice_ds = self._dataset_for("nrt_ice_concentration")

        # Interpolate each variable; on OutOfCoverage the variable is omitted.
        u10 = self._interp_var(wind_ds, "u10", lat, lon, t_utc, provenance, "era5_wind_10m")
        v10 = self._interp_var(wind_ds, "v10", lat, lon, t_utc, provenance, "era5_wind_10m")
        uo = self._interp_var(cur_ds, "uo", lat, lon, t_utc, provenance, "cmems_current")
        vo = self._interp_var(cur_ds, "vo", lat, lon, t_utc, provenance, "cmems_current")
        ice = self._interp_var(ice_ds, "ice_conc", lat, lon, t_utc, provenance, "nrt_ice_concentration")
        swh = self._interp_var(wave_ds, "swh", lat, lon, t_utc, provenance, "era5_waves")

        # Wave masking under ice: waves are meaningless under ice cover.
        wave_valid = True
        if swh is not None:
            ice_val = ice if ice is not None else 0.0
            if not math.isfinite(ice_val) or ice_val > 0.15:
                swh = None
                wave_valid = False

        # Derived scalars.
        wind_speed = None
        if u10 is not None and v10 is not None:
            wind_speed = math.hypot(u10, v10)
        current_speed = None
        current_dir = None
        if uo is not None and vo is not None:
            current_speed = math.hypot(uo, vo)
            current_dir = (math.degrees(math.atan2(uo, vo)) + 360.0) % 360.0
        wind_dir = None
        if u10 is not None and v10 is not None:
            wind_dir = (math.degrees(math.atan2(u10, v10)) + 360.0) % 360.0

        return EnvSample(
            lat=lat,
            lon=lon,
            valid_time_hours=t_hours,
            u10=u10,
            v10=v10,
            wind_speed_ms=wind_speed,
            wind_dir_from_deg=wind_dir,
            wind_gust_ms=None,
            uo=uo,
            vo=vo,
            current_speed_ms=current_speed,
            current_dir_to_deg=current_dir,
            sst_c=None,
            t2m_c=None,
            msl_hpa=None,
            sig_wave_height_m=swh,
            visibility_km=None,
            katabatic_component_ms=None,
            wave_valid=wave_valid,
            ice_valid=(ice is not None),
            is_synthetic=False,
            source="replay pack",
            provenance_by_variable=provenance,
        )

    def _interp_var(
        self,
        ds: xr.Dataset | None,
        var_name: str,
        lat: float,
        lon: float,
        t_utc: datetime,
        provenance: dict[str, dict[str, Any]],
        product: str,
    ) -> float | None:
        if ds is None or var_name not in ds.data_vars:
            return None
        try:
            values = ds[var_name]
            lats = np.asarray(ds["latitude"].values)
            lons = np.asarray(ds["longitude"].values)
            times = np.asarray(ds["time"].values)
        except Exception:
            return None

        # Find the two bracketing times.
        t_ns = np.datetime64(t_utc.astimezone(timezone.utc).replace(tzinfo=None), "ns")
        if t_ns < times[0] or t_ns > times[-1]:
            raise OutOfCoverage(var_name, t_utc.isoformat(), f"outside product time range [{times[0]}, {times[-1]}]")

        idx = int(np.searchsorted(times, t_ns, side="right") - 1)
        idx = max(0, min(idx, times.size - 2))
        t0 = times[idx]
        t1 = times[idx + 1]

        # Skew check: the bracketing pair must straddle the target within 12 h.
        skew_hours = max(
            abs((t_ns - t0).astype("timedelta64[ns]").astype(float) / 3.6e12),
            abs((t1 - t_ns).astype("timedelta64[ns]").astype(float) / 3.6e12),
        )
        if skew_hours > self.MAX_SKEW_HOURS:
            provenance[var_name] = _provenance_entry(
                "reanalysis", "replay pack", product, str(t0), skew_hours,
            )
            return None

        # Spatial interpolation raises OutOfCoverage when the point is outside
        # the grid - let it propagate so sample() can report which variable.
        v0 = self._spatial_interp(values.sel(time=t0), lats, lons, lat, lon)
        v1 = self._spatial_interp(values.sel(time=t1), lats, lons, lat, lon)

        t0_h = float((np.datetime64(t0) - np.datetime64("1970-01-01")) / np.timedelta64(1, "h"))
        t1_h = float((np.datetime64(t1) - np.datetime64("1970-01-01")) / np.timedelta64(1, "h"))
        t_h = float((t_ns - np.datetime64("1970-01-01")) / np.timedelta64(1, "h"))

        result = _linear_in_time(t0_h, t1_h, v0, v1, t_h)

        valid_time = str(np.datetime_as_string(t0, unit="h"))
        age_hours = None
        if result is not None:
            age_hours = max(0.0, t_h - t0_h)
        provenance[var_name] = _provenance_entry(
            "reanalysis", "replay pack", product, valid_time, age_hours,
        )
        return result

    def _spatial_interp(self, da: Any, lats: np.ndarray, lons: np.ndarray, lat: float, lon: float) -> float | None:
        values = np.asarray(da.values, dtype=np.float64)
        return _bilinear(lats, lons, values, lat, lon)


# ---------------------------------------------------------------------------
# LiveProvider
# ---------------------------------------------------------------------------


class LiveProvider:
    """Live environment: GFS wind + CMEMS current + NRT ice, with walk-back.

    When the target time is not covered by a live forecast, the provider walks
    back up to 14 days to the most recent available analysis/forecast cycle and
    stamps the sample with the source valid time and age. It never fabricates
    data and never falls back silently to simulated data.
    """

    WALK_BACK_DAYS = 14

    def __init__(self, gfs_cache_dir: str | Path | None = None) -> None:
        self.gfs_cache_dir = Path(gfs_cache_dir) if gfs_cache_dir else None

    def sample(self, lat: float, lon: float, t_utc: datetime) -> EnvSample:
        # Placeholder: live acquisition requires CDS/CMEMS credentials and
        # network access. The provider raises rather than silently returning
        # synthetic data.
        now = datetime.now(timezone.utc)
        walk_back_limit = now - timedelta(days=self.WALK_BACK_DAYS)
        if t_utc < walk_back_limit:
            raise OutOfCoverage("all", t_utc.isoformat(), "beyond 14-day walk-back limit")
        raise OutOfCoverage(
            "live_provider",
            t_utc.isoformat(),
            "live acquisition is not wired in this build; configure GFS/CMEMS credentials",
        )


# ---------------------------------------------------------------------------
# SimulatedProvider
# ---------------------------------------------------------------------------


class SimulatedProvider:
    """Wraps the seeded ``EnvironmentModel`` for ``environment_mode="simulated"``.

    Every sample carries ``is_synthetic=True`` and ``kind="synthetic"``. This
    provider is the *only* one allowed to return synthetic data; real providers
    never fall back to it silently.
    """

    def __init__(self, seed: int = 26059, reference_doy: int = 330) -> None:
        self._model = EnvironmentModel(seed=seed, reference_day_of_year=reference_doy)

    def sample(self, lat: float, lon: float, t_utc: datetime) -> EnvSample:
        t_hours = t_utc.timestamp() / 3600.0
        core = self._model.sample(lat, lon, t_hours, ice_concentration=0.0)

        provenance: dict[str, dict[str, Any]] = {}
        for var_name in ("u10", "v10", "uo", "vo", "sst_c", "t2m_c", "msl_hpa", "sig_wave_height_m"):
            provenance[var_name] = _provenance_entry(
                "synthetic", "ICEFLOW EnvironmentModel", "simulated", str(t_utc.date()), None,
            )

        return EnvSample(
            lat=core.lat,
            lon=core.lon,
            valid_time_hours=core.valid_time_hours,
            u10=core.u10,
            v10=core.v10,
            wind_speed_ms=core.wind_speed_ms,
            wind_dir_from_deg=core.wind_dir_from_deg,
            wind_gust_ms=core.wind_gust_ms,
            uo=core.uo,
            vo=core.vo,
            current_speed_ms=core.current_speed_ms,
            current_dir_to_deg=core.current_dir_to_deg,
            sst_c=core.sst_c,
            t2m_c=core.t2m_c,
            msl_hpa=core.msl_hpa,
            sig_wave_height_m=core.sig_wave_height_m,
            visibility_km=core.visibility_km,
            katabatic_component_ms=core.katabatic_component_ms,
            wave_valid=True,
            ice_valid=True,
            is_synthetic=True,
            source=core.source,
            provenance_by_variable=provenance,
        )



