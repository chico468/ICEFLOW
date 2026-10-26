"""IO helpers for real SIC evaluation."""
from __future__ import annotations

import warnings
from datetime import date, timedelta
from pathlib import Path
from typing import Optional

import numpy as np

from src.data.nsidc_sea_ice import (
    NSIDCDataError,
    NSIDCSeaIceReader,
    read_nsidc_file,
    default_cache_dir,
)


def get_cache_dir() -> Path:
    return default_cache_dir()


def load_sic_range(
    start: date,
    end: date,
    cache_dir: Optional[Path] = None,
):
    """Load SIC for a date range from the local cache only.

    Dates whose cached file is missing (or unreadable) are recorded as gaps;
    nothing is silently fabricated. The first successfully read observation
    supplies the grid coordinates (x_m, y_m).

    Returns ``(sic_by_date, gaps, grid)`` where ``grid`` is a dict with
    ``x_m``/``y_m`` 1-D arrays or ``None`` if no observation could be read.
    """
    if cache_dir is None:
        cache_dir = get_cache_dir()
    reader = NSIDCSeaIceReader(cache_dir=cache_dir)

    sic_by_date: dict[date, np.ndarray] = {}
    gaps: list[date] = []
    grid: Optional[dict] = None

    for d in _daterange(start, end):
        path = cache_dir / reader._filename(d)
        if not path.is_file():
            gaps.append(d)
            continue
        try:
            obs = read_nsidc_file(
                path,
                source_url=f"{reader._url(d)}",
                retrieved_from_cache=True,
            )
        except NSIDCDataError:
            gaps.append(d)
            continue
        if obs.observation_date != d:
            gaps.append(d)
            continue
        sic_by_date[d] = np.asarray(obs.concentration, dtype=np.float64)
        if grid is None:
            grid = {"x_m": np.asarray(obs.x_m, dtype=np.float64),
                    "y_m": np.asarray(obs.y_m, dtype=np.float64)}
    return sic_by_date, gaps, grid


def load_real(dates: list[date], cache_dir: Optional[Path] = None):
    """Load a specific set of dates from cache, returning ``(sic_by_date, gaps, grid)``."""
    if cache_dir is None:
        cache_dir = get_cache_dir()
    reader = NSIDCSeaIceReader(cache_dir=cache_dir)
    sic_by_date: dict[date, np.ndarray] = {}
    gaps: list[date] = []
    grid: Optional[dict] = None
    for d in dates:
        path = cache_dir / reader._filename(d)
        if not path.is_file():
            gaps.append(d)
            continue
        try:
            obs = read_nsidc_file(path, source_url=f"{reader._url(d)}", retrieved_from_cache=True)
        except NSIDCDataError:
            gaps.append(d)
            continue
        if obs.observation_date != d:
            gaps.append(d)
            continue
        sic_by_date[d] = np.asarray(obs.concentration, dtype=np.float64)
        if grid is None:
            grid = {"x_m": np.asarray(obs.x_m, dtype=np.float64),
                    "y_m": np.asarray(obs.y_m, dtype=np.float64)}
    return sic_by_date, gaps, grid


def _daterange(start: date, end: date):
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)


def latlon_grid(x_m: np.ndarray, y_m: np.ndarray, crs_epsg: str = "EPSG:3412"):
    """Return (lat, lon) 2-D arrays for the grid cell centres."""
    from pyproj import CRS, Transformer

    code = int(str(crs_epsg).split(":")[-1])
    crs = CRS.from_epsg(code)
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(x_m, y_m)
    lon, lat = transformer.transform(xx, yy)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        lon = np.asarray(lon, dtype=np.float64)
        lat = np.asarray(lat, dtype=np.float64)
    return lat, lon
