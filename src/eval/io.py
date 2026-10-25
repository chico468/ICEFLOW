"""IO helpers for real SIC evaluation."""
from __future__ import annotations

import json
from datetime import date, datetime
from pathlib import Path

import numpy as np

from src.data.nsidc_sea_ice import NSIDCSeaIceReader, read_nsidc_file, default_cache_dir


def get_cache_dir():
    return default_cache_dir()


def load_sic_range(start: date, end: date, cache_dir: Path | None = None):
    """Load SIC for date range into arrays."""
    if cache_dir is None:
        cache_dir = get_cache_dir()
    reader = NSIDCSeaIceReader(cache_dir=cache_dir)
    sic_by_date = {}
    gaps = []
    for d in _daterange(start, end):
        try:
            obs = reader.fetch_latest(today=d + __import__('datetime').timedelta(days=1))
            # If observation is not for this date, try to load from cache
            if obs.observation_date != d:
                # try direct cache load
                target = cache_dir / reader._filename(d)
                if target.exists():
                    obs = read_nsidc_file(target)
            if obs.observation_date == d:
                sic_by_date[d] = obs.concentration
            else:
                gaps.append(d)
        except Exception:
            gaps.append(d)
    return sic_by_date, gaps


def _daterange(start: date, end: date):
    from datetime import timedelta
    cur = start
    while cur <= end:
        yield cur
        cur += timedelta(days=1)
