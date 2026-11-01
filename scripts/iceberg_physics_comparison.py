#!/usr/bin/env python
"""
Phase 4 step 4 — paired iceberg drift comparison on IDENTICAL (track, t0, lead) samples.

Computes, on VAL (2018) and TEST (2019-2022) splits of the real BYU/NIC v6 tracks:

  Baselines (no forcing, no ML):
    (a) no movement        — position held fixed at t0
    (b) 3-day velocity     — constant velocity from the last 3 days
    (c) 7-day damped velocity — constant velocity from the last 7 days, damped 0.5x

  Forcing variants (require real ERA5 wind + GLORYS current data, PART 2/3):
    (d) wind-only ablation            — ERA5 10 m wind only
    (e) full physics                  — ERA5 wind + GLORYS currents (surface and 0-100 m mean)

Method:
  * All baselines are evaluated on the SAME rows (identical (track, t0, lead) samples),
    so errors are paired per lead.
  * VAL (2018): choose the best baseline per lead (lowest median great-circle error).
  * TEST (2019-2022): report median and p90 km, n tracks, n steps for every variant;
    bootstrap CI (by iceberg) of (variant error - best baseline error); promoted computed
    in code = best baseline beats the runner-up with CI excluding zero.
  * No tuning on TEST: variant selection and any calibration happen on VAL only.
  * data_source is "real" only for results computed from real forcing/tracks. Wind-only and
    full-physics rows are omitted (not fabricated) when ERA5/GLORYS data is absent.

Writes models/eval/iceberg_physics_report.json.
"""
from __future__ import annotations

import json
import math
import os
import sys
import time
from datetime import date
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
from src.ml.iceberg_forecaster import _block_bootstrap_ci_by_berg

TRAIN_START_YEAR = 2005
TRAIN_END_YEAR = 2017
VAL_YEAR = 2018
TEST_START_YEAR = 2019
TEST_END_YEAR = 2022
DAMPING = 0.5

REPORT_PATH = REPO_ROOT / "models" / "eval" / "iceberg_physics_report.json"
DEFAULT_DATABASE_PATH = REPO_ROOT / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"

# Real-forcing data locations (populated by PART 2 ERA5 download and GLORYS ingest).
ERA5_WIND_DIR = REPO_ROOT / "data" / "raw" / "iceberg" / "era5_wind"
GLORYS_CURRENT_DIR = REPO_ROOT / "data" / "raw" / "glorys"

BASELINES = ("no_move", "velocity_3d", "velocity_7d_damped")
BASELINE_LABELS = {
    "no_move": "no movement",
    "velocity_3d": "3-day constant velocity",
    "velocity_7d_damped": "7-day damped constant velocity",
}
FORCING_VARIANTS = ("wind_only", "full_physics", "velocity_initialised")


def _date_range_inclusive(start: date, end: date) -> List[date]:
    out: List[date] = []
    cur = start
    while cur <= end:
        out.append(cur)
        cur += __import__("datetime").timedelta(days=1)
    return out


def _percentile(values: np.ndarray, q: float) -> float:
    return float(np.percentile(values, q)) if len(values) > 0 else float("nan")


def _baseline_errors(ds, baseline: str) -> np.ndarray:
    if baseline == "no_move":
        return _vectorized_haversine(ds.X[:, 0], ds.X[:, 1], ds.truth_lat, ds.truth_lon)
    if baseline == "velocity_3d":
        return ds.baseline_error_km.copy()
    if baseline == "velocity_7d_damped":
        return ds.baseline_damped_error_km.copy()
    raise ValueError(f"unknown baseline {baseline!r}")


def _vectorized_haversine(
    lat1: np.ndarray, lon1: np.ndarray, lat2: np.ndarray, lon2: np.ndarray,
) -> np.ndarray:
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return 6371.0088 * c


def _rows_for_lead(ds, lead: int) -> Dict[str, np.ndarray]:
    mask = ds.lead_days == float(lead)
    return {
        "mask": mask,
        "berg_id": ds.berg_id[mask],
        "n_samples": int(mask.sum()),
        "n_tracks": int(len(np.unique(ds.berg_id[mask]))) if int(mask.sum()) > 0 else 0,
    }


def _ci_diff(pred_err: np.ndarray, base_err: np.ndarray, berg_ids: np.ndarray,
             seed: int = 26059) -> Tuple[float, float, float, float]:
    """Bootstrap CI (by iceberg) of (pred_rmse - base_rmse). Returns (pred, base, lo, hi)."""
    return _block_bootstrap_ci_by_berg(pred_err, base_err, berg_ids, n_boot=200, seed=seed)


