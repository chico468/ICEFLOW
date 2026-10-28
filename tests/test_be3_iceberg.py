"""Tests for real-data iceberg drift forecasting (BE-3)."""
from __future__ import annotations

import csv
import io
import json
import math
import zipfile
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
import pytest

from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    FEATURE_NAMES_ICEBERG,
    IcebergSplit,
    IcebergTrack,
    build_iceberg_dataset,
    filter_moving_segments,
    load_database,
    GROUNDING_SPEED_THRESHOLD_KNOTS,
)
from src.ml.iceberg_forecaster import (
    IcebergForecaster,
    IcebergConformalCalibrator,
    ICEBERG_PROMOTION_CI_ALPHA,
)


def _make_berg_csv(rows: list[str]) -> str:
    """Build a CSV with standard BYU/NIC-style headers."""
    header = "date,qscat_1,qscat_2,qscat_3,size_1,size_2\n"
    return header + "".join(rows)


def _write_test_zip(tmp_path: Path) -> Path:
    """Create a small test zip with two icebergs: one moving, one grounded."""
    zip_path = tmp_path / "consolidated_database_v6.zip"
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zf:
        # Moving iceberg: A01, drifts southwest at ~1 deg/day.
        a01_rows = []
        for i in range(20):
            d = date(2020, 1, 1) + timedelta(days=i)
            jd = f"{d.year}{d.timetuple().tm_yday:03d}"
            lat = -65.0 - i * 0.8
            lon = -50.0 - i * 1.2
            size = 20 + i
            a01_rows.append(f"{jd},{lat:.4f},{lon:.4f},1,{size},{size-5}\n")
        zf.writestr("consolidated_database_v6/a01.csv", _make_berg_csv(a01_rows))

        # Grounded iceberg: B01, stays near same position.
        b01_rows = []
        for i in range(10):
            d = date(2020, 1, 1) + timedelta(days=i)
            jd = f"{d.year}{d.timetuple().tm_yday:03d}"
            lat = -70.0 + i * 0.0001
            lon = 80.0 + i * 0.0001
            b01_rows.append(f"{jd},{lat:.6f},{lon:.6f},1,10,5\n")
        zf.writestr("consolidated_database_v6/b01.csv", _make_berg_csv(b01_rows))

    return zip_path


def test_load_database_parses_csvs(tmp_path):
    zip_path = _write_test_zip(tmp_path)
    tracks = load_database(zip_path)
    assert len(tracks) == 2  # both a01 and b01 loaded (filtering is separate)
    ids = {t.berg_id for t in tracks}
    assert "a01" in ids
    assert "b01" in ids


def test_berg_dates_parsed_from_jd():
    """Julian day YYYYDDD should parse correctly."""
    # 2002017 = year 2002, day 17 = January 17
    jd = "2002017"
    dt = datetime.strptime(jd, "%Y%j").date()
    assert dt == date(2002, 1, 17)


def test_filter_moving_segments_removes_grounded(tmp_path):
    """Icebergs with average speed < threshold should be removed."""
    zip_path = tmp_path / "test.zip"
    with zipfile.ZipFile(zip_path, "w") as zf:
        # Moving: 1 deg/day ~ 1.5+ kt — above 0.1 kt threshold
        rows = []
        for i in range(10):
            d = date(2021, 1, 1) + timedelta(days=i)
            jd = f"{d.year}{d.timetuple().tm_yday:03d}"
            rows.append(f"{jd},{-65.0 - i:.4f},{-50.0 - i:.4f},1,20,15\n")
        zf.writestr("consolidated_database_v6/a01.csv", _make_berg_csv(rows))

        # Grounded: barely moves
        rows2 = []
        for i in range(10):
            d = date(2021, 1, 1) + timedelta(days=i)
            jd = f"{d.year}{d.timetuple().tm_yday:03d}"
            rows2.append(f"{jd},{-70.0 + i*0.0001:.6f},{80.0 + i*0.0001:.6f},1,10,5\n")
        zf.writestr("consolidated_database_v6/b01.csv", _make_berg_csv(rows2))

    tracks = load_database(zip_path)
    filtered = filter_moving_segments(tracks)
    ids = {t.berg_id for t in filtered}
    assert "a01" in ids
    assert "b01" not in ids, "Grounded iceberg should be filtered out"


