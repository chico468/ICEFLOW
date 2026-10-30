#!/usr/bin/env python
"""Train the iceberg drift forecaster (BE-3).

Pipeline:
  1. Load and parse the BYU/NIC consolidated Antarctic iceberg database v6
     (data/raw/iceberg/consolidated_database_v6.zip).
  2. Consolidate daily positions per iceberg (average across sensors).
     Drop grounded segments: speed below GROUNDING_SPEED_THRESHOLD_KNOTS
     (0.1 kt = ~0.185 km/day, justified: below this the iceberg is either
     grounded or too small to track reliably from scatterometer data).
  3. Split by iceberg and time: train 2005-2017, val 2018, test 2019-2022.
  4. For each row (iceberg, t0, lead): baseline (b) = 3-day constant velocity.
     Target y = signed cross-track displacement (km) from baseline to truth.
  5. Train one HistGradientBoostingRegressor per lead (1, 3, 7 days) on the
     residual, selected on val RMSE of the full position forecast.
  6. Split-conformal calibration for p50/p90 error radii on val residuals.
  7. Evaluate on val (promotion gate) and test.
  8. Write artefact + scorecard report.

Baselines (computed on TEST for context, never trained on):
  (a) No movement (position held fixed at t0).
  (b) Constant velocity from the last 3 days.  <-- ML competes against this.
  (c) Constant velocity from the last 7 days, damped (0.5x).
"""
from __future__ import annotations

import argparse
import json
import math
import platform
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import numpy as np
import sklearn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    FEATURE_NAMES_ICEBERG,
    IcebergSplit,
    IcebergTrack,
    build_iceberg_dataset,
    load_database,
    filter_moving_segments,
    GROUNDING_SPEED_THRESHOLD_KNOTS,
)
from src.ml.iceberg_forecaster import (
    ICEBERG_PROMOTION_CI_ALPHA,
    IcebergForecaster,
)
from src.ml.registry import MODELS_DIR


DEFAULT_SEED = 26059
ICEBERG_ARTEFACT_NAME = "iceberg_forecaster.joblib"
SCORECARD_REPORT_NAME = "iceberg_ml_report.json"
DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"

TRAIN_START_YEAR = 2005
TRAIN_END_YEAR = 2017
VAL_YEAR = 2018
TEST_START_YEAR = 2019
TEST_END_YEAR = 2022


def _git_sha() -> Optional[str]:
    try:
        import subprocess as sp
        return sp.check_output(
            ["git", "rev-parse", "HEAD"],
            cwd=str(Path(__file__).resolve().parents[1]),
            stderr=sp.DEVNULL,
            text=True,
        ).strip() or None
    except Exception:
        return None


def _json_dump(obj: Any, path: Path) -> None:
    """Dump JSON with NaN/Infinity sanitized to null (valid JSON)."""
    def sanitize(v: Any) -> Any:
        if isinstance(v, dict):
            return {k: sanitize(x) for k, x in v.items()}
        if isinstance(v, list):
            return [sanitize(x) for x in v]
        if isinstance(v, float):
            return None if not math.isfinite(v) else v
        return v
    path.parent.mkdir(parents=True, exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sanitize(obj), f, indent=2, ensure_ascii=False)


