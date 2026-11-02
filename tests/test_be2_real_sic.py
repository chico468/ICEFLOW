"""Tests for real-data SIC forecasting (BE-2)."""
from __future__ import annotations

import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.eval import baselines
from src.ml.real_dataset import (
    RealSICSplit,
    build_real_sic_dataset,
    compute_climatology,
    build_viz_mask,
    FEATURE_NAMES_REAL,
    REAL_LEAD_DAYS,
    TRAIN_END_YEAR,
    VAL_YEARS,
    TEST_YEARS,
    EMBARGO_DAYS,
)
from src.ml.real_sic_forecaster import RealSICForecaster


def _make_synthetic_sic(n_days: int = 400, ny: int = 20, nx: int = 20, seed: int = 42) -> dict:
    """Generate a small synthetic SIC dataset for tests."""
    rng = np.random.default_rng(seed)
    start = date(2005, 1, 1)
    sic_by_date = {}
    climatology = 0.5 + 0.2 * np.sin(2 * np.pi * np.arange(ny)[:, None] / ny)
    anom = np.zeros((ny, nx))
    for i in range(n_days):
        d = start + timedelta(days=i)
        anom = 0.8 * anom + rng.normal(0, 0.03, (ny, nx))
        sic_by_date[d] = np.clip(climatology + anom, 0.0, 1.0)
    return {"sic_by_date": sic_by_date, "start": start, "n_days": n_days}


def test_fit_damped_tau_returns_reasonable_value():
    data = _make_synthetic_sic(n_days=400)
    sic_by_date = data["sic_by_date"]
    dates = sorted(sic_by_date.keys())
    train_dates = [d for d in dates if d.year <= 2006]

    clim = compute_climatology(sic_by_date, train_dates, use_trend=True)
    clim_ref = clim["clim_ref"]
    ocean = np.isfinite(clim_ref)
    viz_mask = build_viz_mask(clim_ref, ocean)

    tau, rmse = baselines.fit_damped_tau(
        sic_by_date, train_dates, clim["doy_to_mean"], 7, viz_mask,
    )
    assert tau > 0
    assert np.isfinite(tau)
    assert rmse >= 0


def test_fit_damped_tau_persistence_beats_climatology_when_anomaly_persistent():
    """On a highly persistent anomaly, tau should be large (persistence wins)."""
    rng = np.random.default_rng(1)
    ny, nx = 10, 10
    clim = np.full((ny, nx), 0.5)
    # Persistent anomaly that barely decays.
    anom = np.zeros((ny, nx))
    sic_by_date = {}
    start = date(2005, 1, 1)
    for i in range(100):
        d = start + timedelta(days=i)
        anom = 0.99 * anom + rng.normal(0, 0.01, (ny, nx))
        sic_by_date[d] = np.clip(clim + anom, 0.0, 1.0)

    train_dates = sorted(sic_by_date.keys())
    doy_to_mean = {(d.month, d.day): clim.copy() for d in train_dates}
    viz_mask = np.ones((ny, nx), dtype=bool)

    tau, _ = baselines.fit_damped_tau(
        sic_by_date, train_dates, doy_to_mean, 7, viz_mask,
        tau_bounds=(3.0, 1000.0),
    )
    # Highly persistent anomaly -> tau should be large (>20 days).
    assert tau > 20.0


def test_build_real_sic_dataset_structure():
    data = _make_synthetic_sic(n_days=400)
    sic_by_date = data["sic_by_date"]
    start = data["start"]
    dates = sorted(sic_by_date.keys())
    train_dates = [d for d in dates if d.year <= 2006]
    val_dates = [d for d in dates if d.year == 2007][:30]

    clim = compute_climatology(sic_by_date, train_dates, use_trend=True)
    clim_ref = clim["clim_ref"]
    ocean = np.isfinite(clim_ref)
    viz_mask = build_viz_mask(clim_ref, ocean)

    # Use the grid from the synthetic data.
    lat = np.linspace(-60, -85, clim_ref.shape[0])
    lon = np.linspace(-180, 180, clim_ref.shape[1])
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    sector_grid = np.zeros_like(clim_ref, dtype=np.int32)
    areas_grid = np.ones_like(clim_ref, dtype=np.float64)

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    ds = build_real_sic_dataset(
        sic_by_date, train_dates[:60], clim, taus,
        lat_grid, lon_grid, sector_grid, areas_grid,
        REAL_LEAD_DAYS,
        sample_viz_fraction=0.5,
        sample_other_fraction=0.0,
        rng_seed=42,
    )
    assert len(ds) > 0
    assert ds.X.shape[1] == len(FEATURE_NAMES_REAL)
    assert ds.y.shape[0] == ds.X.shape[0]
    assert ds.baseline.shape[0] == ds.X.shape[0]
    assert ds.truth.shape[0] == ds.X.shape[0]
    assert ds.month.shape[0] == ds.X.shape[0]
    assert len(ds.feature_names) == len(FEATURE_NAMES_REAL)
    # y is the residual (truth - baseline).
    np.testing.assert_allclose(ds.y, ds.truth - ds.baseline, rtol=1e-10, atol=1e-12)