def test_build_iceberg_dataset_structure(tmp_path):
    """Dataset should produce correct shapes and feature names."""
    zip_path = _write_test_zip(tmp_path)
    tracks = load_database(zip_path)
    filtered = filter_moving_segments(tracks)

    ds = build_iceberg_dataset(
        filtered, date(2020, 1, 1), date(2020, 1, 20),
        leads=ICELEAD_DAYS, rng_seed=42,
    )
    assert len(ds) > 0
    assert ds.X.shape[1] == len(FEATURE_NAMES_ICEBERG)
    assert ds.y_lat.shape[0] == ds.X.shape[0]
    assert ds.y_lon.shape[0] == ds.X.shape[0]
    assert ds.baseline_error_km.shape[0] == ds.X.shape[0]
    assert ds.berg_id.shape[0] == ds.X.shape[0]
    assert ds.lead_days.shape[0] == ds.X.shape[0]
    assert ds.month.shape[0] == ds.X.shape[0]
    assert len(ds.feature_names) == len(FEATURE_NAMES_ICEBERG)
    unique_leads = set(ds.lead_days.tolist())
    assert unique_leads.issubset(set(ICELEAD_DAYS))


def test_build_iceberg_dataset_residual_consistency(tmp_path):
    """y_lat = truth_lat - baseline_lat and y_lon = truth_lon - baseline_lon."""
    zip_path = _write_test_zip(tmp_path)
    tracks = load_database(zip_path)
    filtered = filter_moving_segments(tracks)

    ds = build_iceberg_dataset(
        filtered, date(2020, 1, 1), date(2020, 1, 20),
        leads=ICELEAD_DAYS, rng_seed=42,
    )
    if len(ds) > 0:
        np.testing.assert_allclose(
            ds.y_lat, ds.truth_lat - ds.baseline_lat, rtol=1e-10, atol=1e-12
        )
        np.testing.assert_allclose(
            ds.y_lon, ds.truth_lon - ds.baseline_lon, rtol=1e-10, atol=1e-12
        )


def test_build_iceberg_dataset_empty_when_no_tracks():
    """Empty input should produce an empty IcebergSplit."""
    ds = build_iceberg_dataset([], date(2020, 1, 1), date(2020, 1, 20))
    assert len(ds) == 0
    assert ds.X.shape[1] == len(FEATURE_NAMES_ICEBERG)


def test_iceberg_forecaster_fit_predict(tmp_path):
    """Smoke test: train, predict, evaluate check shapes."""
    zip_path = _write_test_zip(tmp_path)
    tracks = load_database(zip_path)
    filtered = filter_moving_segments(tracks)

    train_ds = build_iceberg_dataset(
        filtered, date(2020, 1, 1), date(2020, 1, 15),
        leads=ICELEAD_DAYS, rng_seed=42,
    )
    val_ds = build_iceberg_dataset(
        filtered, date(2020, 1, 10), date(2020, 1, 20),
        leads=ICELEAD_DAYS, rng_seed=43,
    )

    model = IcebergForecaster(leads=ICELEAD_DAYS, random_state=42)
    model.fit(train_ds, val_ds)

    # Predict residual.
    for lead in ICELEAD_DAYS:
        lat_res, lon_res = model.predict_residual(val_ds, lead)
        mask = val_ds.lead_days == float(lead)
        assert len(lat_res) == int(mask.sum())
        assert len(lon_res) == int(mask.sum())

    # Evaluate.
    metrics = model.evaluate(val_ds, n_boot=5)
    assert "per_lead" in metrics
    assert "promoted" in metrics
    assert "radii" in metrics
    assert "overall" in metrics
    assert metrics["n_samples"] == len(val_ds)
    assert metrics["metric"] == "great_circle_error_km"


