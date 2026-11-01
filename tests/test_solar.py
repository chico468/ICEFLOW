"""Tests for the solar position algorithm (src/core/solar.py).

Anchors are published equinox geometry: on the equinox the Sun rises due east
(azimuth 90 deg), transits due south in the northern hemisphere / due north in
the southern hemisphere (azimuth 180 / 0 deg), and reaches an elevation of
90 deg - |latitude| at transit.
"""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone

from src.core.solar import sun_position

EQUINOX = datetime(2000, 3, 20, 7, 35, tzinfo=timezone.utc)  # vernal equinox ~ dec ~ 0


def _scan_day(lat_deg: float, lon_deg: float, date_utc: datetime, step_min: float = 5.0):
    best = None
    t = date_utc.replace(hour=0, minute=0, second=0, microsecond=0)
    end = t + timedelta(days=1)
    while t < end:
        az, el = sun_position(lat_deg, lon_deg, t)
        if best is None or el > best[2]:
            best = (t, az, el)
        t += timedelta(minutes=step_min)
    return best


def _circular_distance(a: float, b: float) -> float:
    return abs(((a - b + 180.0) % 360.0) - 180.0)


def test_solar_ranges():
    az, el = sun_position(45.0, 0.0, EQUINOX)
    assert -90.0 <= el <= 90.0
    if not math.isnan(az):
        assert 0.0 <= az < 360.0


def test_solar_equinox_culmination_northern():
    # Northern hemisphere: transit due south (az 180), elevation 90 - lat.
    t, az, el = _scan_day(45.0, 0.0, EQUINOX)
    assert abs(el - 45.0) < 1.5, el
    assert _circular_distance(az, 180.0) < 10.0, az  # az near 180 (south)


def test_solar_equinox_culmination_southern():
    # Southern hemisphere: transit due north (az 0), elevation 90 - |lat|.
    t, az, el = _scan_day(-45.0, 0.0, EQUINOX)
    assert abs(el - 45.0) < 1.5, el
    assert min(_circular_distance(az, 0.0), _circular_distance(az, 360.0)) < 10.0, az  # az near 0


def test_solar_equinox_rise_set_azimuth():
    # Equinox: Sun rises due east (az 90) and sets due west (az 270).
    t = EQUINOX.replace(hour=0, minute=0, second=0, microsecond=0)
    end = t + timedelta(days=1)
    rises = []
    while t < end:
        az, el = sun_position(30.0, 0.0, t)
        if el > -0.5 and not rises:
            rises.append((t, az))
        if el < -0.5 and rises:
            rises.append((t, az))
            break
        t += timedelta(minutes=5)
    assert len(rises) == 2, rises
    # Crossing the horizon: azimuth should be near 90 (rise) / 270 (set).
    assert _circular_distance(rises[0][1], 90.0) < 15.0, rises[0][1]
    assert _circular_distance(rises[1][1], 270.0) < 15.0, rises[1][1]


def test_solar_high_lat_winter_night():
    # 2000-06-21 southern winter at 70S: Sun below horizon all day (el < 0).
    solstice = datetime(2000, 6, 21, 12, 0, tzinfo=timezone.utc)
    t = solstice.replace(hour=0, minute=0, second=0, microsecond=0)
    end = t + timedelta(days=1)
    any_up = False
    while t < end:
        _, el = sun_position(-70.0, 0.0, t)
        if el > 0:
            any_up = True
        t += timedelta(minutes=30)
    assert not any_up


def test_solar_zenith_azimuth_nan():
    # At the equator on equinox the Sun transits at the zenith: azimuth NaN.
    t = EQUINOX.replace(hour=0, minute=0, second=0, microsecond=0)
    end = t + timedelta(days=1)
    while t < end:
        az, el = sun_position(0.0, 0.0, t)
        if el > 89.9:
            assert math.isnan(az)
        t += timedelta(minutes=5)
