"""Baselines for SIC forecasting. All use only data BEFORE forecast origin."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Tuple

import numpy as np


def persistence(obs_t0: np.ndarray) -> np.ndarray:
    return obs_t0.copy()


def climatology_by_doy(doy_to_mean: Dict[Tuple[int, int], np.ndarray], doy: Tuple[int, int]) -> np.ndarray:
    return doy_to_mean.get(doy).copy() if doy in doy_to_mean else None


def fit_climatology(train_dates: list[date], sic_by_date: Dict[date, np.ndarray], use_trend: bool = True):
    """Fit climatology on training years only. NaN-aware."""
    from collections import defaultdict
    by_doy = defaultdict(list)
    for d in train_dates:
        if d in sic_by_date:
            arr = sic_by_date[d]
            if arr is not None and np.any(np.isfinite(arr)):
                by_doy[(d.month, d.day)].append((d.year, arr))
    doy_to_mean = {}
    doy_to_trend = {}
    for k, vals in by_doy.items():
        years = np.array([v[0] for v in vals])
        data = np.stack([np.where(np.isfinite(v[1]), v[1], np.nan) for v in vals], axis=0)
        mean = np.nanmean(data, axis=0)
        if use_trend and len(years) >= 3:
            try:
                # NaN-aware polyfit per pixel
                trend = np.zeros_like(mean)
                for idx in np.ndindex(mean.shape):
                    y = data[(slice(None),) + idx]
                    mask = np.isfinite(y)
                    if np.sum(mask) >= 3:
                        try:
                            coeffs = np.polyfit(years[mask], y[mask], 1)
                            trend[idx] = coeffs[0]
                        except Exception:
                            trend[idx] = 0.0
            except Exception:
                trend = np.zeros_like(mean)
        else:
            trend = np.zeros_like(mean)
        doy_to_mean[k] = mean
        doy_to_trend[k] = trend
    return doy_to_mean, doy_to_trend


def damped_anomaly_persistence(
    obs_t0: np.ndarray,
    clim_t0: np.ndarray,
    clim_tlead: np.ndarray,
    lead_days: int,
    tau_days: float = 30.0,
):
    """Anomaly relative to climatology decays with lead."""
    anomaly_t0 = obs_t0 - clim_t0
    decay = np.exp(-lead_days / tau_days)
    return clim_tlead + anomaly_t0 * decay
