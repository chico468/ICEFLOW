"""
Geodesy primitives for polar navigation.

Spherical-earth great-circle maths for navigation (the standard practice for route
planning), and an exact WGS84 ellipsoidal polar stereographic projection pair for
EPSG:3031 rendering. The forward and inverse projections are true inverses to
sub-millimetre precision, which the test suite asserts.
"""
from __future__ import annotations

import math
from typing import List, Sequence, Tuple

from src.core.constants import (
    EARTH_RADIUS_KM,
    EPSG3031_CENTRAL_MERIDIAN_DEG,
    EPSG3031_STD_PARALLEL_DEG,
    KM_PER_NM,
    WGS84_A,
    WGS84_E,
)

LatLon = Tuple[float, float]


# --------------------------------------------------------------------------------------
# Great-circle navigation
# --------------------------------------------------------------------------------------
def haversine_nm(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in nautical miles."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dphi = math.radians(lat2 - lat1)
    dlam = math.radians(lon2 - lon1)
    a = math.sin(dphi / 2.0) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2.0) ** 2
    a = min(1.0, max(0.0, a))
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return (EARTH_RADIUS_KM * c) / KM_PER_NM


def haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    return haversine_nm(lat1, lon1, lat2, lon2) * KM_PER_NM


def initial_bearing_deg(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """True initial bearing (course) from point 1 to point 2, degrees clockwise from north."""
    phi1, phi2 = math.radians(lat1), math.radians(lat2)
    dlam = math.radians(lon2 - lon1)
    y = math.sin(dlam) * math.cos(phi2)
    x = math.cos(phi1) * math.sin(phi2) - math.sin(phi1) * math.cos(phi2) * math.cos(dlam)
    return (math.degrees(math.atan2(y, x)) + 360.0) % 360.0


def destination_point(lat: float, lon: float, bearing_deg: float, distance_nm: float) -> LatLon:
    """Project a point along a great circle from a start position."""
    ang = (distance_nm * KM_PER_NM) / EARTH_RADIUS_KM
    brg = math.radians(bearing_deg)
    phi1, lam1 = math.radians(lat), math.radians(lon)
    phi2 = math.asin(
        min(1.0, max(-1.0, math.sin(phi1) * math.cos(ang) + math.cos(phi1) * math.sin(ang) * math.cos(brg)))
    )
    lam2 = lam1 + math.atan2(
        math.sin(brg) * math.sin(ang) * math.cos(phi1),
        math.cos(ang) - math.sin(phi1) * math.sin(phi2),
    )
    return math.degrees(phi2), normalize_lon(math.degrees(lam2))


def normalize_lon(lon: float) -> float:
    """Wrap longitude into [-180, 180)."""
    return ((lon + 180.0) % 360.0) - 180.0


def lon_delta(lon1: float, lon2: float) -> float:
    """Shortest signed longitude difference lon2 - lon1, in [-180, 180)."""
    return normalize_lon(lon2 - lon1)


def great_circle_path(lat1: float, lon1: float, lat2: float, lon2: float, n: int = 64) -> List[LatLon]:
    """
    Spherical interpolation along the great circle, inclusive of both endpoints.
    Used as the honest baseline route against which optimisation is measured.
    """
    n = max(2, int(n))
    phi1, lam1 = math.radians(lat1), math.radians(lon1)
    phi2, lam2 = math.radians(lat2), math.radians(lon2)

    d = 2.0 * math.asin(
        min(
            1.0,
            math.sqrt(
                math.sin((phi2 - phi1) / 2.0) ** 2
                + math.cos(phi1) * math.cos(phi2) * math.sin((lam2 - lam1) / 2.0) ** 2
            ),
        )
    )
    if d < 1e-12:
        return [(lat1, lon1), (lat2, lon2)]

    pts: List[LatLon] = []
    for i in range(n):
        f = i / (n - 1)
        a = math.sin((1.0 - f) * d) / math.sin(d)
        b = math.sin(f * d) / math.sin(d)
        x = a * math.cos(phi1) * math.cos(lam1) + b * math.cos(phi2) * math.cos(lam2)
        y = a * math.cos(phi1) * math.sin(lam1) + b * math.cos(phi2) * math.sin(lam2)
        z = a * math.sin(phi1) + b * math.sin(phi2)
        pts.append((math.degrees(math.atan2(z, math.hypot(x, y))), math.degrees(math.atan2(y, x))))
    return pts


def path_length_nm(points: Sequence[LatLon]) -> float:
    return sum(
        haversine_nm(points[i][0], points[i][1], points[i + 1][0], points[i + 1][1])
        for i in range(len(points) - 1)
    )


def cross_track_distance_nm(p: LatLon, a: LatLon, b: LatLon) -> float:
    """
    Perpendicular distance from point p to the great circle through a and b.
    Positive to the right of the a->b track, negative to the left.
    """
    d13 = haversine_nm(a[0], a[1], p[0], p[1]) * KM_PER_NM / EARTH_RADIUS_KM
    if d13 < 1e-12:
        return 0.0
    theta13 = math.radians(initial_bearing_deg(a[0], a[1], p[0], p[1]))
    theta12 = math.radians(initial_bearing_deg(a[0], a[1], b[0], b[1]))
    xt = math.asin(min(1.0, max(-1.0, math.sin(d13) * math.sin(theta13 - theta12))))
    return (xt * EARTH_RADIUS_KM) / KM_PER_NM


def point_to_segment_nm(p: LatLon, a: LatLon, b: LatLon) -> float:
    """Distance from p to the *segment* ab (not the infinite circle), in nautical miles."""
    seg = haversine_nm(a[0], a[1], b[0], b[1])
    if seg < 1e-9:
        return haversine_nm(p[0], p[1], a[0], a[1])
    # Along-track distance from a toward b.
    d13 = haversine_nm(a[0], a[1], p[0], p[1])
    theta13 = math.radians(initial_bearing_deg(a[0], a[1], p[0], p[1]))
    theta12 = math.radians(initial_bearing_deg(a[0], a[1], b[0], b[1]))
    along = d13 * math.cos(theta13 - theta12)
    if along <= 0.0:
        return haversine_nm(p[0], p[1], a[0], a[1])
    if along >= seg:
        return haversine_nm(p[0], p[1], b[0], b[1])
    return abs(cross_track_distance_nm(p, a, b))


# --------------------------------------------------------------------------------------
# EPSG:3031 - Antarctic Polar Stereographic (WGS84, true scale at 71 S, central meridian 0)
# Axis convention: +x toward 90 E, +y toward 0 E, origin at the South Pole.
# --------------------------------------------------------------------------------------
_PHI_C = math.radians(abs(EPSG3031_STD_PARALLEL_DEG))
_LAM_0 = math.radians(EPSG3031_CENTRAL_MERIDIAN_DEG)
_E = WGS84_E
_E2 = _E * _E


def _t_of(phi: float) -> float:
    """Isometric-latitude helper t(phi) for the polar aspect (phi is a positive latitude)."""
    return math.tan(math.pi / 4.0 - phi / 2.0) / (
        ((1.0 - _E * math.sin(phi)) / (1.0 + _E * math.sin(phi))) ** (_E / 2.0)
    )


_M_C = math.cos(_PHI_C) / math.sqrt(1.0 - _E2 * math.sin(_PHI_C) ** 2)
_T_C = _t_of(_PHI_C)


def to_epsg3031(lat: float, lon: float) -> Tuple[float, float]:
    """WGS84 lat/lon (degrees, southern latitudes negative) to EPSG:3031 metres."""
    phi = math.radians(-lat)  # positive southern latitude
    lam = math.radians(lon) - _LAM_0
    if phi >= math.pi / 2.0 - 1e-12:
        return 0.0, 0.0
    rho = WGS84_A * _M_C * _t_of(phi) / _T_C
    return rho * math.sin(lam), rho * math.cos(lam)


def from_epsg3031(x: float, y: float) -> LatLon:
    """EPSG:3031 metres back to WGS84 lat/lon degrees. Exact inverse of to_epsg3031."""
    rho = math.hypot(x, y)
    if rho < 1e-9:
        return -90.0, 0.0
    t = rho * _T_C / (WGS84_A * _M_C)
    chi = math.pi / 2.0 - 2.0 * math.atan(t)
    e4, e6, e8 = _E2 ** 2, _E2 ** 3, _E2 ** 4
    phi = (
        chi
        + (_E2 / 2.0 + 5.0 * e4 / 24.0 + e6 / 12.0 + 13.0 * e8 / 360.0) * math.sin(2.0 * chi)
        + (7.0 * e4 / 48.0 + 29.0 * e6 / 240.0 + 811.0 * e8 / 11520.0) * math.sin(4.0 * chi)
        + (7.0 * e6 / 120.0 + 81.0 * e8 / 1120.0) * math.sin(6.0 * chi)
        + (4279.0 * e8 / 161280.0) * math.sin(8.0 * chi)
    )
    lam = math.atan2(x, y) + _LAM_0
    return -math.degrees(phi), normalize_lon(math.degrees(lam))


# --------------------------------------------------------------------------------------
# Vector helpers used by the drift and ice models
# --------------------------------------------------------------------------------------
def uv_to_speed_dir(u: float, v: float) -> Tuple[float, float]:
    """Eastward/northward components to (magnitude, direction-toward in degrees from north)."""
    speed = math.hypot(u, v)
    direction = (math.degrees(math.atan2(u, v)) + 360.0) % 360.0
    return speed, direction


def speed_dir_to_uv(speed: float, direction_toward_deg: float) -> Tuple[float, float]:
    """Magnitude and direction-toward to eastward/northward components."""
    rad = math.radians(direction_toward_deg)
    return speed * math.sin(rad), speed * math.cos(rad)


def wind_from_to_toward(direction_from_deg: float) -> float:
    """Meteorological 'wind from' convention to a 'moving toward' bearing."""
    return (direction_from_deg + 180.0) % 360.0


def meters_to_degrees(dx_m: float, dy_m: float, lat: float) -> Tuple[float, float]:
    """Local metric displacement to a (dlat, dlon) increment at the given latitude."""
    dlat = dy_m / 111_132.0
    cos_lat = max(0.02, math.cos(math.radians(lat)))
    dlon = dx_m / (111_320.0 * cos_lat)
    return dlat, dlon


def coriolis_parameter(lat: float) -> float:
    """f = 2 * omega * sin(lat). Negative in the Southern Hemisphere."""
    from src.core.constants import OMEGA_EARTH

    return 2.0 * OMEGA_EARTH * math.sin(math.radians(lat))
