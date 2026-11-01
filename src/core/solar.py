"""Solar position (azimuth / elevation) via astronomical approximation.

Implements the standard Julian-century solar geometry (Meeus "Astronomical
Algorithms" / NOAA Solar Calculator). Accurate to roughly 0.1 deg for dates
1900-2100, which is ample for a voyage-timeline display.

All angles in degrees. Azimuth is measured clockwise from north
(0 = north, 90 = east, 180 = south, 270 = west). Elevation is positive above
the horizon; negative values mean the Sun is below the horizon (night/twilight).

Published equinox geometry used as the test anchor: on the equinox the Sun
rises due east (azimuth 90 deg), transits due south in the northern hemisphere
/ due north in the southern hemisphere (azimuth 180 / 0 deg), and reaches an
elevation of 90 deg - |latitude| at transit.
"""
from __future__ import annotations

import math
from datetime import datetime, timezone


def _julian_date(dt: datetime) -> float:
    utc = dt.astimezone(timezone.utc)
    year = utc.year
    month = utc.month
    day = utc.day
    hour = (
        utc.hour
        + utc.minute / 60.0
        + utc.second / 3600.0
        + utc.microsecond / 3.6e9
    )
    if month <= 2:
        year -= 1
        month += 12
    a = math.floor(year / 100.0)
    b = 2.0 - a + math.floor(a / 4.0)
    jd = (
        math.floor(365.25 * (year + 4716))
        + math.floor(30.6001 * (month + 1))
        + day
        + b
        - 1524.5
        + hour / 24.0
    )
    return jd


def sun_position(lat_deg: float, lon_deg: float, t_utc: datetime) -> tuple[float, float]:
    """Return (azimuth_deg, elevation_deg) of the Sun at ``(lat, lon, t_utc)``.

    Azimuth is clockwise from north; elevation positive above the horizon.
    Returns ``(float("nan"), float("nan"))`` when the Sun is at the zenith
    (azimuth undefined there).
    """
    jd = _julian_date(t_utc)
    t = (jd - 2451545.0) / 36525.0
    t2 = t * t
    t3 = t2 * t

    # Mean longitude and mean anomaly of the Sun (deg).
    l0 = 280.46646 + 36000.76983 * t + 0.0003032 * t2
    g = 357.52911 + 35999.05029 * t - 0.0001537 * t2
    # Eccentricity of Earth's orbit.
    ecc = 0.016708634 - 0.000042037 * t - 0.0000001267 * t2
    # Equation of the centre (deg).
    c = (
        (1.914602 - 0.004817 * t - 0.000014 * t2) * math.sin(math.radians(g))
        + (0.019993 - 0.000101 * t) * math.sin(math.radians(2.0 * g))
        + 0.000290 * math.sin(math.radians(3.0 * g))
    )
    lam = l0 + c  # true longitude (deg)
    # Apparent longitude, correcting for aberration (deg).
    lam_app = lam - 0.00569 - 0.00478 * math.sin(math.radians(125.04 - 1934.136 * t))
    # Mean and true obliquity of the ecliptic (deg).
    eps0 = 23.439291 - 0.0130042 * t - 0.00000016 * t2 + 0.000000504 * t3
    eps = eps0 + 0.00256 * math.cos(math.radians(125.04 - 1934.136 * t))
    # Right ascension (deg).
    alpha = math.degrees(
        math.atan2(
            math.cos(math.radians(eps)) * math.sin(math.radians(lam_app)),
            math.cos(math.radians(lam_app)),
        )
    ) % 360.0
    # Declination (deg).
    dec = math.degrees(
        math.asin(math.sin(math.radians(eps)) * math.sin(math.radians(lam_app)))
    )
    # Greenwich mean sidereal time (deg).
    d = jd - 2451545.0
    gmst = (
        280.46061837
        + 360.98564736629 * d
        + 0.000387933 * t2
        - t3 / 38710000.0
    ) % 360.0
    lst = (gmst + lon_deg) % 360.0  # local apparent sidereal time (deg)
    # Hour angle (deg): 0 at local apparent transit, positive in afternoon.
    h = (lst - alpha + 180.0) % 360.0 - 180.0

    phi = math.radians(lat_deg)
    delta = math.radians(dec)
    hour = math.radians(h)

    sin_el = math.sin(phi) * math.sin(delta) + math.cos(phi) * math.cos(delta) * math.cos(hour)
    sin_el = max(-1.0, min(1.0, sin_el))
    el = math.degrees(math.asin(sin_el))
    el_rad = math.radians(el)

    # Azimuth (from south, positive west) then convert to clockwise-from-north.
    # Avoids dividing by cos(el) so it stays finite at transit/zenith.
    tan_delta = math.tan(delta)
    az_from_south = math.atan2(math.sin(hour), math.cos(hour) * math.sin(phi) - tan_delta * math.cos(phi))
    az = (math.degrees(az_from_south) + 180.0) % 360.0

    # Azimuth is undefined at the zenith; report NaN there.
    if abs(sin_el) > 0.99999:
        az = float("nan")

    return az, el
