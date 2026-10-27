"""Baselines for SIC forecasting. All use only data BEFORE forecast origin."""
from __future__ import annotations

from datetime import date, timedelta
from typing import Dict, Optional, Sequence, Tuple

import numpy as np
from scipy.optimize import minimize_scalar


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


def _doy_key(d: date) -> Tuple[int, int]:
    return (d.month, d.day)


def fit_damped_tau(
    sic_by_date: Dict[date, np.ndarray],
    train_dates: Sequence[date],
    doy_to_mean: Dict[Tuple[int, int], np.ndarray],
    lead_days: int,
    viz_mask: np.ndarray,
    tau_bounds: Tuple[float, float] = (3.0, 365.0),
    max_pairs: Optional[int] = None,
    seed: int = 26059,
) -> Tuple[float, float]:
    """
    Find the tau that minimises RMSE of the damped-anomaly-persistence baseline
    at a given lead, tuned on the training dates only.

    Uses the analytic result that RMSE^2 is a quadratic in the decay factor
    ``d = exp(-lead/tau)``::

        RMSE^2(d) = (S_bb + 2*d*S_ab + d^2*S_aa) / N

    where S_bb = sum of (clim_tlead - obs_tlead)^2, S_ab = sum of
    (clim_tlead - obs_tlead)*(obs_t0 - clim_t0), S_aa = sum of
    (obs_t0 - clim_t0)^2, all over VIZ cells and available date pairs.

    The unconstrained optimum ``d* = -S_ab / S_aa`` is clamped to (0, 1]
    (positive, decaying) and converted to tau via ``tau = -lead / ln(d*)``.
    A scalar minimisation refines within the allowed bounds when the analytic
    optimum falls outside them.

    Returns ``(tau_days, rmse_at_tau)``.
    """
    rng = np.random.default_rng(seed)
    available = sorted(d for d in train_dates if d in sic_by_date)
    if max_pairs is not None and len(available) > max_pairs:
        available = sorted(rng.choice(available, size=max_pairs, replace=False))

    valid_count = 0
    sum_base_sq = 0.0
    sum_cross = 0.0
    sum_anom_sq = 0.0
    sse = 0.0

    for t0 in available:
        t1 = t0 + timedelta(days=lead_days)
        if t1 not in sic_by_date:
            continue
        k0 = _doy_key(t0)
        k1 = _doy_key(t1)
        if k0 not in doy_to_mean or k1 not in doy_to_mean:
            continue
        obs_t0 = sic_by_date[t0]
        obs_t1 = sic_by_date[t1]
        clim_t0 = doy_to_mean[k0]
        clim_t1 = doy_to_mean[k1]
        if not np.any(viz_mask & np.isfinite(obs_t0) & np.isfinite(obs_t1)):
            continue

        mask = viz_mask & np.isfinite(obs_t0) & np.isfinite(obs_t1)
        o0 = obs_t0[mask]
        o1 = obs_t1[mask]
        c0 = clim_t0[mask]
        c1 = clim_t1[mask]

        base_err = c1 - o1
        anom_t0 = o0 - c0
        sum_base_sq += float(np.sum(base_err * base_err))
        sum_cross += float(np.sum(base_err * anom_t0))
        sum_anom_sq += float(np.sum(anom_t0 * anom_t0))
        sse += float(np.sum(base_err * base_err))  # at d=0, baseline = climatology
        valid_count += o0.size

    if valid_count == 0:
        return tau_bounds[0], float("inf")

    def _rmse_sq(d: float) -> float:
        return (sum_base_sq + 2.0 * d * sum_cross + d * d * sum_anom_sq) / valid_count

    # Analytic optimum.
    d_opt = -sum_cross / sum_anom_sq if sum_anom_sq > 1e-30 else 1.0
    d_opt = float(np.clip(d_opt, 1e-6, 1.0))

    def _rmse_from_d(d: float) -> float:
        return float(np.sqrt(_rmse_sq(d)))

    if d_opt <= 1e-6:
        tau = tau_bounds[0]
        rmse = _rmse_from_d(1e-6)
    elif d_opt >= 1.0 - 1e-9:
        tau = tau_bounds[1]
        rmse = _rmse_from_d(1.0)
    else:
        tau = float(-lead_days / np.log(d_opt))
        tau = float(np.clip(tau, tau_bounds[0], tau_bounds[1]))
        decay = float(np.exp(-lead_days / tau))
        rmse = _rmse_from_d(decay)

    # Refine with scalar minimisation in case the analytic optimum was clamped.
    def _neg_skill_neg(tau_log: float) -> float:
        tau_v = tau_bounds[0] * (tau_bounds[1] / tau_bounds[0]) ** tau_log
        d = float(np.exp(-lead_days / tau_v))
        return _rmse_from_d(d)

    res = minimize_scalar(
        _neg_skill_neg, bounds=(0.0, 1.0), method="bounded",
        options={"xatol": 1e-3},
    )
    tau_refined = float(
        tau_bounds[0] * (tau_bounds[1] / tau_bounds[0]) ** res.x
    )
    decay_r = float(np.exp(-lead_days / tau_refined))
    rmse_r = _rmse_from_d(decay_r)

    if rmse_r < rmse:
        tau, rmse = tau_refined, rmse_r

    return tau, rmse
