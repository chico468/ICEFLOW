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

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    ds = build_real_sic_dataset(
        sic_by_date, train_dates[:60], clim, taus,
        lat_grid, lon_grid, sector_grid,
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

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    train_ds = build_real_sic_dataset(
        sic_by_date, train_dates[:60], clim, taus,
        lat_grid, lon_grid, sector_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=0.5, sample_other_fraction=0.0, rng_seed=42,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates[:20], clim, taus,
        lat_grid, lon_grid, sector_grid, REAL_LEAD_DAYS,
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

    taus = {3: 10.0, 7: 30.0, 14: 60.0}
    train_ds = build_real_sic_dataset(
        sic_by_date, train_dates, clim, taus,
        lat_grid, lon_grid, sector_grid, REAL_LEAD_DAYS,
        sample_viz_fraction=0.5, rng_seed=42,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates, clim, taus,
        lat_grid, lon_grid, sector_grid, REAL_LEAD_DAYS,
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
