"""Metrics for SIC evaluation."""
from __future__ import annotations

import numpy as np


def rmse(pred: np.ndarray, obs: np.ndarray, mask=None) -> float:
    if mask is None:
        mask = np.isfinite(pred) & np.isfinite(obs)
    diff = pred[mask] - obs[mask]
    return float(np.sqrt(np.mean(diff ** 2)))


def mae(pred: np.ndarray, obs: np.ndarray, mask=None) -> float:
    if mask is None:
        mask = np.isfinite(pred) & np.isfinite(obs)
    diff = pred[mask] - obs[mask]
    return float(np.mean(np.abs(diff)))


def bias(pred: np.ndarray, obs: np.ndarray, mask=None) -> float:
    if mask is None:
        mask = np.isfinite(pred) & np.isfinite(obs)
    return float(np.mean(pred[mask] - obs[mask]))


def iiee(pred: np.ndarray, obs: np.ndarray, areas_m2: np.ndarray, threshold: float = 0.15, ocean_mask=None) -> float:
    """IIEE = area overestimated + area underestimated (Goessling et al. 2016). 
    Exclude land and missing from both fields."""
    pred = np.array(pred)
    obs = np.array(obs)
    areas_m2 = np.array(areas_m2)
    valid = np.isfinite(pred) & np.isfinite(obs)
    if ocean_mask is not None:
        ocean_mask = np.array(ocean_mask)
        valid = valid & ocean_mask
    # ice/no-ice
    ice_obs = obs >= threshold
    ice_pred = pred >= threshold
    # disagreement
    over = ice_pred & (~ice_obs) & valid
    under = (~ice_pred) & ice_obs & valid
    area_over = float(np.nansum(areas_m2[over])) if np.any(over) else 0.0
    area_under = float(np.nansum(areas_m2[under])) if np.any(under) else 0.0
    total = area_over + area_under
    return total / 1e12  # million km2


def metrics_batch(preds, obs, mask, areas_m2, threshold=0.15):
    """Compute (rmse, mae, bias, iiee) for each prediction in ``preds`` in one pass.

    ``preds`` is a list of 2-D prediction arrays. ``mask`` restricts to the
    analysed cells (e.g. a sector/domain/ocean mask). Returns a list of
    ``(rmse, mae, bias, iiee)`` tuples, one per prediction.
    """
    obs = np.asarray(obs)
    mask = np.asarray(mask, dtype=bool)
    areas_m2 = np.asarray(areas_m2)
    valid = mask & np.isfinite(obs)
    if not np.any(valid):
        return [(float("nan"), float("nan"), float("nan"), float("nan")) for _ in preds]
    out = []
    for pred in preds:
        pred = np.asarray(pred)
        m = valid & np.isfinite(pred)
        if not np.any(m):
            out.append((float("nan"), float("nan"), float("nan"), float("nan")))
            continue
        diff = pred[m] - obs[m]
        rmse = float(np.sqrt(np.mean(diff ** 2)))
        mae = float(np.mean(np.abs(diff)))
        bias = float(np.mean(diff))
        p_v = pred[m]
        obs_v = obs[m]
        ice_obs = obs_v >= threshold
        ice_pred = p_v >= threshold
        area_over = float(np.sum(areas_m2[m][ice_pred & ~ice_obs]))
        area_under = float(np.sum(areas_m2[m][~ice_pred & ice_obs]))
        out.append((rmse, mae, bias, (area_over + area_under) / 1e12))
    return out


def skill_score(rmse_model: float, rmse_baseline: float) -> float:
    if rmse_baseline == 0:
        return np.nan
    return 1.0 - rmse_model / rmse_baseline


def bootstrap_ci_blocks(values_by_block, n_boot: int = 1000, ci: float = 0.95, seed: int = 12345):
    """Bootstrap by BLOCKS of days (month-blocks). Vectorized over resamples.

    Each block is an iterable of per-observation values (e.g. all days in a
    month). Resample blocks with replacement; the statistic is the mean of all
    values in the resampled blocks (weighted by block size).
    """
    rng = np.random.default_rng(seed)
    blocks = [np.asarray(b, dtype=np.float64).ravel() for b in values_by_block]
    blocks = [b for b in blocks if b.size > 0 and np.any(np.isfinite(b))]
    if not blocks:
        return (float("nan"), float("nan"))
    n_blocks = len(blocks)
    block_sums = np.array([b.sum() for b in blocks], dtype=np.float64)
    block_sizes = np.array([b.size for b in blocks], dtype=np.float64)
    idx = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    sums = block_sums[idx]
    counts = block_sizes[idx]
    means = sums.sum(axis=1) / counts.sum(axis=1)
    alpha = (1.0 - ci) / 2.0
    lo = float(np.percentile(means, alpha * 100))
    hi = float(np.percentile(means, (1.0 - alpha) * 100))
    return (lo, hi)
