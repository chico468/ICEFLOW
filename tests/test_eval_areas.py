import numpy as np
import pytest
from pyproj import CRS, Transformer

from src.eval.areas import compute_cell_areas

EPSG = "EPSG:3412"


def _y_for_lat70():
    """Projected y at lon=0, lat=-70 for EPSG:3412 (standard parallel)."""
    return 2187973.819


def test_area_known_answer_70s():
    # A 25 km cell centred on 70 S should be ~625 km^2.
    x_m = np.array([0.0])
    y_m = np.array([_y_for_lat70()])
    areas = compute_cell_areas(x_m, y_m, EPSG)
    assert areas.shape == (1, 1)
    km2 = areas[0, 0] / 1e6
    assert km2 == pytest.approx(625.0, rel=0.01)


def test_area_monotonic_with_latitude():
    # Single 25 km cells centred on each latitude (dx/dy fall back to 25 km).
    # Poleward of 70 S the cell area grows; equatorward it shrinks.
    y_at = {
        -85: 541978.122,
        -80: 1085943.188,
        -70: _y_for_lat70(),
        -60: 3323230.519,
    }
    areas = {lat: float(compute_cell_areas(np.array([0.0]), np.array([y]))[0, 0]) for lat, y in y_at.items()}
    a85, a80, a70, a60 = areas[-85], areas[-80], areas[-70], areas[-60]
    assert a85 > a80 > a70 > 0
    assert a70 > a60
    # Known-answer sanity at 70 S.
    assert a70 / 1e6 == pytest.approx(625.0, rel=0.01)
    # Poleward area exceeds 70 S area.
    assert a85 > a70
    assert a80 > a70


def _independent_cell_areas(x_m, y_m, R=6371008.8):
    """Independent areal-scale estimate: spherical equal-area on cell corners."""
    crs = CRS.from_epsg(3412)
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    dx = float(np.mean(np.diff(x_m)))
    dy = float(np.mean(np.diff(y_m)))
    ny, nx = len(y_m), len(x_m)
    xlo = x_m - dx / 2.0
    xhi = x_m + dx / 2.0
    ylo = y_m - dy / 2.0
    yhi = y_m + dy / 2.0
    areas = np.zeros((ny, nx))
    for i in range(ny):
        for j in range(nx):
            xs = [xlo[j], xhi[j], xhi[j], xlo[j]]
            ys = [ylo[i], ylo[i], yhi[i], yhi[i]]
            lon, lat = tr.transform(np.array(xs), np.array(ys))
            a = 0.0
            for k in range(4):
                la1, la2 = np.radians(lat[k]), np.radians(lat[(k + 1) % 4])
                dl = np.radians(lon[(k + 1) % 4] - lon[k])
                a += (np.sin(la1) + np.sin(la2)) / 2.0 * dl
            areas[i, j] = R * R * abs(a)
    return areas


def test_summed_sector_area_matches_independent():
    # Grid centred ~70 S spanning the Weddell sector (lon -60..20).
    nx, ny = 80, 80
    dx = 25000.0
    y0 = _y_for_lat70()
    x_m = (np.arange(nx) - (nx - 1) / 2.0) * dx
    y_m = y0 + (np.arange(ny) - (ny - 1) / 2.0) * dx
    areas = compute_cell_areas(x_m, y_m, EPSG)
    assert areas.shape == (ny, nx)

    crs = CRS.from_epsg(3412)
    tr = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(x_m, y_m)
    lon, lat = tr.transform(xx, yy)
    in_sector = (lon >= -60.0) & (lon <= 20.0)
    ocean = in_sector  # whole grid treated as ocean

    summed = float(np.nansum(areas[ocean]))
    independent = float(np.nansum(_independent_cell_areas(x_m, y_m)[ocean]))
    assert summed > 0
    rel = abs(summed - independent) / independent
    assert rel < 0.05
