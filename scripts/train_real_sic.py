#!/usr/bin/env python
"""Train the real-data SIC forecaster (BE-2).

Pipeline:
  1. Load NSIDC V6 observations for 2005-2024 from disk cache.
  2. Split dates: train 2005-2019, val 2020-2021, test 2022-2024, with a
     14-day embargo between blocks.
  3. Fit climatology and tune damped-anomaly persistence tau per lead on train.
  4. Build feature matrices for each split (VIZ cells from 10% of train days
     + small sample of other cells; full VIZ for val and test).
  5. Train one HistGradientBoostingRegressor per lead (3, 7, 14 days) on the
     residual (truth - tuned baseline), selected on val RMSE.
  6. Split-conformal calibration for 90% intervals on val residuals.
  7. Evaluate on val (promotion gate) and test.
  8. Sensor check on 2025-01 onward (AMSR2 era).
  9. Write artefact + metrics.
"""
from __future__ import annotations

import argparse
import json
import platform
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Tuple

import joblib
import numpy as np
import sklearn

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.eval import baselines
from src.eval.areas import compute_cell_areas
from src.eval.io import latlon_grid
from src.eval.regions import SECTORS_SIMPLE, AUSTRAL_DEPARTURE_SEASON
from src.ml.real_dataset import (
    RealSICSplit, FEATURE_NAMES_REAL, REAL_LEAD_DAYS,
    build_real_sic_dataset, compute_climatology, build_viz_mask, load_real_dates,
    TRAIN_END_YEAR, VAL_YEARS, TEST_YEARS, EMBARGO_DAYS,
)
from src.ml.registry import MODELS_DIR, metrics_path
from src.ml.real_sic_forecaster import RealSICForecaster as RealForecast


DEFAULT_SEED = 26059
REAL_ARTEFACT_NAME = "real_sic_forecaster.joblib"


def _doy_key(d: date) -> Tuple[int, int]:
    return (d.month, d.day)


def _date_list(year_start: int, year_end: int) -> List[date]:
    out: List[date] = []
    cur = date(year_start, 1, 1)
    end = date(year_end, 12, 31)
    while cur <= end:
        out.append(cur)
        cur += timedelta(days=1)
    return out


def _split_dates_quick(
    all_dates: List[date], train_end_year: int, val_years: tuple, test_years: tuple,
) -> Tuple[List[date], List[date], List[date]]:
    train_dates = [d for d in all_dates if d.year <= train_end_year]
    val_dates = [d for d in all_dates if d.year in val_years]
    test_dates = [d for d in all_dates if d.year in test_years]

    val_start = min(val_dates) if val_dates else date(1, 1, 1)
    test_start = min(test_dates) if test_dates else date(1, 1, 1)

    train_dates = [d for d in train_dates if (val_start - d).days > EMBARGO_DAYS]
    val_dates = [d for d in val_dates if (test_start - d).days > EMBARGO_DAYS]
    return train_dates, val_dates, test_dates


def _split_dates(all_dates: List[date]) -> Tuple[List[date], List[date], List[date]]:
    train_dates = [d for d in all_dates if d.year <= TRAIN_END_YEAR]
    val_dates = [d for d in all_dates if d.year in VAL_YEARS]
    test_dates = [d for d in all_dates if d.year in TEST_YEARS]

    # Embargo: drop dates within EMBARGO_DAYS of val/test boundaries.
    val_start = min(val_dates) if val_dates else date(1, 1, 1)
    test_start = min(test_dates) if test_dates else date(1, 1, 1)

    train_dates = [d for d in train_dates if (val_start - d).days > EMBARGO_DAYS]
    val_dates = [d for d in val_dates if (test_start - d).days > EMBARGO_DAYS]
    return train_dates, val_dates, test_dates


def _fmt(value: Any, width: int = 9, digits: int = 4) -> str:
    if value is None or (isinstance(value, float) and not np.isfinite(value)):
        return "n/a".rjust(width)
    if isinstance(value, float):
        return f"{value:.{digits}f}".rjust(width)
    return str(value).rjust(width)