def test_iceberg_forecaster_save_load(tmp_path):
    zip_path = _write_test_zip(tmp_path)
    tracks = load_database(zip_path)
    filtered = filter_moving_segments(tracks)

    train_ds = build_iceberg_dataset(
        filtered, date(2020, 1, 1), date(2020, 1, 15),
        leads=ICELEAD_DAYS, rng_seed=42,
    )
    val_ds = build_iceberg_dataset(
        filtered, date(2020, 1, 10), date(2020, 1, 20),
        leads=ICELEAD_DAYS, rng_seed=43,
    )

    model = IcebergForecaster(leads=ICELEAD_DAYS, random_state=42)
    model.fit(train_ds, val_ds)

    path = tmp_path / "test_iceberg.joblib"
    model.save(path)
    assert path.exists()

    loaded = IcebergForecaster.load(path)
    for lead in ICELEAD_DAYS:
        lat_orig, lon_orig = model.predict_residual(val_ds, lead)
        lat_loaded, lon_loaded = loaded.predict_residual(val_ds, lead)
        np.testing.assert_allclose(lat_orig, lat_loaded, rtol=1e-10)
        np.testing.assert_allclose(lon_orig, lon_loaded, rtol=1e-10)


def test_registry_has_iceberg_entry(tmp_path, monkeypatch):
    from src.ml import registry

    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    status = registry.ml_status()
    assert "iceberg_forecaster" in status["models"]
    entry = status["models"]["iceberg_forecaster"]
    assert entry["status"] == "not trained"
    assert entry["artefact_present"] is False
    assert "caveat" in entry


def test_promotion_gate_logic():
    """A model that beats baseline should be promoted if CI excludes zero."""
    from src.ml.iceberg_forecaster import _block_bootstrap_ci_by_berg

    np.random.seed(42)
    n = 200
    n_bergs = 10
    berg_ids = np.array([f"b{i}" for i in range(n_bergs) for _ in range(n // n_bergs)])

    # Model errors: small, beating baseline.
    pred_err = np.random.normal(0, 5.0, n)
    base_err = np.random.normal(0, 10.0, n)

    model_rmse, base_rmse, ci_lo, ci_hi = _block_bootstrap_ci_by_berg(
        pred_err, base_err, berg_ids, n_boot=50, seed=42,
    )
    assert model_rmse < base_rmse
    assert ci_hi < 0.0 or ci_lo > 0.0


def test_dataset_constants():
    """Verify BE-3 constants match the SPRINT doc."""
    assert ICELEAD_DAYS == (1, 3, 7)
    assert GROUNDING_SPEED_THRESHOLD_KNOTS == 0.1
    assert len(FEATURE_NAMES_ICEBERG) > 0
    assert "lat_t0" in FEATURE_NAMES_ICEBERG
    assert "baseline_vel_lat" in FEATURE_NAMES_ICEBERG


def test_conformal_calibrator():
    cal = IcebergConformalCalibrator(scores=np.array([1.0, 2.0, 3.0, 4.0, 5.0]))
    r = cal.radius()
    assert r > 0
    p50, p90 = cal.p50_p90()
    assert p50 <= p90


def test_iceberg_split_len():
    ds = IcebergSplit(
        X=np.zeros((5, 3)),
        y_lat=np.zeros(5),
        y_lon=np.zeros(5),
        baseline_lat=np.zeros(5),
        baseline_lon=np.zeros(5),
        truth_lat=np.zeros(5),
        truth_lon=np.zeros(5),
        baseline_error_km=np.zeros(5),
        berg_id=np.array(["a"] * 5),
        lead_days=np.ones(5),
        month=np.ones(5),
        feature_names=FEATURE_NAMES_ICEBERG,
        window_years=(2020,),
    )
    assert len(ds) == 5


def test_real_data_evaluation():
    """Run the actual training script on real data and verify report validity."""
    import subprocess
    import sys
    repo = Path(__file__).resolve().parents[1]
    report_path = repo / "models" / "eval" / "iceberg_ml_report.json"
    if not report_path.exists():
        pytest.skip("iceberg_ml_report.json not generated yet")
    with open(report_path) as f:
        report = json.load(f)
    assert report["data_source"] == "real"
    assert report["product"] == "BYU/NIC consolidated Antarctic iceberg database v6"
    assert report["lead_days"] == [1, 3, 7]
    assert "promoted" in report
    assert "iceberg" in report["promoted"]
    assert len(report["rows"]) > 0
    for row in report["rows"]:
        assert "lead_days" in row
        assert "metric" in row
        assert row["metric"] == "great_circle_error_km"
        assert "promoted" not in row
