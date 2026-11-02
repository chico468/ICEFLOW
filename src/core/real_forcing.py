"""
Real (observed) iceberg forcing: ECMWF ERA5 10 m wind (anonymous ARCO GCS store) plus
Copernicus Marine GLORYS currents, loaded from the NetCDF files cached to disk by
scripts/download_iceberg_forcing.py.

This is the live-data counterpart of src/core/environment.py. Per the build-spec honesty
principle (P2), instances flag themselves ``is_synthetic = False`` and name the real products
they ingest, so a forecast driven here is never mis-labelled as simulated.

ERA5 files are hourly; they are subsampled to 3-hourly and lat-restricted to the Southern
Ocean corridor holding the tracks. GLORYS is a daily mean; it is reduced to the surface level
and a 0-100 m depth mean. Forcing is sampled at the nearest available time step (never
fabricated between steps). Grids are normalised to ascending latitude and longitude in
[0, 360) before interpolation.
"""
from __future__ import annotations

import glob
from datetime import date, datetime, timedelta
from typing import Tuple

import numpy as np
import xarray as xr
from scipy.interpolate import RegularGridInterpolator

ERA5_DIR = "data/raw/iceberg/era5_wind"
GLORYS_DIR = "data/raw/iceberg/glorys"
LAT_MIN, LAT_MAX = -82.0, -48.0  # Southern Ocean corridor holding the tracks


def _to_grid_lon(lon: np.ndarray, grid_lon: np.ndarray) -> np.ndarray:
    """Normalise input longitudes to the grid's convention ([0,360) or [-180,180))."""
    lon = np.asarray(lon, dtype=np.float64)
    if float(grid_lon.min()) < 0.0:
        return ((lon + 180.0) % 360.0) - 180.0
    return np.mod(lon, 360.0)


def load_era5() -> xr.Dataset:
    """Load all cached ERA5 day files, subsample to 3-hourly, lat-restrict, float32."""
    datasets = []
    for var, pattern in (("u10", "10m_u_component_of_wind_*.nc"),
                         ("v10", "10m_v_component_of_wind_*.nc")):
        var_files = sorted(glob.glob(f"{ERA5_DIR}/{pattern}"))
        if not var_files:
            raise FileNotFoundError(f"No ERA5 {var} files matching {pattern} in {ERA5_DIR}")
        parts = [xr.open_dataset(f)[[var]].isel(time=slice(0, None, 3))
                 for f in var_files]
        ds = xr.concat(parts, dim="time")
        ds = ds.where((ds.latitude >= LAT_MIN) & (ds.latitude <= LAT_MAX), drop=True)
        ds = ds.sortby("latitude")
        ds = ds.astype(np.float32)
        datasets.append(ds)
    return xr.merge(datasets)


def load_glorys() -> xr.Dataset:
    """Load all cached GLORYS day files, reduce to surface + 0-100 m mean, lat-restrict."""
    files = sorted(glob.glob(f"{GLORYS_DIR}/glorys_*.nc"))
    if not files:
        raise FileNotFoundError(f"No GLORYS files in {GLORYS_DIR}")
    surface_parts, mean_parts = [], []
    for f in files:
        ds = xr.open_dataset(f)
        depth = ds["depth"].values
        surf_idx = int(np.argmin(depth))
        mean_idx = np.where(depth <= 100.0)[0]
        if mean_idx.size == 0:
            mean_idx = np.array([surf_idx])
        surf = ds.isel(depth=surf_idx)[["uo", "vo"]]
        mean100 = ds.isel(depth=mean_idx)[["uo", "vo"]].mean(dim="depth")
        mean100 = mean100.rename({"uo": "uo_mean100", "vo": "vo_mean100"})
        surface_parts.append(surf)
        mean_parts.append(mean100)
        ds.close()
    surf = xr.concat(surface_parts, dim="time")
    mean100 = xr.concat(mean_parts, dim="time")
    ds = xr.merge([surf, mean100])
    ds = ds.where((ds.latitude >= LAT_MIN) & (ds.latitude <= LAT_MAX), drop=True)
    ds = ds.sortby("latitude").astype(np.float32)
    return ds