def main(argv: List[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--cache-dir", type=Path, default=None)
    parser.add_argument("--start", type=str, default="2005-01-01")
    parser.add_argument("--end", type=str, default="2024-12-31")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-viz-fraction", type=float, default=0.03,
                        help="Fraction of VIZ cells from each sampled training day")
    parser.add_argument("--n-boot", type=int, default=200)
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke run with a small date subset")
    args = parser.parse_args(argv)

    if args.quick:
        args.start = "2005-01-01"
        args.end = "2008-12-31"
        sample_viz = 0.05
        val_sample_viz = 0.1
        n_boot_quick = 10
    else:
        sample_viz = args.sample_viz_fraction
        val_sample_viz = 0.05
        n_boot_quick = args.n_boot

    start = datetime.strptime(args.start, "%Y-%m-%d").date()
    end = datetime.strptime(args.end, "%Y-%m-%d").date()

    print("=" * 92)
    print("ICEFLOW  -  real-data SIC forecaster training (BE-2)")
    print("=" * 92)
    print(f"  mode          {'quick smoke' if args.quick else 'full'}")
    print(f"  seed          {args.seed}")
    print(f"  python        {platform.python_version()}  scikit-learn {sklearn.__version__}  numpy {np.__version__}")
    print(f"  models dir    {MODELS_DIR}")
    print(f"  date range    {start} to {end}")
    print(f"  leads         {list(REAL_LEAD_DAYS)} days")
    print(f"  embargo       {EMBARGO_DAYS} days between train/val/test blocks")
    print()
    print("  DATA PROVENANCE. Observations from NOAA/NSIDC CDR G02202 Version 6")
    print("  (passive microwave, 25 km grid). Train=2005-2019, Val=2020-2021,")
    print("  Test=2022-2024. 2025+ is AMSR2 sensor, evaluated separately.")
    print()

    # ------------------------------------------------------------------ 1. Load
    t0 = time.perf_counter()
    sic_by_date, gaps, grid = load_real_dates(start, end, args.cache_dir)
    load_s = time.perf_counter() - t0
    print(f"  Loaded {len(sic_by_date)} days ({len(gaps)} gaps) in {load_s:.1f}s")

    if len(sic_by_date) < 100:
        print("  ERROR: Too few days available. Need NSIDC cache.")
        return 1

    all_dates = sorted(sic_by_date.keys())
    # Split dates based on available data and mode.
    if args.quick:
        train_end_y = 2005
        val_yrs = (2006, 2007)
        test_yrs = (2008,)
    else:
        train_end_y = TRAIN_END_YEAR
        val_yrs = VAL_YEARS
        test_yrs = TEST_YEARS

    train_dates, val_dates, test_dates = _split_dates_quick(
        all_dates, train_end_y, val_yrs, test_yrs,
    )

    print(f"  Train: {train_dates[0]} to {train_dates[-1]}  ({len(train_dates)} days)")
    print(f"  Val:   {val_dates[0]} to {val_dates[-1]}  ({len(val_dates)} days)")
    print(f"  Test:  {test_dates[0]} to {test_dates[-1]}  ({len(test_dates)} days)")

    from src.eval.splits import check_no_leakage
    max_lead = max(REAL_LEAD_DAYS)
    check_no_leakage(train_dates, val_dates, max_lead)
    check_no_leakage(val_dates, test_dates, max_lead)
    check_no_leakage(train_dates, test_dates, max_lead)
    print("  Leakage check: PASSED")

    # ------------------------------------------------------------------ 2. Climo
    t0 = time.perf_counter()
    clim = compute_climatology(
        sic_by_date, train_dates, use_trend=True,
    )
    print(f"  Climatology fit: {len(clim['doy_to_mean'])} DOYs in {time.perf_counter()-t0:.1f}s")

    ocean_mask = np.isfinite(clim["clim_ref"])
    viz_mask = build_viz_mask(clim["clim_ref"], ocean_mask)
    n_viz = int(viz_mask.sum())
    n_ocean = int(ocean_mask.sum())
    print(f"  Ocean cells: {n_ocean}  VIZ cells: {n_viz}  VIZ fraction: {n_viz/n_ocean:.2%}")

    # ------------------------------------------------------------------ 3. Tau
    taus: Dict[int, float] = {}
    for lead in REAL_LEAD_DAYS:
        tau, rmse = baselines.fit_damped_tau(
            sic_by_date, train_dates, clim["doy_to_mean"],
            lead, viz_mask, max_pairs=200 if args.quick else None,
        )
        taus[lead] = tau
        print(f"  tau[{lead}d] = {tau:.1f} days  (baseline RMSE = {rmse:.6f})")

    # ------------------------------------------------------------------ 4. Datasets
    print()
    print("  Building datasets...")
    t0 = time.perf_counter()
    sample_other = 0.01 if not args.quick else 0.001
    train_ds = build_real_sic_dataset(
        sic_by_date, train_dates, clim, taus,
        grid["lat"], grid["lon"], grid["sector_id"],
        REAL_LEAD_DAYS,
        sample_viz_fraction=sample_viz,
        sample_other_fraction=sample_other,
        rng_seed=args.seed,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates, clim, taus,
        grid["lat"], grid["lon"], grid["sector_id"],
        REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
        rng_seed=args.seed + 100,
    )
    test_ds = build_real_sic_dataset(
        sic_by_date, test_dates, clim, taus,
        grid["lat"], grid["lon"], grid["sector_id"],
        REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
        rng_seed=args.seed + 200,
    )
    ds_s = time.perf_counter() - t0
    print(f"  Datasets built in {ds_s:.1f}s")
    print(f"  Train: {len(train_ds)} rows  Val: {len(val_ds)} rows  Test: {len(test_ds)} rows")
    print(f"  Features: {list(train_ds.feature_names)}")

    # ------------------------------------------------------------------ 5. Train
    print()
    print("  Fitting per-lead HistGradientBoostingRegressor...")
    t0 = time.perf_counter()
    model = RealForecast(leads=REAL_LEAD_DAYS, random_state=args.seed)
    model.fit(train_ds, val_ds, taus)
    fit_s = time.perf_counter() - t0
    print(f"  Total training time: {fit_s:.1f}s")

    # ------------------------------------------------------------------ 6. Evaluate
    print()
    print("  Validation results:")
    val_metrics = model.evaluate(val_ds, n_boot=n_boot_quick, seed=args.seed)
    _print_results(val_metrics, "VAL")

    print()
    print("  Test results:")
    test_metrics = model.evaluate(test_ds, n_boot=n_boot_quick, seed=args.seed + 1)
    _print_results(test_metrics, "TEST")

    # ------------------------------------------------------------------ 7. Sensor check
    print()
    print("  Sensor check (AMSR2 era, 2025+):")
    sensor_2025_start = date(2025, 1, 1)
    sensor_dates = [d for d in all_dates if d >= sensor_2025_start]
    if sensor_dates:
        sensor_ds = build_real_sic_dataset(
            sic_by_date, sensor_dates, clim, taus,
            grid["lat"], grid["lon"], grid["sector_id"],
            REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
            rng_seed=args.seed + 300,
        )
        if len(sensor_ds) > 0:
            sensor_metrics = model.evaluate(sensor_ds, n_boot=n_boot_quick, seed=args.seed + 3)
            _print_results(sensor_metrics, "SENSOR-CHECK")
            test_metrics["sensor_check_2025"] = {
                "n_samples": sensor_metrics["n_samples"],
                "overall": sensor_metrics["overall"],
                "per_lead": sensor_metrics["per_lead"],
            }
        else:
            print("  No sensor-check data available (no 2025+ dates with lead pairs)")
    else:
        print("  No 2025+ data in cache for sensor check")

    # ------------------------------------------------------------------ 8. Save
    artefact_path = Path(MODELS_DIR) / REAL_ARTEFACT_NAME
    artefact_path.parent.mkdir(parents=True, exist_ok=True)
    model.save(artefact_path)
    print()
    print(f"  Saved model to {artefact_path.name} ({artefact_path.stat().st_size / 1024:.0f} KB)")

    payload: Dict[str, Any] = {
        "system": "ICEFLOW",
        "trained_on": "real",
        "problem_statement": "BE-2",
        "trained_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "training_wall_time_s": round(fit_s, 2),
        "mode": "quick" if args.quick else "full",
        "seed": args.seed,
        "python_version": platform.python_version(),
        "sklearn_version": sklearn.__version__,
        "numpy_version": np.__version__,
        "data_provenance": (
            "Real NSIDC V6 daily sea-ice concentration (G02202, 25 km polar "
            "stereographic). Train on train_years, val on val_years, test on test_years. "
            f"Record length: {len(sic_by_date)} days; gaps: {len(gaps)}."
        ),
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "product_version": "v06r00",
        "date_range": [str(min(sic_by_date.keys())), str(max(sic_by_date.keys()))],
        "leads_days": list(REAL_LEAD_DAYS),
        "embargo_days": EMBARGO_DAYS,
        "splits": {
            "train_years": sorted({d.year for d in train_dates}),
            "val_years": sorted({d.year for d in val_dates}),
            "test_years": sorted({d.year for d in test_dates}),
        },
        "taus": {str(k): round(v, 2) for k, v in taus.items()},
        "feature_names": list(FEATURE_NAMES_REAL),
        "artefact": artefact_path.name,
        "n_features": len(FEATURE_NAMES_REAL),
        "dataset": {
            "n_train_rows": len(train_ds),
            "n_val_rows": len(val_ds),
            "n_test_rows": len(test_ds),
            "n_viz_cells": n_viz,
            "n_ocean_cells": n_ocean,
            "sample_viz_fraction": sample_viz,
            "val_test_sample_viz_fraction": val_sample_viz,
            "sample_other_fraction": sample_other,
        },
        "fit_seconds": round(fit_s, 2),
        "val_metrics": val_metrics,
        "test_metrics": test_metrics,
        "promoted_leads": test_metrics["promoted_leads"],
        "coverage_90_ci": test_metrics["coverage_90_ci"],
        "evaluation_status": {
            "trained_on": "real",
            "operational_skill_validated": False,
            "used_in_routing": False,
            "promoted_leads": test_metrics["promoted_leads"],
            "status": "real_data_training_complete",
        },
    }

    metrics_path_obj = metrics_path()
    metrics_path_obj.parent.mkdir(parents=True, exist_ok=True)
    with open(metrics_path_obj, "w", encoding="utf-8") as fh:
        json.dump(payload, fh, indent=2, sort_keys=False, default=_json_default)
    print(f"  Metrics written to {metrics_path_obj}")

    return 0


def _print_results(metrics: Dict[str, Any], tag: str) -> None:
    print(f"  [{'='*50}]")
    ov = metrics["overall"]
    print(f"  {tag} overall (all cells):")
    print(f"    model RMSE:     {ov['model_rmse']:.4f}")
    print(f"    baseline RMSE:  {ov['baseline_rmse']:.4f}")
    print(f"    persistence RMSE: {ov['persistence_rmse']:.4f}")
    print(f"    skill vs baseline: {ov['skill_vs_baseline']:+.4f}")
    print(f"    n samples: {ov['n_samples']}")

    print(f"  {tag} per-lead (VIZ cells, promotion gate):")
    print(f"    {'lead':>5s} {'n':>6s}  {'model':>8s} {'baseline':>8s} {'persist':>8s} "
          f"{'diff_ci':>22s}  {'promoted':>8s}")
    for pl in metrics["per_lead"]:
        print(
            f"    {pl['lead_days']:>5d} {pl['n_samples']:>6d}  "
            f"{pl['model_rmse']:>8.4f} {pl['viz_baseline_rmse']:>8.4f} {pl['persistence_rmse']:>8.4f} "
            f"[{pl['viz_rmse_diff_ci'][0]:>8.4f},{pl['viz_rmse_diff_ci'][1]:>8.4f}] "
            f"  {str(pl['promoted']):>8s}"
        )
    print(f"  Coverage (90% CI): overall={metrics['coverage_90_ci']['overall']}")


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


if __name__ == "__main__":
    raise SystemExit(main())