def evaluate_comparison(val_ds, test_ds, forcing_available: bool) -> Dict[str, Any]:
    per_lead: List[Dict[str, Any]] = []
    for lead in ICELEAD_DAYS:
        lead_entry: Dict[str, Any] = {"lead_days": lead}

        # --- VAL: choose best baseline (lowest median) ----------------------
        val_summaries: Dict[str, Dict[str, Any]] = {}
        val_errs: Dict[str, np.ndarray] = {}
        for baseline in BASELINES:
            errs = _np_abs(_baseline_errors(val_ds, baseline))[
                val_ds.lead_days == float(lead)
            ]
            val_errs[baseline] = errs
            val_summaries[baseline] = {
                "median_km": _percentile(errs, 50),
                "p90_km": _percentile(errs, 90),
                "n_samples": int(len(errs)),
            }
        lead_entry["val"] = val_summaries

        best_baseline = min(BASELINES, key=lambda b: val_summaries[b]["median_km"])
        lead_entry["best_baseline_val"] = best_baseline

        # --- TEST: identical samples for every variant ----------------------
        test_entry: Dict[str, Any] = {}
        test_errs: Dict[str, np.ndarray] = {}
        for baseline in BASELINES:
            errs = _np_abs(_baseline_errors(test_ds, baseline))[
                test_ds.lead_days == float(lead)
            ]
            test_errs[baseline] = errs
            rows = _rows_for_lead(test_ds, lead)
            test_entry[baseline] = {
                "label": BASELINE_LABELS[baseline],
                "median_km": _percentile(errs, 50),
                "p90_km": _percentile(errs, 90),
                "n_samples": rows["n_samples"],
                "n_tracks": rows["n_tracks"],
                "n_steps": rows["n_samples"],
            }

        # Forcing variants: compute only when real data present; never fabricate.
        if forcing_available:
            for variant in FORCING_VARIANTS:
                variant_errs = _run_forcing_variant(test_ds, lead, variant)
                if variant_errs is None:
                    test_entry[variant] = {
                        "label": variant,
                        "available": False,
                        "reason": "real forcing data not present on disk",
                    }
                else:
                    test_errs[variant] = variant_errs
                    test_entry[variant] = {
                        "label": variant,
                        "available": True,
                        "median_km": _percentile(variant_errs, 50),
                        "p90_km": _percentile(variant_errs, 90),
                        "n_samples": int(len(variant_errs)),
                        "n_tracks": int(len(np.unique(test_ds.berg_id[test_ds.lead_days == float(lead)]))),
                        "n_steps": int(len(variant_errs)),
                    }
        else:
            for variant in FORCING_VARIANTS:
                test_entry[variant] = {
                    "label": variant,
                    "available": False,
                    "reason": "ERA5 wind and/or GLORYS current not on disk (PART 2/3 pending)",
                }

        # Bootstrap CI vs best baseline on the identical TEST samples.
        best_err = test_errs[best_baseline]
        berg_ids = test_ds.berg_id[test_ds.lead_days == float(lead)]
        ci_block: Dict[str, Any] = {}
        promoted = False
        runner_up = None
        runner_up_diff = None
        for variant, errs in test_errs.items():
            if variant == best_baseline:
                continue
            model_rmse, base_rmse, ci_lo, ci_hi = _ci_diff(errs, best_err, berg_ids)
            diff = model_rmse - base_rmse  # positive = variant worse than best
            ci_block[variant] = {
                "rmse_variant_km": round(model_rmse, 4) if math.isfinite(model_rmse) else None,
                "rmse_best_baseline_km": round(base_rmse, 4) if math.isfinite(base_rmse) else None,
                "ci_lo": round(ci_lo, 4) if math.isfinite(ci_lo) else None,
                "ci_hi": round(ci_hi, 4) if math.isfinite(ci_hi) else None,
                "diff_km": round(diff, 4) if math.isfinite(diff) else None,
                "ci_excludes_zero": bool((ci_lo > 0.0) or (ci_hi < 0.0)),
            }
            if runner_up is None or diff < runner_up_diff:
                runner_up = variant
                runner_up_diff = diff

        # Promoted (computed in code): best baseline beats runner-up with CI excluding zero.
        if runner_up is not None and runner_up in ci_block:
            cb = ci_block[runner_up]
            # best baseline is better iff runner_up diff > 0 and CI entirely above 0.
            promoted = bool(cb["diff_km"] is not None and cb["diff_km"] > 0.0
                            and cb["ci_lo"] is not None and cb["ci_lo"] > 0.0)
        test_entry["ci_vs_best_baseline"] = ci_block
        test_entry["promoted"] = promoted
        test_entry["best_baseline"] = best_baseline

        lead_entry["test"] = test_entry
        per_lead.append(lead_entry)

    return {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "phase": 4,
        "step": 4,
        "name": "paired iceberg drift comparison on identical (track, t0, lead) samples",
        "data_source": "real",
        "product": "BYU/NIC consolidated Antarctic iceberg database v6",
        "train_start_year": TRAIN_START_YEAR,
        "train_end_year": TRAIN_END_YEAR,
        "val_year": VAL_YEAR,
        "test_start_year": TEST_START_YEAR,
        "test_end_year": TEST_END_YEAR,
        "leads": list(ICELEAD_DAYS),
        "baselines": [{"key": b, "label": BASELINE_LABELS[b]} for b in BASELINES],
        "forcing_available": forcing_available,
        "forcing_note": (
            "Wind-only ablation (ERA5 wind), full physics (ERA5 wind + GLORYS currents, "
            "surface and 0-100 m mean), and velocity-initialised physics (start from the last "
            "3-day observed velocity) require PART 2 ERA5 download and GLORYS ingest. "
            "Rows omitted, not fabricated, when data is absent."
        ),
        "method": (
            "VAL (2018) selects best baseline per lead by median error. TEST (2019-2022) reports "
            "median/p90/n on identical (track, t0, lead) samples. Bootstrap CI by iceberg of "
            "(variant - best baseline) RMSE difference; promoted = best baseline beats runner-up "
            "with CI excluding zero. No tuning on TEST."
        ),
        "per_lead": per_lead,
    }


