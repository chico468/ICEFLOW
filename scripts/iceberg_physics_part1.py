#!/usr/bin/env python
"""
Phase 4 PART 1 — tracks-only iceberg physics baseline evaluation (no forcing, no ML).

Uses real BYU/NIC v6 observations only. No ERA5, no GLORYS, no ML model, no training.

For each lead (1, 3, 7 days) computes the three no-forcing baselines on the observed tracks:

  (a) no movement        — position held fixed at t0
  (b) 3-day velocity     — constant velocity from the last 3 days
  (c) 7-day damped velocity — constant velocity from the last 7 days, damped 0.5x

VAL (2018): select the best baseline per lead (lowest median great-circle error),
then calibrate p50/p90 uncertainty radii on the VAL residuals of that best baseline.

TEST (2019-2022): report median and p90 km, n samples and n icebergs, plus the
empirical coverage — the fraction of TEST truth positions falling within the
calibrated p50 / p90 radii. Coverage is computed from the TEST data, never
hardcoded to the calibration target.

Writes models/eval/iceberg_part1_report.json with data_source "real".
"""
from __future__ import annotations

import json
import math
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.geo import haversine_km
from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    IcebergTrack,
    build_iceberg_dataset,
    filter_moving_segments,
    load_database,
)

TRAIN_START_YEAR = 2005
TRAIN_END_YEAR = 2017
VAL_YEAR = 2018
TEST_START_YEAR = 2019
TEST_END_YEAR = 2022
DAMPING = 0.5

REPORT_PATH = REPO_ROOT / "models" / "eval" / "iceberg_part1_report.json"


def _date_range_inclusive(start: date, end: date) -> List[date]:
    out: List[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += __import__("datetime").timedelta(days=1)
    return out


def _vectorized_haversine_km(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray,
) -> np.ndarray:
    """Vectorised great-circle distance in km."""
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return 6371.0088 * c


def _baseline_errors(ds, baseline: str) -> np.ndarray:
    """Great-circle error (km) for one no-forcing baseline on a split.

    ``baseline`` is one of "no_move", "velocity_3d", "velocity_7d_damped".
    """
    if baseline == "no_move":
        return _vectorized_haversine_km(
            ds.X[:, 0], ds.X[:, 1], ds.truth_lat, ds.truth_lon,
        )
    if baseline == "velocity_3d":
        return ds.baseline_error_km.copy()
    if baseline == "velocity_7d_damped":
        return ds.baseline_damped_error_km.copy()
    raise ValueError(f"unknown baseline {baseline!r}")


BASELINES = ("no_move", "velocity_3d", "velocity_7d_damped")
BASELINE_LABELS = {
    "no_move": "no movement",
    "velocity_3d": "3-day constant velocity",
    "velocity_7d_damped": "7-day damped constant velocity",
}

DEFAULT_DATABASE_PATH = REPO_ROOT / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"


def _percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if len(values) > 0 else float("nan")


def evaluate_part1(val_ds, test_ds) -> Dict[str, Any]:
    """Evaluate the no-forcing baselines on VAL and TEST.

    Returns a report dict ready to serialise to JSON.
    """
    per_lead: List[Dict[str, Any]] = []
    for lead in ICELEAD_DAYS:
        lead_entry: Dict[str, Any] = {"lead_days": lead}

        # --- VAL: baseline comparison and radius calibration -----------------
        val_errors: Dict[str, np.ndarray] = {}
        val_summary: Dict[str, Any] = {}
        for baseline in BASELINES:
            errs = _baseline_errors(val_ds, baseline)
            mask = val_ds.lead_days == float(lead)
            errs = errs[mask]
            abs_errs = np.abs(errs)
            val_summary[baseline] = {
                "median_km": _percentile(abs_errs, 50),
                "p90_km": _percentile(abs_errs, 90),
                "n_samples": int(len(abs_errs)),
            }
        lead_entry["val"] = val_summary

        best_baseline = min(
            BASELINES,
            key=lambda b: val_summary[b]["median_km"],
        )
        lead_entry["best_baseline_val"] = best_baseline

        val_best_errs = _baseline_errors(val_ds, best_baseline)
        val_best_mask = val_ds.lead_days == float(lead)
        val_best_errs = val_best_errs[val_best_mask]
        val_abs = np.abs(val_best_errs)
        cal_p50 = _percentile(val_abs, 50)
        cal_p90 = _percentile(val_abs, 90)
        lead_entry["cal_p50_km"] = cal_p50
        lead_entry["cal_p90_km"] = cal_p90

        # --- TEST: median, p90, coverage with the VAL-selected baseline ------
        test_errs = _baseline_errors(test_ds, best_baseline)
        test_mask = test_ds.lead_days == float(lead)
        test_errs = test_errs[test_mask]
        test_abs = np.abs(test_errs)
        test_median = _percentile(test_abs, 50)
        test_p90 = _percentile(test_abs, 90)

        coverage_p50 = float(np.mean(test_abs <= cal_p50)) if len(test_abs) > 0 else float("nan")
        coverage_p90 = float(np.mean(test_abs <= cal_p90)) if len(test_abs) > 0 else float("nan")

        berg_ids = test_ds.berg_id[test_mask]
        lead_entry["test"] = {
            "baseline": best_baseline,
            "baseline_label": BASELINE_LABELS[best_baseline],
            "median_km": test_median,
            "p90_km": test_p90,
            "n_samples": int(len(test_abs)),
            "n_icebergs": int(len(np.unique(berg_ids))) if len(berg_ids) > 0 else 0,
            "empirical_coverage_p50": coverage_p50,
            "empirical_coverage_p90": coverage_p90,
            "cal_p50_km": cal_p50,
            "cal_p90_km": cal_p90,
        }
        per_lead.append(lead_entry)

    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "phase": 4,
        "part": 1,
        "name": "tracks-only iceberg physics baseline (no forcing, no ML)",
        "data_source": "real",
        "product": "BYU/NIC consolidated Antarctic iceberg database v6",
        "train_start_year": TRAIN_START_YEAR,
        "train_end_year": TRAIN_END_YEAR,
        "val_year": VAL_YEAR,
        "test_start_year": TEST_START_YEAR,
        "test_end_year": TEST_END_YEAR,
        "leads": list(ICELEAD_DAYS),
        "baselines": [{"key": b, "label": BASELINE_LABELS[b]} for b in BASELINES],
        "note": (
            "No forcing model, no ERA5, no GLORYS, no ML. Baselines are computed directly from "
            "the observed BYU/NIC tracks. Radii p50/p90 calibrated on VAL (2018) residuals of the "
            "best baseline per lead; empirical coverage measured on TEST (2019-2022)."
        ),
        "per_lead": per_lead,
    }


