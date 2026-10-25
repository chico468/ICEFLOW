import numpy as np
from src.eval.areas import compute_cell_areas


def test_area_varies_with_latitude():
    x = np.array([-1000000, -975000])
    y = np.array([1000000, 500000, -1000000])
    areas = compute_cell_areas(x, y)
    assert areas.shape == (3, 2)
    # Areas should vary
    assert np.std(areas) > 0 or areas[0,0] != areas[2,0]