def _date_range_inclusive(start: date, end: date) -> List[date]:
    out: List[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _build_berg_splits(
    tracks: List[IcebergTrack],
    train_dates: List[date],
    val_dates: List[date],
    test_dates: List[date],
    leads: Sequence[int],
    seed: int = DEFAULT_SEED,
) -> Dict[str, IcebergSplit]:
    """Build train/val/test splits for iceberg drift."""
    train_ds = build_iceberg_dataset(tracks, min(train_dates), max(train_dates),
                                     leads=leads, rng_seed=seed)
    val_ds = build_iceberg_dataset(tracks, min(val_dates), max(val_dates),
                                   leads=leads, rng_seed=seed + 100)
    test_ds = build_iceberg_dataset(tracks, min(test_dates), max(test_dates),
                                    leads=leads, rng_seed=seed + 200)
    return {"train": train_ds, "val": val_ds, "test": test_ds}


def _build_scorecard_report(
    test_metrics: Dict[str, Any],
    val_metrics: Dict[str, Any],
    train_tracks: List[IcebergTrack],
    sensor_metrics: Optional[Dict[str, Any]],
    train_dates: List[date],
    val_dates: List[date],
    test_dates: List[date],
    fit_s: float,
    git_sha: Optional[str],
    leads: Sequence[int],
) -> Dict[str, Any]:
    """Build the SPRINT contract scorecard report for the iceberg model."""
    def _add_baseline_row(pl: Dict[str, Any], model_name: str, rmse_key: str,
                          median_key: str, p90_key: str) -> Dict[str, Any]:
        return {
            "task": "iceberg_drift",
            "lead_days": pl["lead_days"],
            "domain": "antarctic_waters",
            "season": "all",
            "model": model_name,
            "rmse": pl.get(rmse_key),
            "median_km": pl.get(median_key),
            "p90_km": pl.get(p90_key),
            "ci": [None, None],
            "skill_vs_baseline": None,
            "n": pl.get("n_samples"),
            "n_icebergs": pl.get("n_icebergs"),
            "metric": "great_circle_error_km",
        }

    rows: List[Dict[str, Any]] = []
    for pl in test_metrics.get("per_lead", []):
        lead = pl["lead_days"]
        model_rmse = pl.get("model_rmse_km")
        base_rmse = pl.get("baseline_rmse_km")
        ci = pl.get("rmse_diff_ci", [None, None])

        rows.append({
            "task": "iceberg_drift",
            "lead_days": lead,
            "domain": "antarctic_waters",
            "season": "all",
            "model": "gbm_residual",
            "rmse": model_rmse,
            "median_km": pl.get("median_error_km"),
            "p90_km": pl.get("p90_error_km"),
            "ci": ci,
            "skill_vs_baseline": pl.get("skill_vs_baseline"),
            "n": pl.get("n_samples"),
            "n_icebergs": pl.get("n_icebergs"),
            "metric": "great_circle_error_km",
        })
        rows.append(_add_baseline_row(pl, "no_movement",
            "baseline_a_no_movement_rmse_km",
            "baseline_a_no_movement_median_km",
            "baseline_a_no_movement_p90_km"))
        rows.append(_add_baseline_row(pl, "velocity_3d",
            "baseline_b_velocity_3d_rmse_km",
            "baseline_b_velocity_3d_median_km",
            "baseline_b_velocity_3d_p90_km"))
        rows.append(_add_baseline_row(pl, "velocity_7d_damped",
            "baseline_c_7d_damped_rmse_km",
            "baseline_c_7d_damped_median_km",
            "baseline_c_7d_damped_p90_km"))

    val_rows: List[Dict[str, Any]] = []
    for pl in val_metrics.get("per_lead", []):
        val_rows.append({
            "lead_days": pl["lead_days"],
            "model_rmse_km": pl.get("model_rmse_km"),
            "baseline_rmse_km": pl.get("baseline_b_velocity_3d_rmse_km"),
            "baseline_a_no_movement_rmse_km": pl.get("baseline_a_no_movement_rmse_km"),
            "baseline_c_7d_damped_rmse_km": pl.get("baseline_c_7d_damped_rmse_km"),
            "model_median_km": pl.get("median_error_km"),
            "model_p90_km": pl.get("p90_error_km"),
            "baseline_a_no_movement_median_km": pl.get("baseline_a_no_movement_median_km"),
            "baseline_a_no_movement_p90_km": pl.get("baseline_a_no_movement_p90_km"),
            "baseline_b_velocity_3d_median_km": pl.get("baseline_b_velocity_3d_median_km"),
            "baseline_b_velocity_3d_p90_km": pl.get("baseline_b_velocity_3d_p90_km"),
            "baseline_c_7d_damped_median_km": pl.get("baseline_c_7d_damped_median_km"),
            "baseline_c_7d_damped_p90_km": pl.get("baseline_c_7d_damped_p90_km"),
            "n_samples": pl.get("n_samples"),
            "n_icebergs": pl.get("n_icebergs"),
            "skill_vs_baseline": pl.get("skill_vs_baseline"),
        })

    promoted = {
        "iceberg": {
            str(pl["lead_days"]): (
                pl.get("model_rmse_km", 0) < pl.get("baseline_rmse_km", 0)
                and pl.get("rmse_diff_ci_excludes_zero", False)
            )
            for pl in test_metrics.get("per_lead", [])
        }
    }

    coverage_out: Dict[str, Any] = {}
    for pl in test_metrics.get("per_lead", []):
        lead_str = str(pl["lead_days"])
        cal_p90 = pl.get("cal_p90_km")
        if cal_p90 is not None:
            coverage_out[lead_str] = {
                "target": 0.9,
                # Empirical coverage measured on TEST (fraction within cal_radius), not the
                # calibration target. Previously hardcoded to 0.9, which only described the
                # validation set the radius was fit on.
                "empirical": pl.get("empirical_coverage"),
                "cal_p50_km": pl.get("cal_p50_km"),
                "cal_p90_km": cal_p90,
                "cal_radius_km": pl.get("cal_radius_km"),
            }

    caveats = [
        "Data: BYU/NIC consolidated Antarctic iceberg database v6 (ftp.mers.byu.edu / www.scp.byu.edu/iceberg).",
        "Split: train 2005-2017, val 2018, test 2019-2022, by iceberg track time.",
        "Grounded segments removed: speed below 0.1 kt (GROUNDING_SPEED_THRESHOLD_KNOTS).",
        "Baseline (b): 3-day constant velocity. ML must beat this with CI-by-iceberg excluding zero.",
        "Baseline (c): 7-day constant velocity damped 0.5x. Included for comparison.",
        "Baseline (a): no-movement (position held fixed). Included for reference.",
        "Metric: great-circle error in km. Radii: p50/p90 from split-conformal on validation residuals.",
        "Dates are Julian day YYYYDDD in the source; parsed to ISO for splitting.",
        "Date matching: exact only (no ±1-day tolerance). Fill value '0' in sensor columns is treated as missing.",
        "Longitude wrapping: velocity baselines normalise dlon to [-180, 180) to handle antimeridian crossings.",
        "Corrupt dates (year outside 1976-2022) are filtered during loading.",
    ]

    n_total_bergs = len(set(t.berg_id for t in train_tracks))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "data_source": "real",
        "product": "BYU/NIC consolidated Antarctic iceberg database v6",
        "version": "v6",
        "train_start_year": TRAIN_START_YEAR,
        "train_end_year": TRAIN_END_YEAR,
        "val_year": VAL_YEAR,
        "test_start_year": TEST_START_YEAR,
        "test_end_year": TEST_END_YEAR,
        "lead_days": list(leads),
        "n_tracks_total": n_total_bergs,
        "rows": rows,
        "val_rows": val_rows,
        "promoted": promoted,
        "coverage": coverage_out,
        "radii": test_metrics.get("radii", {}),
        "evaluation_status": {
            "trained_on": "real",
            "operational_skill_validated": False,
            "used_in_routing": False,
            "promoted_leads": sorted(
                [k for k, v in promoted.get("iceberg", {}).items() if v]
            ),
            "status": "real_data_training_complete",
        },
        "caveats": caveats,
    }


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--n-boot", type=int, default=200)
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke run with a small date subset")
    parser.add_argument("--evaluate-only", action="store_true",
                        help="Load saved model and evaluate without retraining")
    args = parser.parse_args(argv)

    print("=" * 92)
    print("ICEFLOW  -  iceberg drift forecaster training (BE-3)")
    print("=" * 92)
    print(f"  mode          {'quick smoke' if args.quick else 'full'}")
    print(f"  seed          {args.seed}")
    print(f"  python        {platform.python_version()}  scikit-learn {sklearn.__version__}  numpy {np.__version__}")
    print(f"  models dir    {MODELS_DIR}")
    print(f"  leads         {list(ICELEAD_DAYS)} days")
    print(f"  train         2005-2017")
    print(f"  val           2018")
    print(f"  test          2019-2022")
    print(f"  embargo       no embargo (tracks are split at day boundaries)")
    print()
    print("  DATA PROVENANCE. BYU/NIC consolidated Antarctic iceberg database v6.")
    print("  Daily positions, one CSV per iceberg, 1976-2022.")
    print()

    # ------------------------------------------------------------------ 1. Load
    t0 = time.perf_counter()
    db_path = DEFAULT_DATABASE_PATH
    if not db_path.is_file():
        print(f"  ERROR: Iceberg database not found. Looked for:")
        print(f"    data/raw/iceberg/consolidated_database_v6.zip")
        print(f"  Download from: https://www.scp.byu.edu/iceberg/consolidated_database_v6.zip")
        return 1

    print(f"  Loading database from {db_path.name}...")
    tracks = load_database(db_path)
    load_s = time.perf_counter() - t0
    print(f"  Loaded {len(tracks)} iceberg tracks in {load_s:.1f}s")

    # ------------------------------------------------------------------ 2. Filter
    tracks_filtered = filter_moving_segments(tracks)
    print(f"  After removing grounded (< {GROUNDING_SPEED_THRESHOLD_KNOTS} kt): "
          f"{len(tracks_filtered)} tracks, "
          f"{sum(len(t.dates) for t in tracks_filtered)} total position-days")

    # ------------------------------------------------------------------ 3. Split
    train_start = date(TRAIN_START_YEAR, 1, 1)
    train_end = date(TRAIN_END_YEAR, 12, 31)
    val_start = date(VAL_YEAR, 1, 1)
    val_end = date(VAL_YEAR, 12, 31)
    test_start = date(TEST_START_YEAR, 1, 1)
    test_end = date(TEST_END_YEAR, 12, 31)

    train_dates = _date_range_inclusive(train_start, train_end)
    val_dates = _date_range_inclusive(val_start, val_end)
    test_dates = _date_range_inclusive(test_start, test_end)

    print()
    print(f"  Building datasets...")
    ds_t0 = time.perf_counter()
    splits = _build_berg_splits(
        tracks_filtered, train_dates, val_dates, test_dates,
        ICELEAD_DAYS, seed=args.seed,
    )
    ds_s = time.perf_counter() - ds_t0
    print(f"  Datasets built in {ds_s:.1f}s")
    print(f"  Train: {len(splits['train'])} rows  "
          f"Val: {len(splits['val'])} rows  "
          f"Test: {len(splits['test'])} rows")
    print(f"  Features: {list(splits['train'].feature_names)}")

    # ------------------------------------------------------------------ 4. Train
    print()
    if args.evaluate_only:
        print("  Evaluate-only mode: loading saved model (skip training)...")
        artefact_path_existing = Path(MODELS_DIR) / ICEBERG_ARTEFACT_NAME
        if not artefact_path_existing.is_file():
            print(f"  ERROR: No saved model at {artefact_path_existing}")
            return 1
        model = IcebergForecaster.load(artefact_path_existing)
        fit_s = 0.0
    else:
        print("  Fitting per-lead HistGradientBoostingRegressor...")
        t0 = time.perf_counter()
        model = IcebergForecaster(leads=ICELEAD_DAYS, random_state=args.seed)
        model.fit(splits["train"], splits["val"])
        fit_s = time.perf_counter() - t0
        print(f"  Total training time: {fit_s:.1f}s")

    # ------------------------------------------------------------------ 5. Evaluate
    print()
    print("  Validation results:")
    val_metrics = model.evaluate(splits["val"], n_boot=args.n_boot, seed=args.seed)
    _print_iceberg_results(val_metrics, "VAL")

    print()
    print("  Test results:")
    test_metrics = model.evaluate(splits["test"], n_boot=args.n_boot, seed=args.seed + 1)
    _print_iceberg_results(test_metrics, "TEST")

    # ------------------------------------------------------------------ 6. Save
    artefact_path = Path(MODELS_DIR) / ICEBERG_ARTEFACT_NAME
    artefact_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.evaluate_only:
        model.save(artefact_path)
        print()
        print(f"  Saved model to {artefact_path.name} ({artefact_path.stat().st_size / 1024:.0f} KB)")

    # ------------------------------------------------------------------ 7. Scorecard
    scorecard = _build_scorecard_report(
        test_metrics, val_metrics, tracks_filtered,
        None, train_dates, val_dates, test_dates,
        fit_s, _git_sha(), ICELEAD_DAYS,
    )
    report_path = Path(MODELS_DIR) / "eval" / SCORECARD_REPORT_NAME
    _json_dump(scorecard, report_path)
    print(f"  Scorecard report written to {report_path}")

    return 0


