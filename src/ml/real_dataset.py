"""Real-data SIC forecasting dataset construction.

This module replaces the synthetic physics sampler in dataset.py with readers for
real NSIDC V6 observations. The feature vectors produced here are exactly the
fields an operator would have from OSI-SAF/AMSR2, ERA5, CMEMS, and the NSIDC CDR
itself -- concentration, climatology, gradients, neighbourhood means, position,
season, and sector.

Splits are by calendar year with a 14-day embargo between blocks (train 2005-2019,
val 2020-2021, test 2022-2024). No data from the val or test blocks is used to
fit the climatology or the damped-tau baseline.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
from scipy.ndimage import uniform_filter

from src.data.nsidc_sea_ice import default_cache_dir, read_nsidc_file
from src.eval import baselines
from src.eval.areas import compute_cell_areas
from src.eval.regions import SECTORS_SIMPLE, AUSTRAL_DEPARTURE_SEASON


REAL_LEAD_DAYS: Tuple[int, ...] = (3, 7, 14)

TRAIN_END_YEAR = 2019
VAL_YEARS = (2020, 2021)
TEST_YEARS = (2022, 2023, 2024)
EMBARGO_DAYS = 14

FEATURE_NAMES_REAL: Tuple[str, ...] = (
    "sic_t0",
    "anomaly_t0",
    "sic_change_1d",
    "sic_change_3d",
    "sic_change_7d",
    "nhood_mean_3x3",
    "nhood_mean_7x7",
    "clim_target",
    "sin_doy",
    "cos_doy",
    "sin_lon",
    "cos_lon",
    "latitude",
    "sector_id",
)


@dataclass
class RealSICSplit:
    """One split of the real SIC forecasting problem.

    ``X`` and ``y`` are the supervised triple. ``baseline`` is the damped-anomaly
    persistence forecast (with tuned tau) for each row, ``truth`` is the observed
    concentration at t0+lead. The final forecast is ``baseline + model.predict(X)``.
    ``cell_index`` gives (row, col) grid positions so per-cell metrics can be
    reconstructed.
    """

    X: np.ndarray
    y: np.ndarray
    baseline: np.ndarray
    truth: np.ndarray
    persistence: np.ndarray
    lead_days: np.ndarray
    cell_y: np.ndarray
    cell_x: np.ndarray
    month: np.ndarray
    sector_id: np.ndarray
    cell_areas: np.ndarray
    feature_names: Tuple[str, ...]
    window_years: Tuple[int, ...]

    def __len__(self) -> int:
        return int(self.X.shape[0])


def _doy_key(d: date) -> Tuple[int, int]:
    return (d.month, d.day)


def _sector_id(lon: float) -> int:
    """Return the sector index (0-4) for a longitude, matching SECTORS_SIMPLE order."""
    lon_norm = ((lon + 180.0) % 360.0) - 180.0
    names = list(SECTORS_SIMPLE.keys())
    for i, name in enumerate(names):
        w, e = SECTORS_SIMPLE[name]
        if w <= e:
            if w <= lon_norm <= e:
                return i
        else:
            if lon_norm >= w or lon_norm <= e:
                return i
    return 0


def _build_sector_id_grid(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
    """Vectorised sector-id grid matching SECTORS_SIMPLE ordering."""
    ny, nx = lat.shape
    sector_grid = np.zeros((ny, nx), dtype=np.int32)
    names = list(SECTORS_SIMPLE.keys())
    lon_norm = ((lon + 180.0) % 360.0) - 180.0
    for i, name in enumerate(names):
        w, e = SECTORS_SIMPLE[name]
        if w <= e:
            mask = (lon_norm >= w) & (lon_norm <= e)
        else:
            mask = (lon_norm >= w) | (lon_norm <= e)
        sector_grid[mask] = i
    return sector_grid


def load_real_dates(
    start: date, end: date, cache_dir: Optional[Path] = None
) -> Tuple[Dict[date, np.ndarray], List[date], Dict[str, Any]]:
    """Load all available daily SIC observations between start and end from cache.

    Returns ``(sic_by_date, gaps, grid)`` where ``grid`` has ``x_m``, ``y_m``,
    ``lat``, ``lon``, ``areas``, ``sector_id`` arrays.
    """
    if cache_dir is None:
        cache_dir = default_cache_dir()
    from src.data.nsidc_sea_ice import NSIDCSeaIceReader

    reader = NSIDCSeaIceReader(cache_dir=cache_dir)
    sic_by_date: Dict[date, np.ndarray] = {}
    gaps: List[date] = []
    grid: Optional[Dict[str, Any]] = None

    from src.eval.io import latlon_grid

    cur = start
    while cur <= end:
        path = cache_dir / reader._filename(cur)
        if not path.is_file():
            gaps.append(cur)
        else:
            try:
                obs = read_nsidc_file(path, source_url=f"{reader._url(cur)}",
                                      retrieved_from_cache=True)
                if obs.observation_date == cur:
                    arr = np.asarray(obs.concentration, dtype=np.float64)
                    sic_by_date[cur] = arr
                    if grid is None:
                        x_m = np.asarray(obs.x_m, dtype=np.float64)
                        y_m = np.asarray(obs.y_m, dtype=np.float64)
                        lat, lon = latlon_grid(x_m, y_m)
                        areas = compute_cell_areas(x_m, y_m)
                        sector_id = _build_sector_id_grid(lat, lon)
                        grid = {
                            "x_m": x_m, "y_m": y_m,
                            "lat": lat.astype(np.float64),
                            "lon": lon.astype(np.float64),
                            "areas": areas,
                            "sector_id": sector_id,
                        }
                else:
                    gaps.append(cur)
            except Exception:
                gaps.append(cur)
        cur += timedelta(days=1)

    if grid is None:
        grid = {"x_m": np.array([]), "y_m": np.array([]),
                "lat": np.array([]), "lon": np.array([]),
                "areas": np.array([]), "sector_id": np.array([])}
    return sic_by_date, gaps, grid


def compute_climatology(
    sic_by_date: Dict[date, np.ndarray],
    train_dates: Sequence[date],
    use_trend: bool = True,
) -> Dict[str, Any]:
    """Wrap baselines.fit_climatology and also produce a reference climatology
    (mean across all DOYs) for the VIZ mask."""
    doy_to_mean, doy_to_trend, base_year = baselines.fit_climatology(
        list(train_dates), sic_by_date, use_trend=use_trend
    )
    if doy_to_mean:
        clim_stack = np.stack(list(doy_to_mean.values()), axis=0)
        with np.errstate(invalid="ignore"):
            clim_ref = np.nanmean(clim_stack, axis=0)
        clim_ref = np.where(np.isfinite(clim_ref), clim_ref, np.nan)
    else:
        clim_ref = None
    return {
        "doy_to_mean": doy_to_mean,
        "doy_to_trend": doy_to_trend,
        "base_year": base_year,
        "clim_ref": clim_ref,
    }


def build_viz_mask(clim_ref: np.ndarray, ocean_mask: np.ndarray) -> np.ndarray:
    """VIZ = ocean cells with mean climatology between 5% and 95%."""
    return ocean_mask & (clim_ref >= 0.05) & (clim_ref <= 0.95)


def build_real_sic_dataset(
    sic_by_date: Dict[date, np.ndarray],
    dates: Sequence[date],
    clim: Dict[str, Any],
    taus: Dict[int, float],
    lat_grid: np.ndarray,
    lon_grid: np.ndarray,
    sector_id_grid: np.ndarray,
    areas_grid: np.ndarray,
    leads: Sequence[int] = REAL_LEAD_DAYS,
    sample_viz_fraction: float = 1.0,
    sample_other_fraction: float = 0.0,
    rng_seed: int = 26059,
) -> RealSICSplit:
    """Build a real-data SIC dataset split.

    For each date t0 in ``dates`` and each lead L:
      * If t0+L is available, compute features for cells and the residual target
        (truth - damped_anomaly_persistence baseline with tuned tau).
      * VIZ cells (climatology 5-95%) are subsampled by ``sample_viz_fraction``.
        A small ``sample_other_fraction`` of non-VIZ ocean cells can be added.

    Features per cell (see FEATURE_NAMES_REAL):
      sic_t0, anomaly_t0, sic_change_1d/3d/7d, nhood_mean_3x3/7x7, clim_target,
      sin/cos_doy, sin/cos_lon, latitude, sector_id

    The baseline stored is the damped persistence with tuned tau; the model
    learns the residual (truth - baseline).
    """
    rng = np.random.default_rng(rng_seed)
    doy_to_mean = clim["doy_to_mean"]
    clim_ref = clim["clim_ref"]

    ocean_mask = np.isfinite(clim_ref)
    viz_mask = build_viz_mask(clim_ref, ocean_mask)

    # Precompute sin/cos lon and lat for broadcast.
    sin_lon_grid = np.sin(2.0 * np.pi * ((lon_grid + 180.0) % 360.0) / 360.0)
    cos_lon_grid = np.cos(2.0 * np.pi * ((lon_grid + 180.0) % 360.0) / 360.0)

    rows_X: List[np.ndarray] = []
    rows_y: List[np.ndarray] = []
    rows_base: List[np.ndarray] = []
    rows_truth: List[np.ndarray] = []
    rows_pers: List[np.ndarray] = []
    rows_lead: List[np.ndarray] = []
    rows_y_idx: List[np.ndarray] = []
    rows_x_idx: List[np.ndarray] = []
    rows_month: List[np.ndarray] = []
    rows_sector: List[np.ndarray] = []
    rows_areas: List[np.ndarray] = []

    sorted_dates = sorted(dates)
    max_lead = max(leads)

    for t0 in sorted_dates:
        if t0 not in sic_by_date:
            continue
        k0 = _doy_key(t0)
        if k0 not in doy_to_mean:
            continue
        obs_t0 = sic_by_date[t0]
        clim_t0 = doy_to_mean[k0]

        doy = t0.timetuple().tm_yday
        sin_doy = np.sin(2.0 * np.pi * doy / 365.25)
        cos_doy = np.cos(2.0 * np.pi * doy / 365.25)

        # SIC change features require prior-day data.
        change_1d = _safe_diff(sic_by_date, t0, obs_t0, 1)
        change_3d = _safe_diff(sic_by_date, t0, obs_t0, 3)
        change_7d = _safe_diff(sic_by_date, t0, obs_t0, 7)

        nhood_3x3 = uniform_filter(np.nan_to_num(obs_t0, nan=0.0), size=3, mode="nearest")
        nhood_7x7 = uniform_filter(np.nan_to_num(obs_t0, nan=0.0), size=7, mode="nearest")

        for lead in leads:
            t1 = t0 + timedelta(days=lead)
            if t1 not in sic_by_date:
                continue
            k1 = _doy_key(t1)
            if k1 not in doy_to_mean:
                continue

            obs_t1 = sic_by_date[t1]
            clim_t1 = doy_to_mean[k1]
            tau = taus.get(lead, taus.get("default", 30.0))

            baseline = baselines.damped_anomaly_persistence(
                obs_t0, clim_t0, clim_t1, lead, tau_days=tau
            )
            truth = obs_t1

            # Build feature matrix for sampled cells.
            cell_mask = _build_cell_mask(
                obs_t0, obs_t1, viz_mask, ocean_mask,
                sample_viz_fraction, sample_other_fraction, rng,
            )

            if not np.any(cell_mask):
                continue

            ys, xs = np.where(cell_mask)
            n = ys.size

            # Per-cell scalar features extracted at the masked locations.
            o0 = obs_t0[ys, xs]
            c0 = clim_t0[ys, xs]
            c1 = clim_t1[ys, xs]
            o1 = obs_t1[ys, xs]
            ch1 = change_1d[ys, xs]
            ch3 = change_3d[ys, xs]
            ch7 = change_7d[ys, xs]
            nh3 = nhood_3x3[ys, xs]
            nh7 = nhood_7x7[ys, xs]
            lat_v = lat_grid[ys, xs]
            slon_v = sin_lon_grid[ys, xs]
            clon_v = cos_lon_grid[ys, xs]
            sid = sector_id_grid[ys, xs].astype(np.float64)
            base_v = baseline[ys, xs]
            pers_v = o0.copy()
            area_v = areas_grid[ys, xs]

            valid = np.isfinite(o0) & np.isfinite(o1) & np.isfinite(c0) & np.isfinite(c1) & \
                    np.isfinite(ch1) & np.isfinite(ch3) & np.isfinite(ch7)
            if not np.any(valid):
                continue
            ys_v, xs_v = ys[valid], xs[valid]

            n_valid = int(valid.sum())
            feats = np.empty((n_valid, len(FEATURE_NAMES_REAL)), dtype=np.float64)
            feats[:, 0] = o0[valid]                          # sic_t0
            feats[:, 1] = o0[valid] - c0[valid]              # anomaly_t0
            feats[:, 2] = ch1[valid]                         # sic_change_1d
            feats[:, 3] = ch3[valid]                         # sic_change_3d
            feats[:, 4] = ch7[valid]                         # sic_change_7d
            feats[:, 5] = nh3[valid]                         # nhood_mean_3x3
            feats[:, 6] = nh7[valid]                         # nhood_mean_7x7
            feats[:, 7] = c1[valid]                          # clim_target
            feats[:, 8] = sin_doy                            # sin_doy (broadcast scalar)
            feats[:, 9] = cos_doy                            # cos_doy
            feats[:, 10] = slon_v[valid]                     # sin_lon
            feats[:, 11] = clon_v[valid]                     # cos_lon
            feats[:, 12] = lat_v[valid]                      # latitude
            feats[:, 13] = sid[valid]                        # sector_id

            rows_X.append(feats)
            rows_y.append(o1[valid] - base_v[valid])
            rows_base.append(base_v[valid])
            rows_truth.append(o1[valid])
            rows_pers.append(pers_v[valid])
            rows_lead.append(np.full(n_valid, float(lead)))
            rows_y_idx.append(ys_v)
            rows_x_idx.append(xs_v)
            rows_month.append(np.full(n_valid, float(t0.month)))
            rows_sector.append(sid[valid])
            rows_areas.append(area_v[valid])

    if not rows_X:
        return RealSICSplit(
            X=np.empty((0, len(FEATURE_NAMES_REAL)), dtype=np.float64),
            y=np.empty((0,), dtype=np.float64),
            baseline=np.empty((0,), dtype=np.float64),
            truth=np.empty((0,), dtype=np.float64),
            persistence=np.empty((0,), dtype=np.float64),
            lead_days=np.empty((0,), dtype=np.float64),
            cell_y=np.empty((0,), dtype=np.intp),
            cell_x=np.empty((0,), dtype=np.intp),
            month=np.empty((0,), dtype=np.float64),
            sector_id=np.empty((0,), dtype=np.float64),
            cell_areas=np.empty((0,), dtype=np.float64),
            feature_names=FEATURE_NAMES_REAL,
            window_years=tuple(),
        )

    return RealSICSplit(
        X=np.concatenate(rows_X, axis=0),
        y=np.concatenate(rows_y, axis=0),
        baseline=np.concatenate(rows_base, axis=0),
        truth=np.concatenate(rows_truth, axis=0),
        persistence=np.concatenate(rows_pers, axis=0),
        lead_days=np.concatenate(rows_lead, axis=0),
        cell_y=np.concatenate(rows_y_idx, axis=0),
        cell_x=np.concatenate(rows_x_idx, axis=0),
        month=np.concatenate(rows_month, axis=0),
        sector_id=np.concatenate(rows_sector, axis=0),
        cell_areas=np.concatenate(rows_areas, axis=0),
        feature_names=FEATURE_NAMES_REAL,
        window_years=tuple(sorted(set(d.year for d in dates))),
    )


def _safe_diff(sic_by_date, t0, obs_t0, days_back):
    """Return obs_t0 - obs_(t0 - days_back), NaN where prior day is missing."""
    t_prev = t0 - timedelta(days=days_back)
    if t_prev not in sic_by_date:
        return np.full_like(obs_t0, np.nan)
    return obs_t0 - sic_by_date[t_prev]


def _build_cell_mask(
    obs_t0: np.ndarray,
    obs_t1: np.ndarray,
    viz_mask: np.ndarray,
    ocean_mask: np.ndarray,
    sample_viz_fraction: float,
    sample_other_fraction: float,
    rng: np.random.Generator,
) -> np.ndarray:
    """Select cells: all/allotted VIZ cells plus a small sample of other ocean cells."""
    valid = np.isfinite(obs_t0) & np.isfinite(obs_t1)
    viz_cells = viz_mask & valid
    other_cells = ocean_mask & (~viz_mask) & valid

    result = np.zeros_like(viz_mask, dtype=bool)

    # VIZ cells.
    viz_flat = viz_cells.ravel()
    viz_indices = np.flatnonzero(viz_flat)
    if viz_indices.size > 0:
        if sample_viz_fraction >= 1.0:
            result |= viz_cells
        else:
            n_take = max(1, int(viz_indices.size * sample_viz_fraction))
            take = rng.choice(viz_indices, size=n_take, replace=False)
            sub = np.zeros(viz_flat.size, dtype=bool)
            sub[take] = True
            result |= sub.reshape(viz_mask.shape)

    # Other ocean cells (small sample).
    if sample_other_fraction > 0.0:
        other_flat = other_cells.ravel()
        other_indices = np.flatnonzero(other_flat)
        if other_indices.size > 0:
            n_take = max(1, int(other_indices.size * sample_other_fraction))
            take = rng.choice(other_indices, size=n_take, replace=False)
            sub = np.zeros(other_flat.size, dtype=bool)
            sub[take] = True
            result |= sub.reshape(ocean_mask.shape)

    return result


def build_splits(
    sic_by_date: Dict[date, np.ndarray],
    clim: Dict[str, Any],
    taus: Dict[int, float],
    grid: Dict[str, Any],
    train_dates: Sequence[date],
    val_dates: Sequence[date],
    test_dates: Sequence[date],
    leads: Sequence[int] = REAL_LEAD_DAYS,
    sample_viz_fraction: float = 1.0,
    sample_other_fraction: float = 0.01,
    seed: int = 26059,
) -> Dict[str, RealSICSplit]:
    """Build train/val/test RealSICSplit objects from real NSIDC data."""
    lat_grid = grid["lat"]
    lon_grid = grid["lon"]
    sector_grid = grid["sector_id"]
    areas_grid = grid["areas"]

    return {
        "train": build_real_sic_dataset(
            sic_by_date, train_dates, clim, taus,
            lat_grid, lon_grid, sector_grid, areas_grid,
            leads, sample_viz_fraction, sample_other_fraction, seed,
        ),
        "val": build_real_sic_dataset(
            sic_by_date, val_dates, clim, taus,
            lat_grid, lon_grid, sector_grid, areas_grid,
            leads, 1.0, 0.0, seed + 100,
        ),
        "test": build_real_sic_dataset(
            sic_by_date, test_dates, clim, taus,
            lat_grid, lon_grid, sector_grid, areas_grid,
            leads, 1.0, 0.0, seed + 200,
        ),
    }
