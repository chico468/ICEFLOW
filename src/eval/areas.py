"""Cell area computation for polar stereographic grids.

Areas are derived from the projection's areal scale factor so they vary with
latitude. For a conformal projection the grid spacing (dx*dy) measured in the
projection plane must be divided by the areal scale factor to recover the true
area on the ellipsoid.

    real_area = (dx * dy) / areal_scale(lat, lon)

For NSIDC Sea Ice Polar Stereographic South (EPSG:3412) the standard parallel is
70 S, so a 25 km cell centred on 70 S has a true area of ~625 km^2 (== 25000^2).
"""
from __future__ import annotations

import numpy as np
from pyproj import CRS, Proj, Transformer


def _crs_from_epsg(crs_epsg: str) -> CRS:
    code = int(str(crs_epsg).split(":")[-1])
    return CRS.from_epsg(code)


def compute_cell_areas(
    x_m: np.ndarray,
    y_m: np.ndarray,
    crs_epsg: str = "EPSG:3412",
) -> np.ndarray:
    """True cell area in m^2 for a polar stereographic grid.

    Parameters
    ----------
    x_m, y_m:
        1-D projected coordinate arrays (metres) of the *cell centres*.
    crs_epsg:
        Source CRS, e.g. ``"EPSG:3412"`` (NSIDC Sea Ice Polar Stereographic South).

    Returns
    -------
    np.ndarray of shape ``(len(y_m), len(x_m))`` with the true area (m^2) of each
    grid cell, computed as ``dx*dy / areal_scale`` from pyproj.
    """
    x_m = np.asarray(x_m, dtype=np.float64)
    y_m = np.asarray(y_m, dtype=np.float64)
    crs = _crs_from_epsg(crs_epsg)
    proj = Proj(crs)
    transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)

    if x_m.size > 1:
        dx = float(np.mean(np.diff(x_m)))
    else:
        dx = 25000.0
    if y_m.size > 1:
        dy = float(np.mean(np.diff(y_m)))
    else:
        dy = 25000.0

    if abs(dx) < 1e-6:
        dx = 25000.0
    if abs(dy) < 1e-6:
        dy = 25000.0

    xx, yy = np.meshgrid(x_m, y_m)  # shape (ny, nx)
    lon, lat = transformer.transform(xx, yy)
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)

    factors = proj.get_factors(lon, lat)
    areal_scale = np.asarray(factors.areal_scale, dtype=np.float64)

    nominal = dx * dy
    # Guard against zero/negative scale (singular points); fall back to nominal.
    safe = np.where(areal_scale > 1e-6, areal_scale, 1.0)
    areas = nominal / safe
    areas = np.where(np.isfinite(areas), areas, nominal)
    return areas
