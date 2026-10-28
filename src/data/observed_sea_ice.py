"""Observed Antarctic sea-ice concentration field sampled from locally cached NSIDC data.

This module adapts the raw NSIDC NetCDF grid into the lat/lon sampling interface the route
optimizer needs. It never downloads data; it reads only files that have already been cached.
"""
from __future__ import annotations

import math
from datetime import date, datetime, timedelta, timezone
from typing import Optional, Tuple

import numpy as np
from pyproj import Transformer
from scipy.interpolate import RegularGridInterpolator

from src.data.nsidc_sea_ice import (
    NSIDCDataError,
    NSIDCUnavailableError,
    SeaIceObservation,
    default_cache_dir,
    read_nsidc_file,
)


_MAX_LOOKBACK_DAYS = 14


def _find_cached_file(target: date, cache_dir=None) -> Optional[Tuple[np.ndarray, np.ndarray, np.ndarray, str]]:
    """Return (concentration, x_m, y_m, source_url) for a target date, or None."""
    from src.data.nsidc_sea_ice import _FILENAME_RE

    cache = cache_dir or default_cache_dir()
    candidates = sorted(cache.glob("sic_pss25_*_*.nc"))
    for path in candidates:
        try:
            match = _FILENAME_RE.match(path.name)
            if match is None:
                continue
            file_date = datetime.strptime(match.group(1), "%Y%m%d").date()
        except (ValueError, IndexError):
            continue
        if file_date == target:
            obs = read_nsidc_file(path, retrieved_from_cache=True)
            return obs.concentration, obs.x_m, obs.y_m, obs.source_url
    return None


def get_observed_observation(target_date: date, max_lookback_days: int = _MAX_LOOKBACK_DAYS) -> SeaIceObservation:
    """Read the NSIDC observation for *target_date*, or the nearest valid cached date.

    For ``real_ice`` mode the caller passes ``None`` and this function walks back up to
    ``max_lookback_days`` to find the most recent cached observation. For ``replay`` mode
    the caller passes an explicit ``replay_date``.
    """
    cache = default_cache_dir()
    if target_date is not None:
        result = _find_cached_file(target_date, cache)
        if result is None:
            raise NSIDCUnavailableError(
                f"No NSIDC observation cached for {target_date.isoformat()}."
            )
        conc, x_m, y_m, source_url = result
        return SeaIceObservation(
            observation_date=target_date,
            concentration=conc,
            x_m=x_m,
            y_m=y_m,
            source_url=source_url,
            retrieved_from_cache=True,
        )

    today = datetime.now(timezone.utc).date()
    for days_back in range(0, max_lookback_days + 1):
        day = today - timedelta(days=days_back)
        result = _find_cached_file(day, cache)
        if result is not None:
            conc, x_m, y_m, source_url = result
            return SeaIceObservation(
                observation_date=day,
                concentration=conc,
                x_m=x_m,
                y_m=y_m,
                source_url=source_url,
                retrieved_from_cache=True,
            )
    raise NSIDCUnavailableError(
        f"No NSIDC observation cached within the last {max_lookback_days} days."
    )


class ObservedIceField:
    """Sampled concentration from a local NSIDC observation on the route lattice.

    The NSIDC G10016 / G02202 grid is regular in the polar-stereographic projection
    (EPSG:3412), so interpolation is performed in that space and only the lat/lon
    query points are transformed.
    """

    def __init__(self, observation: SeaIceObservation) -> None:
        self.observation = observation
        self._transformer = Transformer.from_crs("EPSG:4326", "EPSG:3412", always_xy=True)
        conc = np.asarray(observation.concentration, dtype=np.float64)
        self._fill_nan = not np.isfinite(conc).any()
        self._conc = np.where(np.isfinite(conc), conc, 0.0)
        self._x = np.asarray(observation.x_m, dtype=np.float64)
        self._y = np.asarray(observation.y_m, dtype=np.float64)
        self._interp = RegularGridInterpolator(
            (self._y, self._x),
            self._conc,
            bounds_error=False,
            fill_value=0.0,
            method="nearest",
        )

    @property
    def valid_date(self) -> date:
        return self.observation.observation_date

    @property
    def source(self) -> str:
        return self.observation.source

    def sample(self, lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
        """Return concentration (fraction 0-1) at lat/lon arrays, same shape as input."""
        lon_scalar = np.isscalar(lon)
        lat_arr = np.atleast_1d(np.asarray(lat, dtype=np.float64))
        lon_arr = np.atleast_1d(np.asarray(lon, dtype=np.float64))
        x, y = self._transformer.transform(lon_arr, lat_arr)
        points = np.column_stack([y.ravel(), x.ravel()])
        result = self._interp(points).reshape(lat_arr.shape)
        result = np.clip(result, 0.0, 1.0)
        if lon_scalar:
            return float(result)
        return result

    def concentration_grid(self, lat_g: np.ndarray, lon_g: np.ndarray) -> np.ndarray:
        """Vectorised concentration over a meshgrid of lat/lon arrays."""
        return self.sample(lat_g, lon_g)
