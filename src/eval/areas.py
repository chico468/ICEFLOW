"""Cell area computation for polar stereographic grid."""
from __future__ import annotations

import numpy as np


def compute_cell_areas(x_m: np.ndarray, y_m: np.ndarray, crs_epsg: str = "EPSG:3412") -> np.ndarray:
    """Compute true cell area in m^2 for polar stereographic grid cells.
    Use projection scale factor / resolution-based area; for NSIDC 25km grid cells
    are approximately equal area in projection but better to compute from dx, dy.
    """
    # Assume regular grid
    dx = float(np.abs(x_m[1] - x_m[0])) if len(x_m) > 1 else 25000.0
    dy = float(np.abs(y_m[1] - y_m[0])) if len(y_m) > 1 else 25000.0
    area_m2 = dx * dy
    # Return 2D array
    areas = np.ones((len(y_m), len(x_m)), dtype=np.float64) * area_m2
    return areas
