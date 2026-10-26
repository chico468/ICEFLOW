import time
from datetime import date

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


def test_fit_climatology_trend_matches_closed_form():
    rng = np.random.default_rng(0)
    years = np.arange(2005, 2025, dtype=float)
    ny, nx = 6, 7
    slope = 0.01
    intercept = 0.3
    data = np.empty((len(years), ny, nx))
    for i, y in enumerate(years):
        data[i] = intercept + slope * (y - years.mean()) + rng.normal(0, 1e-6, size=(ny, nx))
    sic_by_date = {date(int(y), 6, 1): data[i] for i, y in enumerate(years)}
    train_dates = sorted(sic_by_date.keys())
    doy_to_mean, doy_to_trend, base_year = baselines.fit_climatology(
        train_dates, sic_by_date, use_trend=True
    )
    mean, trend = doy_to_mean.values().__iter__().__next__(), None
    trend = list(doy_to_trend.values())[0]
    assert trend.shape == (ny, nx)
    assert np.allclose(trend, slope, atol=1e-9)


def test_fit_climatology_vectorised_under_60s():
    """Benchmark: (332, 316) grid x 20 years must finish in under 60 s."""
    ny, nx, n_years = 332, 316, 20
    years = np.arange(2005, 2005 + n_years, dtype=float)
    rng = np.random.default_rng(42)
    data = np.stack([rng.normal(0.5, 0.1, size=(ny, nx)) for _ in range(n_years)])
    sic_by_date = {date(int(y), 6, 1): data[i] for i, y in enumerate(years)}
    train_dates = sorted(sic_by_date.keys())
    t0 = time.perf_counter()
    doy_to_mean, doy_to_trend, _ = baselines.fit_climatology(
        train_dates, sic_by_date, use_trend=True
    )
    elapsed = time.perf_counter() - t0
    assert elapsed < 60.0, f"fit_climatology took {elapsed:.2f}s, must be < 60s"
    assert len(doy_to_mean) > 0
    mean = next(iter(doy_to_mean.values()))
    trend = next(iter(doy_to_trend.values()))
    assert mean.shape == (ny, nx)
    assert trend.shape == (ny, nx)