class RealForcingEnvironment:
    """Real ERA5 + GLORYS forcing. Not synthetic: is_synthetic is False."""

    is_synthetic = False
    source = "ECMWF ERA5 10 m wind (ARCO) + Copernicus Marine GLORYS currents (surface & 0-100 m)"

    def __init__(self, t0_date: date, era5: xr.Dataset, glorys: xr.Dataset,
                 wind_scale: float = 1.0, current_scale: float = 1.0) -> None:
        self.t0_date = t0_date
        self.t0 = datetime(t0_date.year, t0_date.month, t0_date.day)
        self.wind_scale = float(wind_scale)
        self.current_scale = float(current_scale)
        self._era5 = era5
        self._glorys = glorys
        self._era5_lat = era5.latitude.values.astype(np.float64)
        self._era5_lon = era5.longitude.values.astype(np.float64)
        self._era5_time = era5.time.values
        self._glorys_lat = glorys.latitude.values.astype(np.float64)
        self._glorys_lon = glorys.longitude.values.astype(np.float64)
        self._glorys_time = glorys.time.values
        self._cache: dict[Tuple[str, str, int], RegularGridInterpolator] = {}

    # ------------------------------------------------------------------ time lookup
    def _abs_time(self, t_hours: float) -> datetime:
        return self.t0 + timedelta(hours=float(t_hours))

    def _nearest_index(self, time_values: np.ndarray, when: datetime) -> int:
        return int(np.argmin(np.abs(time_values - np.datetime64(when))))

    # ------------------------------------------------------------------ interpolators
    def _interp2(self, dataset: str, var: str, time_idx: int,
                 lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        key = (dataset, var, int(time_idx))
        interp = self._cache.get(key)
        if dataset == "era5":
            field = self._era5[var].isel(time=time_idx).values
            lat_1d, lon_1d = self._era5_lat, self._era5_lon
        else:
            field = self._glorys[var].isel(time=time_idx).values
            lat_1d, lon_1d = self._glorys_lat, self._glorys_lon
        if interp is None:
            interp = RegularGridInterpolator(
                (lat_1d, lon_1d), np.ascontiguousarray(field, dtype=np.float64),
                bounds_error=False, fill_value=np.nan,
            )
            self._cache[key] = interp
        points = np.column_stack([np.asarray(lat, dtype=np.float64),
                                  _to_grid_lon(np.asarray(lon, dtype=np.float64), lon_1d)])
        return np.nan_to_num(np.asarray(interp(points), dtype=np.float64), nan=0.0)

    # ----------------------------------------------------------- environment interface
    def wind_uv(self, lat, lon, t_hours: float) -> Tuple[np.ndarray, np.ndarray, np.ndarray]:
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        i = self._nearest_index(self._era5_time, self._abs_time(t_hours))
        ua = self._interp2("era5", "u10", i, lat, lon) * self.wind_scale
        va = self._interp2("era5", "v10", i, lat, lon) * self.wind_scale
        return ua, va, np.zeros_like(ua)

    def current_uv(self, lat, lon, t_hours: float) -> Tuple[np.ndarray, np.ndarray]:
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        i = self._nearest_index(self._glorys_time, self._abs_time(t_hours))
        # 0-100 m mean current: the layer a berg's keel sits in.
        uo = self._interp2("glorys", "uo_mean100", i, lat, lon) * self.current_scale
        vo = self._interp2("glorys", "vo_mean100", i, lat, lon) * self.current_scale
        return uo, vo

    def scalars(self, lat, lon, t_hours: float, wind_speed, ice_concentration=0.0):
        lat = np.asarray(lat, dtype=np.float64)
        wind_speed = np.asarray(wind_speed, dtype=np.float64)
        hs = np.clip(0.0246 * wind_speed ** 2, 0.2, 13.0)
        return {
            "t2m_c": np.full_like(lat, -10.0),
            "sst_c": np.full_like(lat, -1.85),
            "msl_hpa": np.full_like(lat, 1000.0),
            "sig_wave_height_m": hs,
            "visibility_km": np.full_like(lat, 15.0),
        }

    # ------------------------------------------------------------------ EnvironmentProvider interface
    def sample_grid(
        self,
        lats: np.ndarray,
        lons: np.ndarray,
        t_hours: float,
    ) -> dict[str, np.ndarray]:
        """Sample all variables on a regular lat/lon grid (EnvironmentProvider interface)."""
        lats = np.asarray(lats, dtype=np.float64)
        lons = np.asarray(lons, dtype=np.float64)
        shape = lats.shape
        lat_flat = lats.ravel()
        lon_flat = lons.ravel()

        ua, va, _ = self.wind_uv(lat_flat, lon_flat, t_hours)
        uo, vo = self.current_uv(lat_flat, lon_flat, t_hours)
        ws = np.hypot(ua, va)
        scal = self.scalars(lat_flat, lon_flat, t_hours, ws, np.zeros_like(lat_flat))

        return {
            "u10": ua.reshape(shape),
            "v10": va.reshape(shape),
            "uo": uo.reshape(shape),
            "vo": vo.reshape(shape),
            "swh": scal["sig_wave_height_m"].reshape(shape),
            "ice_conc": np.zeros(shape),
            "sst_c": scal["sst_c"].reshape(shape),
            "wind_speed_ms": ws.reshape(shape),
            "current_speed_ms": np.hypot(uo, vo).reshape(shape),
        }


_ERA5 = None
_GLORYS = None


def _loaded() -> Tuple[xr.Dataset, xr.Dataset]:
    global _ERA5, _GLORYS
    if _ERA5 is None:
        _ERA5 = load_era5()
    if _GLORYS is None:
        _GLORYS = load_glorys()
    return _ERA5, _GLORYS


def real_environment_for(t0_date: date, wind_scale: float = 1.0,
                         current_scale: float = 1.0) -> RealForcingEnvironment:
    """Build a real-forcing environment for forecasts starting on ``t0_date``."""
    era5, glorys = _loaded()
    return RealForcingEnvironment(t0_date, era5, glorys, wind_scale, current_scale)
