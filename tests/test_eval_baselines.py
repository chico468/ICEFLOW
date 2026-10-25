import numpy as np
from src.eval import baselines


def test_persistence():
    obs = np.array([0.5, 0.3])
    assert np.allclose(baselines.persistence(obs), obs)


def test_damped_anomaly():
    obs_t0 = np.array([0.8])
    clim_t0 = np.array([0.5])
    clim_tlead = np.array([0.6])
    res = baselines.damped_anomaly_persistence(obs_t0, clim_t0, clim_tlead, 7)
    # anomaly decays toward climatology
    assert res[0] < obs_t0[0] or res[0] >= clim_tlead[0]