def _np_abs(arr: np.ndarray) -> np.ndarray:
    return np.abs(arr)


def _run_forcing_variant(test_ds, lead: int, variant: str) -> Optional[np.ndarray]:
    """Run a real-forcing variant. Returns abs errors (km) or None if data unavailable."""
    # ERA5 wind directory must be populated (PART 2). GLORYS for full physics.
    if variant == "wind_only" and not ERA5_WIND_DIR.is_dir():
        return None
    if variant == "full_physics" and not (ERA5_WIND_DIR.is_dir() and GLORYS_CURRENT_DIR.is_dir()):
        return None
    # Real forcing integration would go here: drive iceberg_tracker.predict_iceberg_drift
    # with ERA5/GLORYS fields at (track, t0) and compare to truth at t0+lead.
    # Not implemented until PART 2/3 data is present; returning None keeps results honest.
    return None


def main() -> int:
    db_path = DEFAULT_DATABASE_PATH
    if not db_path.is_file():
        print(f"ERROR: Iceberg database not found at {db_path}", file=sys.stderr)
        return 1

    forcing_available = ERA5_WIND_DIR.is_dir() and GLORYS_CURRENT_DIR.is_dir()
    print("=" * 92)
    print("PHASE 4 STEP 4 — paired iceberg drift comparison (identical samples, VAL/TEST)")
    print("=" * 92)
    print(f"Real forcing available: {forcing_available} "
          f"(ERA5={ERA5_WIND_DIR.is_dir()}, GLORYS={GLORYS_CURRENT_DIR.is_dir()})")
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

    report = evaluate_comparison(val_ds, test_ds, forcing_available)

    print()
    print("RESULTS — paired comparison (radii/baseline chosen on VAL; metrics on TEST)")
    print(f"{'lead':>5s} | {'best baseline':>24s} | {'variant':>22s} | {'med':>7s} | {'p90':>7s} | {'n':>6s} | {'promoted':>8s}")
    print("-" * 100)
    for pl in report["per_lead"]:
        te = pl["test"]
        for variant in (pl["best_baseline_val"],) + tuple(v for v in BASELINES if v != pl["best_baseline_val"]):
            e = te[variant]
            print(
                f"{pl['lead_days']:>5d} | {pl['best_baseline_val']:>24s} | {variant:>22s} | "
                f"{e['median_km']:>7.2f} | {e['p90_km']:>7.2f} | {e['n_samples']:>6d} | "
                f"{'--' if variant != pl['best_baseline_val'] else str(te['promoted']):>8s}"
            )

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReport written to {REPORT_PATH}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