def test_real_sic_forecaster_fit_predict():
    """Smoke test: train on synthetic, predict, check shapes and clipping."""
    data = _make_synthetic_sic(n_days=400)
    sic_by_date = data["sic_by_date"]
    dates = sorted(sic_by_date.keys())
    train_dates = [d for d in dates if d.year <= 2006]
    val_dates = [d for d in dates if d.year == 2007]

    clim = compute_climatology(sic_by_date, train_dates, use_trend=True)
    clim_ref = clim["clim_ref"]
    ocean = np.isfinite(clim_ref)
    viz_mask = build_viz_mask(clim_ref, ocean)

    lat = np.linspace(-60, -85, clim_ref.shape[0])
    lon = np.linspace(-180, 180, clim_ref.shape[1])
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    sector_grid = np.zeros_like(clim_ref, dtype=np.int32)
    areas_grid = np.ones_like(clim_ref, dtype=np.float64)

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    train_ds = build_real_sic_dataset(
        sic_by_date, train_dates[:60], clim, taus,
        lat_grid, lon_grid, sector_grid, areas_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=0.5, sample_other_fraction=0.0, rng_seed=42,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates[:20], clim, taus,
        lat_grid, lon_grid, sector_grid, areas_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=1.0, sample_other_fraction=0.0, rng_seed=43,
    )

    model = RealSICForecaster(leads=REAL_LEAD_DAYS, random_state=42)
    model.fit(train_ds, val_ds, taus)

    # Predict.
    preds = model.predict_full(val_ds)
    assert len(preds) == len(val_ds)
    assert np.all(preds >= 0.0) and np.all(preds <= 1.0)

    # Intervals.
    lo, hi = model.predict_interval(val_ds)
    assert np.all(lo >= 0.0) and np.all(hi <= 1.0)

    # Evaluate.
    metrics = model.evaluate(val_ds, n_boot=20)
    assert "overall" in metrics
    assert "per_lead" in metrics
    assert "promoted_leads" in metrics
    assert "coverage_90_ci" in metrics


def test_real_sic_forecaster_save_load(tmp_path):
    data = _make_synthetic_sic(n_days=200)
    sic_by_date = data["sic_by_date"]
    dates = sorted(sic_by_date.keys())
    train_dates = dates[:30]
    val_dates = dates[30:40]

    clim = compute_climatology(sic_by_date, train_dates, use_trend=True)
    clim_ref = clim["clim_ref"]
    ocean = np.isfinite(clim_ref)
    viz_mask = build_viz_mask(clim_ref, ocean)

    lat = np.linspace(-60, -85, clim_ref.shape[0])
    lon = np.linspace(-180, 180, clim_ref.shape[1])
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    sector_grid = np.zeros_like(clim_ref, dtype=np.int32)
    areas_grid = np.ones_like(clim_ref, dtype=np.float64)

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    train_ds = build_real_sic_dataset(
        sic_by_date, train_dates, clim, taus,
        lat_grid, lon_grid, sector_grid, areas_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=0.5, rng_seed=42,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates, clim, taus,
        lat_grid, lon_grid, sector_grid, areas_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=1.0, rng_seed=43,
    )

    model = RealSICForecaster(leads=REAL_LEAD_DAYS, random_state=42)
    model.fit(train_ds, val_ds, taus)

    path = tmp_path / "test_real_sic.joblib"
    model.save(path)
    assert path.exists()

    loaded = RealSICForecaster.load(path)
    preds_orig = model.predict_full(val_ds)
    preds_loaded = loaded.predict_full(val_ds)
    np.testing.assert_allclose(preds_orig, preds_loaded, rtol=1e-10)


def test_registry_has_real_sic_entry(tmp_path, monkeypatch):
    from src.ml import registry

    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    status = registry.ml_status()
    assert "real_sic_forecaster" in status["models"]
    entry = status["models"]["real_sic_forecaster"]
    assert entry["trained_on"] == "real"
    assert entry["status"] == "not trained"
    assert entry["artefact_present"] is False
    assert "caveat" in entry


def test_emergency_split_values():
    assert TRAIN_END_YEAR == 2019
    assert VAL_YEARS == (2020, 2021)
    assert TEST_YEARS == (2022, 2023, 2024)
    assert EMBARGO_DAYS == 14
    assert REAL_LEAD_DAYS == (3, 7, 14)
    assert len(FEATURE_NAMES_REAL) == 14


