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


def skill_score(rmse_model: float, rmse_baseline: float) -> float:
    if rmse_baseline == 0:
        return np.nan
    return 1.0 - rmse_model / rmse_baseline


def bootstrap_ci_blocks(values_by_block: list, n_boot: int = 1000, ci: float = 0.95, seed: int = 12345):
    """Bootstrap by BLOCKS of days (not individual days)."""
    rng = np.random.default_rng(seed)
    blocks = list(values_by_block)
    if not blocks:
        return (np.nan, np.nan)
    n_blocks = len(blocks)
    stats = []
    for _ in range(n_boot):
        idx = rng.integers(0, n_blocks, size=n_blocks)
        sample_blocks = [blocks[i] for i in idx]
        # flatten
        flat = []
        for b in sample_blocks:
            if hasattr(b, '__iter__') and not isinstance(b, str):
                flat.extend(b)
            else:
                flat.append(b)
        if flat:
            stats.append(np.mean(flat))
    stats = np.array(stats)
    alpha = (1 - ci) / 2
    return (float(np.percentile(stats, alpha * 100)), float(np.percentile(stats, (1 - alpha) * 100)))
