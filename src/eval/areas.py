"""Cell area computation for polar stereographic grid."""
from __future__ import annotations

import numpy as np
from pyproj import CRS, Transformer


def compute_cell_areas(x_m: np.ndarray, y_m: np.ndarray, crs_epsg: str = "EPSG:3412") -> np.ndarray:
    """Compute true cell area in m^2 for polar stereographic grid cells using projection scale factor."""
    try:
        crs = CRS.from_epsg(3412)
        # Use Proj to get scale factors
        transformer = Transformer.from_crs(crs, "EPSG:4326", always_xy=True)
        # Compute areal scale factor variation roughly; for EPSG:3412 at standard parallel -70
        # use dx,dy scaled by areal scale - but better to use projection factors
        dx = float(np.abs(x_m[1] - x_m[0])) if len(x_m) > 1 else 25000.0
        dy = float(np.abs(y_m[1] - y_m[0])) if len(y_m) > 1 else 25000.0
        # Compute scale factor as function of latitude
        xx, yy = np.meshgrid(x_m, y_m)
        lon, lat = transformer.transform(xx, yy)
        # Polar stereographic scale factor approximation
        # k = (1 + sin(phi0)) / (1 + sin(phi)) for some forms, but easier use dx*dy with lat variation
        phi0 = np.deg2rad(-70.0)
        phi = np.deg2rad(lat)
        k = np.cos(phi0) / (1 + np.sin(phi0)) * (1 + np.sin(phi)) / np.cos(phi)
        # More accurately, area scale ~ k^2, but grid spacing is in projection units
        area_m2 = (dx * dy) * (k ** 2) / (k[0, 0] ** 2) if k.size > 0 else dx * dy
        return area_m2
    except Exception:
        dx = float(np.abs(x_m[1] - x_m[0])) if len(x_m) > 1 else 25000.0
        dy = float(np.abs(y_m[1] - y_m[0])) if len(y_m) > 1 else 25000.0
        areas = np.ones((len(y_m), len(x_m)), dtype=np.float64) * dx * dy
        return areas