def _print_iceberg_results(metrics: Dict[str, Any], tag: str) -> None:
    print(f"  [{tag}] per-lead:")
    print(f"    {'lead':>5s} {'n':>6s} {'n_bergs':>8s}  {'model':>10s} {'base(b)':>10s} {'base(a)':>10s} "
          f"{'diff_ci':>22s}  {'promoted':>8s}")
    for pl in metrics.get("per_lead", []):
        ci = pl.get("rmse_diff_ci", [None, None])
        ci_str = f"[{ci[0]:.4f},{ci[1]:.4f}]" if ci[0] is not None else "n/a"
        lead = pl["lead_days"]
        promoted = metrics.get("promoted", {}).get("iceberg", {}).get(str(lead), False)
        print(
            f"    {lead:>5d} {pl['n_samples']:>6d} {pl['n_icebergs']:>8d}  "
            f"{pl.get('model_rmse_km', float('nan')):>10.4f} {pl.get('baseline_rmse_km', float('nan')):>10.4f} "
            f"{pl.get('baseline_a_no_movement_rmse_km', float('nan')):>10.4f}  "
            f"{ci_str:>22s}  {str(promoted):>8s}"
        )
    print(f"    Radii:")
    for lead_str, radii in metrics.get("radii", {}).items():
        print(f"      lead {lead_str}: p50={radii.get('p50', 'n/a')} km  p90={radii.get('p90', 'n/a')} km")


DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[1] / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"


if __name__ == "__main__":
    raise SystemExit(main())
