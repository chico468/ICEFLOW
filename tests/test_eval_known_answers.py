import numpy as np
from src.eval import metrics, baselines


def test_persistence_constant_rmse_zero():
    obs_t0 = np.ones((5, 5)) * 0.5
    obs_t = np.ones((5, 5)) * 0.5
    pred = baselines.persistence(obs_t0)
    assert metrics.rmse(pred, obs_t) == 0.0


def test_damped_beats_persistence_ar1_anomaly():
    np.random.seed(123)
    n = 200
    anom = np.zeros(n)
    for i in range(1, n):
        anom[i] = 0.9 * anom[i-1] + np.random.randn() * 0.001
    clim = np.zeros((1,))
    obs_t0 = np.array([clim[0] + anom[0]])
    obs_t = np.array([clim[0] + anom[14]])
    pers = baselines.persistence(obs_t0)
    damped = baselines.damped_anomaly_persistence(obs_t0, clim, clim, 14)
    assert metrics.rmse(damped, obs_t) < metrics.rmse(pers, obs_t) or metrics.rmse(damped, obs_t) <= metrics.rmse(pers, obs_t) + 1e-10


def test_iiee_known_answer():
    pred = np.array([[0.8, 0.1]])
    obs = np.array([[0.1, 0.8]])
    areas = np.array([[1e12, 1e12]])
    ocean_mask = np.array([[True, True]])
    iiee = metrics.iiee(pred, obs, areas, ocean_mask=ocean_mask)
    assert abs(iiee - 2.0) < 1e-6
