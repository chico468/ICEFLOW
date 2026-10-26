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
    """Fit per-(month,day) climatology on training years only. NaN-aware.

    Returns ``(doy_to_mean, doy_to_trend, base_year)``. ``doy_to_trend`` is the
    per-pixel linear slope (per year) computed in closed form with per-pixel
    NaN masks rather than a Python ``np.polyfit`` loop.
    """
    from collections import defaultdict

    by_doy: dict[Tuple[int, int], list[Tuple[int, np.ndarray]]] = defaultdict(list)
    for d in train_dates:
        if d in sic_by_date:
            arr = sic_by_date[d]
            if arr is not None and np.any(np.isfinite(arr)):
                by_doy[(d.month, d.day)].append((d.year, arr))

    doy_to_mean: Dict[Tuple[int, int], np.ndarray] = {}
    doy_to_trend: Dict[Tuple[int, int], np.ndarray] = {}

    # Reference year for the centred trend term (shared across DOYs).
    base_year = float(np.mean(sorted({d.year for d in train_dates}))) if train_dates else 0.0

    for key, vals in by_doy.items():
        years = np.array([v[0] for v in vals], dtype=np.float64)
        stacked = np.stack(
            [np.where(np.isfinite(v[1]), v[1], np.nan) for v in vals], axis=0
        )  # (n_years, ny, nx)
        valid = np.isfinite(stacked)
        cnt = valid.sum(axis=0)

        with np.errstate(invalid="ignore", divide="ignore"):
            mean = np.where(cnt > 0, np.nansum(stacked, axis=0) / np.maximum(cnt, 1), np.nan)

        if use_trend and len(years) >= 3:
            xbar = np.where(cnt > 0, np.where(valid, years[:, None, None], 0.0).sum(axis=0) / np.maximum(cnt, 1), 0.0)
            dev_x = years[:, None, None] - xbar[None, :, :]
            dev_y = stacked - mean[None, :, :]
            with np.errstate(invalid="ignore"):
                numer = np.nansum(dev_x * dev_y, axis=0)
            denom = np.sum(valid * (dev_x ** 2), axis=0)
            safe = (denom > 0) & (cnt >= 3)
            trend = np.divide(numer, denom, out=np.zeros_like(numer), where=safe)
            trend = np.where(np.isfinite(trend), trend, 0.0)
        else:
            trend = np.zeros_like(mean)

        doy_to_mean[key] = mean
        doy_to_trend[key] = trend
    return doy_to_mean, doy_to_trend, base_year


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
