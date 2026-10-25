import numpy as np
from src.eval import metrics


def test_metrics():
    pred = np.array([0.5, 0.5])
    obs = np.array([0.4, 0.6])
    assert metrics.rmse(pred, obs) > 0
    assert metrics.mae(pred, obs) > 0


def test_iiee():
    pred = np.array([[0.8]])
    obs = np.array([[0.0]])
    areas = np.array([[1e12]])
    ocean_mask = np.array([[True]])
    iiee = metrics.iiee(pred, obs, areas, ocean_mask=ocean_mask)
    assert iiee > 0


def test_bootstrap_blocks():
    blocks = [[0.1, 0.2], [0.15, 0.25]]
    lo, hi = metrics.bootstrap_ci_blocks(blocks)
    assert lo <= hi
