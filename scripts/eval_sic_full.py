#!/usr/bin/env python
"""Full evaluation implementation."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from src.data.nsidc_sea_ice import default_cache_dir
from src.eval import baselines, metrics, splits
from src.eval.areas import compute_cell_areas
from src.eval.regions import SECTORS_SIMPLE, AUSTRAL_DEPARTURE_SEASON
from src.eval import io


def get_season(d: date):
    if d.month in (11, 12, 1, 2, 3):
        return 'austral_departure'
    return 'other'


def get_sector(lon_deg):
    lon = ((lon_deg + 180) % 360) - 180  # normalize
    # Weddell -60W to 20E
    if -60 <= lon <= 20:
        return 'Weddell Sea'
    if 20 < lon <= 90:
        return 'Indian Ocean'
    if 90 < lon <= 160:
        return 'Western Pacific'
    if 160 < lon or lon <= -130:  # crosses
        return 'Ross Sea'
    if -130 < lon < -60:
        return 'Bellingshausen-Amundsen'
    return 'other'