def test_compute_iiee_per_day_hand_computed():
    """Hand-computed IIEE on a tiny 4-cell grid, all on one day.

    Cells:
      0: pred=0.20 (>0.15), truth=0.10 (<=0.15) -> overestimated (false ice)
      1: pred=0.10 (<=0.15), truth=0.20 (>0.15) -> underestimated (missed ice)
      2: pred=0.20, truth=0.20 -> both ice, match
      3: pred=0.10, truth=0.10 -> both no ice, match
    Areas: [100, 200, 300, 400] km^2 -> total 1000, mismatching 300 -> 30%.
    """
    from src.ml.real_sic_forecaster import _compute_iiee_per_day

    pred = np.array([0.20, 0.10, 0.20, 0.10])
    truth = np.array([0.10, 0.20, 0.20, 0.10])
    areas = np.array([100.0, 200.0, 300.0, 400.0])
    dates = np.array([1000, 1000, 1000, 1000])  # all one day

    iiee = _compute_iiee_per_day(pred, truth, areas, dates)
    assert abs(iiee - 30.0) < 1e-9, f"expected 30.0, got {iiee}"


def test_compute_iiee_per_day_two_days():
    """IIEE per day then mean over days.

    Day 1000: cells 0,1 -> mismatching area 100+200=300, total 300 -> 100%
    Day 1001: cells 2,3 -> matching, mismatching 0, total 700 -> 0%
    Mean over days: (100 + 0) / 2 = 50%.
    """
    from src.ml.real_sic_forecaster import _compute_iiee_per_day

    pred = np.array([0.20, 0.10, 0.20, 0.10])
    truth = np.array([0.10, 0.20, 0.20, 0.10])
    areas = np.array([100.0, 200.0, 300.0, 400.0])
    dates = np.array([1000, 1000, 1001, 1001])

    iiee = _compute_iiee_per_day(pred, truth, areas, dates)
    assert abs(iiee - 50.0) < 1e-9, f"expected 50.0, got {iiee}"


def test_compute_iiee_per_day_nan_excluded():
    """NaN cells are excluded from IIEE."""
    from src.ml.real_sic_forecaster import _compute_iiee_per_day

    pred = np.array([0.20, np.nan, 0.20])
    truth = np.array([0.10, 0.20, np.nan])
    areas = np.array([100.0, 200.0, 300.0])
    dates = np.array([1000, 1000, 1000])

    iiee = _compute_iiee_per_day(pred, truth, areas, dates)
    # Only cell 0 is valid: pred=0.20>0.15, truth=0.10<=0.15 -> overestimated
    # mismatching area = 100, total = 100 -> 100%
    assert abs(iiee - 100.0) < 1e-9, f"expected 100.0, got {iiee}"


def test_compute_iiee_area_per_day():
    """Area-based IIEE: mismatched area in million km2, per day then averaged.

    4 cells, areas [100, 200, 300, 400] km2, all one day.
    Cells 0,1 mismatch: over (100) + under (200) = 300 km2 mismatched.
    Total VIZ area = 1000 km2. IIEE pct = 30%.
    Mismatched area = 300 km2 = 300 / 1e6 million km2 = 0.0003 Mkm2.
    """
    from src.ml.real_sic_forecaster import _compute_iiee_area_per_day

    pred = np.array([0.20, 0.10, 0.20, 0.10])
    truth = np.array([0.10, 0.20, 0.20, 0.10])
    areas = np.array([100.0, 200.0, 300.0, 400.0])  # km2
    areas_m2 = areas * 1e6  # convert to m2
    dates = np.array([1000, 1000, 1000, 1000])

    result = _compute_iiee_area_per_day(pred, truth, areas_m2, dates)
    assert abs(result["iiee_pct"] - 30.0) < 1e-9
    assert abs(result["mismatched_area_mkm2_per_day"] - 0.0003) < 1e-9
    assert abs(result["viz_area_mkm2_per_day"] - 0.001) < 1e-9
    assert int(result["mean_mismatched_cells"]) == 2
    assert int(result["mean_viz_cells"]) == 4
    assert abs(result["mean_cell_area_km2"] - 250.0) < 1e-9


def test_iiee_sanity_check_passes():
    """Sanity check passes for physically plausible inputs.

    Uses 1000 cells (each 625 km2 = 25x25 km) so the daily VIZ extent
    (~0.625 Mkm2) is above the 0.1 Mkm2 plausibility floor.
    """
    from src.ml.real_sic_forecaster import _iiee_sanity_check

    n = 1000
    cell_area_km2 = 625.0
    areas_m2 = np.full(n, cell_area_km2 * 1e6)
    rng = np.random.default_rng(42)
    pred = np.clip(rng.uniform(0, 1, n), 0.01, 0.99)
    truth = np.clip(rng.uniform(0, 1, n), 0.01, 0.99)
    dates = np.array([1000] * n)

    result = _iiee_sanity_check(pred, truth, areas_m2, dates)
    assert result["passed"] is True
    assert result["mean_cell_area_km2"] == 625.0
    assert result["mean_mismatched_cells"] > 0


