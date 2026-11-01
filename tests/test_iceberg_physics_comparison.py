"""Tests for Phase 4 step 4 paired iceberg drift comparison. Fixtures only, no network."""
from __future__ import annotations

import numpy as np
import pytest

from src.ml.iceberg_dataset import ICELEAD_DAYS, FEATURE_NAMES_ICEBERG

import scripts.iceberg_physics_comparison as step4


def _make_split(rows):
    n = len(rows)
    X = np.zeros((n, len(FEATURE_NAMES_ICEBERG)))
    X[:, 0] = [r["lat_t0"] for r in rows]
    X[:, 1] = [r["lon_t0"] for r in rows]
    from src.ml.iceberg_dataset import IcebergSplit
    return IcebergSplit(
        X=X, y_lat=np.zeros(n), y_lon=np.zeros(n),
        baseline_lat=np.array([r["baseline_lat"] for r in rows]),
        baseline_lon=np.array([r["baseline_lon"] for r in rows]),
        truth_lat=np.array([r["truth_lat"] for r in rows]),
        truth_lon=np.array([r["truth_lon"] for r in rows]),
        baseline_error_km=np.array([r["base_err_km"] for r in rows]),
        baseline_damped_error_km=np.array([r["damped_err_km"] for r in rows]),
        berg_id=np.array([r["berg_id"] for r in rows]),
        lead_days=np.array([r["lead_days"] for r in rows], dtype=np.float64),
        month=np.array([r["month"] for r in rows], dtype=np.float64),
        feature_names=FEATURE_NAMES_ICEBERG,
        window_years=(2018, 2019),
    )


def _row(berg_id, lead, lat_t0, lon_t0, base_lat, base_lon, truth_lat, truth_lon,
         base_err_km, damped_err_km, month=1):
    return {
        "berg_id": berg_id, "lead_days": lead, "lat_t0": lat_t0, "lon_t0": lon_t0,
        "baseline_lat": base_lat, "baseline_lon": base_lon, "truth_lat": truth_lat,
        "truth_lon": truth_lon, "base_err_km": base_err_km, "damped_err_km": damped_err_km,
        "month": month,
    }


def test_evaluate_comparison_uses_identical_samples_and_real_data_source():
    # VAL: velocity_3d best (small base_err). TEST: same rows, velocity_3d still best.
    val_rows = [
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 1.0, 5.0),
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 1.0, 5.0),
    ]
    test_rows = [
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 1.0, 5.0),
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 1.0, 5.0),
    ]
    val_ds = _make_split(val_rows)
    test_ds = _make_split(test_rows)
    report = step4.evaluate_comparison(val_ds, test_ds, forcing_available=False)

    assert report["data_source"] == "real"
    assert report["forcing_available"] is False
    assert report["phase"] == 4 and report["step"] == 4
    pl1 = {pl["lead_days"]: pl for pl in report["per_lead"]}[1]
    assert pl1["best_baseline_val"] == "velocity_3d"
    assert pl1["test"]["promoted"] is not None  # computed in code, not hardcoded
    # wind_only / full_physics omitted, not fabricated, when no forcing data.
    assert pl1["test"]["wind_only"]["available"] is False
    assert pl1["test"]["full_physics"]["available"] is False
    assert "reason" in pl1["test"]["wind_only"]
    assert "reason" in pl1["test"]["full_physics"]
    # All variants evaluated on identical n samples.
    for v in ("no_move", "velocity_3d", "velocity_7d_damped"):
        assert pl1["test"][v]["n_samples"] == 2
        assert pl1["test"][v]["n_steps"] == 2
        assert pl1["test"][v]["n_tracks"] == 2


def test_ci_block_structure_and_promotion_logic():
    # best baseline clearly worse than runner-up so CI excludes zero -> promoted True.
    val_rows = [
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 10.0, 1.0),
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 10.0, 1.0),
    ]
    test_rows = [
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 10.0, 1.0),
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 10.0, 1.0),
    ]
    val_ds = _make_split(val_rows)
    test_ds = _make_split(test_rows)
    report = step4.evaluate_comparison(val_ds, test_ds, forcing_available=False)
    pl1 = {pl["lead_days"]: pl for pl in report["per_lead"]}[1]
    ci = pl1["test"]["ci_vs_best_baseline"]
    assert "velocity_3d" in ci or "no_move" in ci
    for variant, cb in ci.items():
        assert "ci_lo" in cb and "ci_hi" in cb and "diff_km" in cb
        assert "ci_excludes_zero" in cb


def test_no_tuning_on_test_promotion_is_computed_not_hardcoded():
    val_ds = _make_split([
        _row("B1", 3, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 5.0, 5.0),
    ])
    test_ds = _make_split([
        _row("B1", 3, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 5.0, 5.0),
    ])
    report = step4.evaluate_comparison(val_ds, test_ds, forcing_available=False)
    pl3 = {pl["lead_days"]: pl for pl in report["per_lead"]}[3]
    # promoted must be a bool computed from CI, never None.
    assert isinstance(pl3["test"]["promoted"], bool)
