"""Tests for Phase 4 PART 1 tracks-only iceberg physics baseline (no forcing, no ML).

Uses fixtures only; no network access.
"""
from __future__ import annotations

import json
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from src.ml.iceberg_dataset import ICELEAD_DAYS, IcebergSplit, FEATURE_NAMES_ICEBERG

import scripts.iceberg_physics_part1 as part1


def _make_split(rows):
    """Build an IcebergSplit from a list of dict rows with per-lead data."""
    n = len(rows)
    X = np.zeros((n, len(FEATURE_NAMES_ICEBERG)))
    X[:, 0] = [r["lat_t0"] for r in rows]  # lat_t0
    X[:, 1] = [r["lon_t0"] for r in rows]  # lon_t0
    return IcebergSplit(
        X=X,
        y_lat=np.zeros(n),
        y_lon=np.zeros(n),
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
        "berg_id": berg_id,
        "lead_days": lead,
        "lat_t0": lat_t0,
        "lon_t0": lon_t0,
        "baseline_lat": base_lat,
        "baseline_lon": base_lon,
        "truth_lat": truth_lat,
        "truth_lon": truth_lon,
        "base_err_km": base_err_km,
        "damped_err_km": damped_err_km,
        "month": month,
    }


def test_evaluate_part1_val_calibrates_radii_and_test_coverage_is_empirical():
    # VAL (2018): one berg, lead 1. no_move error = haversine(t0, truth); set truth far
    # from t0 so no_move error is large and known; velocity baselines even larger so
    # no_move wins on VAL.
    val_rows = [
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.05, -50.05, 50.0, 60.0),
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.10, -50.10, 50.0, 60.0),
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.20, -50.20, 50.0, 60.0),
    ]
    # TEST (2019): one berg, lead 1, different errors than VAL.
    test_rows = [
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.02, -50.02, 50.0, 60.0),
        _row("B2", 1, -65.0, -50.0, -65.0, -50.0, -65.50, -50.50, 50.0, 60.0),
    ]
    val_ds = _make_split(val_rows)
    test_ds = _make_split(test_rows)

    report = part1.evaluate_part1(val_ds, test_ds)

    assert report["data_source"] == "real"
    assert report["leads"] == list(ICELEAD_DAYS)
    per_lead = {pl["lead_days"]: pl for pl in report["per_lead"]}
    assert set(per_lead.keys()) == set(ICELEAD_DAYS)

    pl1 = per_lead[1]
    assert pl1["best_baseline_val"] == "no_move"
    # cal p50/p90 come from VAL residuals.
    assert pl1["cal_p50_km"] > 0
    assert pl1["cal_p90_km"] >= pl1["cal_p50_km"]
    # TEST empirical coverage is data-derived, not the 0.9 target.
    assert "empirical_coverage_p50" in pl1["test"]
    assert "empirical_coverage_p90" in pl1["test"]
    cov = pl1["test"]["empirical_coverage_p90"]
    assert 0.0 <= cov <= 1.0
    assert cov != 0.9, "coverage must be empirical, not hardcoded to calibration target"
    assert pl1["test"]["n_icebergs"] >= 1


def test_evaluate_part1_picks_best_baseline_by_val_median():
    # velocity_7d_damped clearly better on VAL for lead 3: no_move large (truth far from
    # t0), base large, damped tiny.
    val_rows = [
        _row("B1", 3, -65.0, -50.0, -65.0, -50.0, -66.0, -51.0, 100.0, 1.0),
        _row("B2", 3, -65.0, -50.0, -65.0, -50.0, -66.0, -51.0, 100.0, 1.0),
    ]
    test_rows = [
        _row("B1", 3, -65.0, -50.0, -65.0, -50.0, -66.0, -51.0, 100.0, 1.0),
    ]
    val_ds = _make_split(val_rows)
    test_ds = _make_split(test_rows)
    report = part1.evaluate_part1(val_ds, test_ds)
    pl3 = {pl["lead_days"]: pl for pl in report["per_lead"]}[3]
    assert pl3["best_baseline_val"] == "velocity_7d_damped"
    assert pl3["test"]["baseline"] == "velocity_7d_damped"


def test_main_runs_on_fixture_no_network(tmp_path, monkeypatch):
    """End-to-end run using the fixture zip; no network."""
    fixture = Path("tests/fixtures/observed_bergs/byu_small.zip")
    assert fixture.is_file()
    out_path = tmp_path / "iceberg_part1_report.json"
    monkeypatch.setattr(part1, "DEFAULT_DATABASE_PATH", fixture)
    monkeypatch.setattr(part1, "REPORT_PATH", out_path)
    # No network: the DB path is a local fixture file.
    code = part1.main()
    assert code == 0
    assert out_path.is_file()
    report = json.loads(out_path.read_text(encoding="utf-8"))
    assert report["data_source"] == "real"
    assert report["phase"] == 4
    assert report["part"] == 1
    assert len(report["per_lead"]) == len(ICELEAD_DAYS)
    for pl in report["per_lead"]:
        assert pl["lead_days"] in ICELEAD_DAYS
        assert "test" in pl and "val" in pl
        assert "empirical_coverage_p50" in pl["test"]
        assert "empirical_coverage_p90" in pl["test"]


def test_baseline_errors_no_move_matches_haversine():
    ds = _make_split([
        _row("B1", 1, -65.0, -50.0, -65.0, -50.0, -65.0, -51.0, 99.0, 1.0),
    ])
    errs = part1._baseline_errors(ds, "no_move")
    # no_move: predict t0 position -> error vs truth (one degree lon at -65 lat).
    from src.core.geo import haversine_km
    expected = haversine_km(-65.0, -50.0, -65.0, -51.0)
    assert np.isclose(errs[0], expected, atol=1e-6)