def main() -> int:
    db_path = DEFAULT_DATABASE_PATH
    if not db_path.is_file():
        print(f"ERROR: Iceberg database not found at {db_path}", file=sys.stderr)
        return 1

    print("=" * 92)
    print("PHASE 4 PART 1 — tracks-only iceberg physics baseline (no forcing, no ML)")
    print("=" * 92)
    print()

    t0 = time.perf_counter()
    tracks = load_database(db_path)
    print(f"Loaded {len(tracks)} raw iceberg tracks in {time.perf_counter() - t0:.1f}s")

    moving = filter_moving_segments(tracks)
    print(f"After removing grounded (<0.1 kt): {len(moving)} moving tracks")

    train_dates = _date_range_inclusive(date(TRAIN_START_YEAR, 1, 1), date(TRAIN_END_YEAR, 12, 31))
    val_dates = _date_range_inclusive(date(VAL_YEAR, 1, 1), date(VAL_YEAR, 12, 31))
    test_dates = _date_range_inclusive(date(TEST_START_YEAR, 1, 1), date(TEST_END_YEAR, 12, 31))

    print("Building VAL (2018) and TEST (2019-2022) datasets...")
    val_ds = build_iceberg_dataset(moving, min(val_dates), max(val_dates), leads=ICELEAD_DAYS)
    test_ds = build_iceberg_dataset(moving, min(test_dates), max(test_dates), leads=ICELEAD_DAYS)
    print(f"VAL rows: {len(val_ds)}   TEST rows: {len(test_ds)}")

    report = evaluate_part1(val_ds, test_ds)

    print()
    print("RESULTS — tracks-only physics baseline (radii calibrated on VAL, coverage on TEST)")
    print(f"{'lead':>5s} | {'best baseline':>24s} | {'cal p50':>8s} | {'cal p90':>8s} | "
          f"{'test median':>10s} | {'test p90':>9s} | {'cov p50':>8s} | {'cov p90':>8s} | {'n':>6s}")
    print("-" * 100)
    for pl in report["per_lead"]:
        te = pl["test"]
        print(
            f"{pl['lead_days']:>5d} | {pl['best_baseline_val']:>24s} | "
            f"{pl['cal_p50_km']:>8.2f} | {pl['cal_p90_km']:>8.2f} | "
            f"{te['median_km']:>10.2f} | {te['p90_km']:>9.2f} | "
            f"{te['empirical_coverage_p50']:>8.3f} | {te['empirical_coverage_p90']:>8.3f} | "
            f"{te['n_samples']:>6d}"
        )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
