"""Geodesy and land-mask tests.

These matter more than they look. The route optimiser calls the land mask hundreds of thousands
of times per plan, and a projection that is not a true inverse would put the map and the model in
different places.
"""
from __future__ import annotations

import math

import pytest

from src.core.geo import (
    cross_track_distance_nm,
    destination_point,
    from_epsg3031,
    great_circle_path,
    haversine_nm,
    initial_bearing_deg,
    normalize_lon,
    path_length_nm,
    point_to_segment_nm,
    to_epsg3031,
)
from src.data.landmask import coast_clearance_nm, get_land_mask, is_land


def test_haversine_known_distance():
    """Cape Town to Bharati anchorage is roughly 2800 nautical miles."""
    nm = haversine_nm(-34.2, 18.43, -69.2, 76.3)
    assert 2700 < nm < 2950


def test_haversine_is_symmetric_and_zero_on_identity():
    assert haversine_nm(-60.0, 20.0, -60.0, 20.0) == pytest.approx(0.0, abs=1e-9)
    assert haversine_nm(-60.0, 20.0, -65.0, 30.0) == pytest.approx(
        haversine_nm(-65.0, 30.0, -60.0, 20.0), rel=1e-12
    )


def test_bearing_cardinal_directions():
    assert initial_bearing_deg(-60.0, 20.0, -59.0, 20.0) == pytest.approx(0.0, abs=1e-6)
    assert initial_bearing_deg(-60.0, 20.0, -61.0, 20.0) == pytest.approx(180.0, abs=1e-6)
    east = initial_bearing_deg(-60.0, 20.0, -60.0, 21.0)
    assert 89.0 < east < 91.0


def test_destination_point_round_trips_with_haversine():
    lat, lon = destination_point(-60.0, 20.0, 135.0, 250.0)
    assert haversine_nm(-60.0, 20.0, lat, lon) == pytest.approx(250.0, rel=1e-6)


def test_epsg3031_forward_inverse_is_exact():
    """The projection pair must be a true inverse; the map depends on it."""
    for lat, lon in [(-70.7667, 11.7333), (-69.4075, 76.1908), (-55.0, -120.0), (-80.0, 179.0)]:
        x, y = to_epsg3031(lat, lon)
        back_lat, back_lon = from_epsg3031(x, y)
        assert back_lat == pytest.approx(lat, abs=1e-9)
        assert normalize_lon(back_lon - lon) == pytest.approx(0.0, abs=1e-9)


def test_epsg3031_axis_convention():
    """+x toward 90 E, +y toward 0 E, origin at the pole."""
    x_pole, y_pole = to_epsg3031(-90.0, 0.0)
    assert (x_pole, y_pole) == pytest.approx((0.0, 0.0), abs=1e-6)

    x0, y0 = to_epsg3031(-71.0, 0.0)
    assert y0 > 0 and abs(x0) < 1e-6

    x90, y90 = to_epsg3031(-71.0, 90.0)
    assert x90 > 0 and abs(y90) < 1e-6


def test_epsg3031_true_scale_at_standard_parallel():
    """Distance along the 71 S parallel should be near-exact in the projected plane."""
    a = to_epsg3031(-71.0, 0.0)
    b = to_epsg3031(-71.0, 1.0)
    projected_km = math.hypot(b[0] - a[0], b[1] - a[1]) / 1000.0
    true_km = haversine_nm(-71.0, 0.0, -71.0, 1.0) * 1.852
    assert projected_km == pytest.approx(true_km, rel=0.01)


def test_great_circle_path_endpoints_and_length():
    pts = great_circle_path(-34.2, 18.43, -69.2, 76.3, 40)
    assert len(pts) == 40
    assert pts[0] == pytest.approx((-34.2, 18.43))
    assert pts[-1][0] == pytest.approx(-69.2, abs=1e-6)
    direct = haversine_nm(-34.2, 18.43, -69.2, 76.3)
    # A polyline along the great circle is never shorter than the great circle itself.
    assert path_length_nm(pts) == pytest.approx(direct, rel=0.01)


def test_cross_track_is_zero_on_the_great_circle():
    """
    A point taken from the great circle itself must be on it.

    Note the trap this replaces: the midpoint of the *parallel* between two points at equal
    latitude is NOT on their great circle. The great circle bulges poleward, so (-60, 25) sits
    about 5.7 nm off the track from (-60, 20) to (-60, 30). That is correct geodesy, and it is
    exactly the error a rhumb-line assumption would introduce.
    """
    a, b = (-60.0, 20.0), (-60.0, 30.0)
    midpoint = great_circle_path(a[0], a[1], b[0], b[1], 3)[1]
    assert cross_track_distance_nm(midpoint, a, b) == pytest.approx(0.0, abs=0.5)
    assert midpoint[0] < -60.0  # the great circle really does bulge poleward


def test_cross_track_sign_flips_across_the_track():
    a, b = (-60.0, 20.0), (-60.0, 30.0)
    north = cross_track_distance_nm((-58.0, 25.0), a, b)
    south = cross_track_distance_nm((-62.0, 25.0), a, b)
    assert north * south < 0.0


def test_point_to_segment_clamps_to_the_endpoint():
    """A point beyond the segment end measures to the endpoint, not to the infinite circle."""
    assert point_to_segment_nm((-60.0, 40.0), (-60.0, 20.0), (-60.0, 30.0)) == pytest.approx(
        haversine_nm(-60.0, 40.0, -60.0, 30.0), rel=1e-6
    )


def test_normalize_lon_wraps():
    assert normalize_lon(190.0) == pytest.approx(-170.0)
    assert normalize_lon(-190.0) == pytest.approx(170.0)
    assert normalize_lon(0.0) == pytest.approx(0.0)


def test_land_mask_known_points():
    mask = get_land_mask()
    assert mask.is_land(-70.7667, 11.7333) is True      # Maitri, inland on the Schirmacher Oasis
    assert mask.is_land(-60.0, 20.0) is False           # open Southern Ocean
    assert mask.is_land(-85.0, 0.0) is True             # deep interior


def test_land_mask_stats():
    stats = get_land_mask().stats()
    assert stats["polygons"] > 50
    assert stats["vertices"] > 1000
    assert stats["northern_limit_lat"] < -55.0


def test_coast_clearance_is_positive_at_sea_and_zero_on_land():
    assert coast_clearance_nm(-60.0, 20.0) > 100.0
    assert is_land(-85.0, 0.0) is True


def test_no_land_north_of_the_mask_limit():
    """The mask covers Antarctica only; nothing north of its limit may report as land."""
    limit = get_land_mask().northern_limit
    for lon in range(-180, 180, 30):
        assert get_land_mask().is_land(limit + 1.0, float(lon)) is False