def test_iiee_sanity_check_fails_bad_cell_area():
    """Sanity check fails when cell area is far from nominal."""
    from src.ml.real_sic_forecaster import _iiee_sanity_check

    # Cell area of 10000 km2 is not plausible for 25km NSIDC grid
    areas_m2 = np.full(5, 10000.0 * 1e6)
    pred = np.array([0.20, 0.10, 0.30, 0.05, 0.15])
    truth = np.array([0.10, 0.20, 0.30, 0.05, 0.20])
    dates = np.array([1000] * 5)

    result = _iiee_sanity_check(pred, truth, areas_m2, dates)
    assert result["passed"] is False
    assert result["checks"]["cell_area_plausible"] is False


def test_block_bootstrap_ci_includes_zero_when_improvement_on_few_dates():
    """Block bootstrap CI correctly includes zero when improvement exists on only a few dates.

    Data: model beats baseline by a fixed delta on just 3 of 30 dates (10%).
    Pooled-cell bootstrap would treat all 3000 cell-days as independent → narrow CI
    that wrongly excludes zero. Block bootstrap (14-day blocks, ~3 blocks) resamples
    whole dates → wider CI that correctly includes zero because most bootstrap
    samples miss some or all of the good dates.
    """
    from src.ml.real_sic_forecaster import _compute_rmse_diff_ci

    rng = np.random.default_rng(42)
    n_dates = 30
    n_cells = 100

    # Baseline: random SIC values per cell per date.
    baseline = rng.uniform(0.1, 0.9, (n_dates, n_cells))

    # Model: same as baseline on most dates, slightly better on just 3 dates.
    model = baseline.copy()
    good_dates = [0, 10, 20]  # only 3 out of 30 dates
    for d in good_dates:
        model[d] = baseline[d] - 0.02  # model is 0.02 better on these dates

    # Date ordinals: one per date, repeated for each cell.
    date_ord = np.repeat(np.arange(n_dates), n_cells)

    # Mask: all cells valid.
    mask = np.ones(n_dates * n_cells, dtype=bool)

    pred = model.ravel()
    truth = baseline.ravel()  # truth = baseline (no real improvement)
    base = baseline.ravel()

    # Block bootstrap CI with 14-day blocks (~3 blocks for 30 dates).
    model_rmse, baseline_rmse, ci_lo, ci_hi, n_blocks, block_len = _compute_rmse_diff_ci(
        pred, truth, base, date_ord, mask, n_boot=2000, seed=42, block_days=14,
    )

    # With only 3 good dates out of 30, block CI should include zero (ci_lo <= 0 <= ci_hi).
    assert ci_lo <= 0.0 <= ci_hi, (
        f"Block CI should include zero, got [{ci_lo}, {ci_hi}], "
        f"n_blocks={n_blocks}, block_len={block_len}"
    )
    assert n_blocks >= 2, f"Expected at least 2 date blocks, got {n_blocks}"
    assert block_len == 14


def test_block_bootstrap_ci_excludes_zero_when_improvement_on_most_dates():
    """Block bootstrap CI excludes zero when improvement exists on most dates.

    Sanity check: when model is consistently better than baseline on most dates,
    both pooled and block CI should exclude zero.
    """
    from src.ml.real_sic_forecaster import _compute_rmse_diff_ci

    rng = np.random.default_rng(7)
    n_dates = 30
    n_cells = 100

    baseline = rng.uniform(0.1, 0.9, (n_dates, n_cells))
    # Model is consistently closer to truth than baseline.
    truth = baseline + 0.06
    model = baseline + 0.03  # model is 0.03 closer to truth than baseline

    date_ord = np.repeat(np.arange(n_dates), n_cells)
    mask = np.ones(n_dates * n_cells, dtype=bool)

    pred = model.ravel()
    truth_r = truth.ravel()
    base = baseline.ravel()

    model_rmse, baseline_rmse, ci_lo, ci_hi, n_blocks, block_len = _compute_rmse_diff_ci(
        pred, truth_r, base, date_ord, mask, n_boot=2000, seed=7, block_days=14,
    )

    # Model is consistently better → CI should exclude zero (ci_hi < 0).
    assert ci_hi < 0.0, (
        f"Block CI should exclude zero (ci_hi < 0), got [{ci_lo}, {ci_hi}]"
    )
    assert model_rmse < baseline_rmse
