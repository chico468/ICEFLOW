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
import math
import platform
import sys
import time
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

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
SCORECARD_REPORT_NAME = "real_sic_ml_report.json"


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
    parser.add_argument("--end", type=str, default="2025-12-31",
                        help="End date inclusive; 2005-2024 train/val/test, 2025+ sensor check")
    parser.add_argument("--seed", type=int, default=DEFAULT_SEED)
    parser.add_argument("--sample-viz-fraction", type=float, default=0.03,
                        help="Fraction of VIZ cells from each sampled training day")
    parser.add_argument("--n-boot", type=int, default=2000)
    parser.add_argument("--quick", action="store_true",
                        help="Quick smoke run with a small date subset")
    parser.add_argument("--evaluate-only", action="store_true",
                        help="Load saved model and evaluate without retraining")
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
        grid["lat"], grid["lon"], grid["sector_id"], grid["areas"],
        REAL_LEAD_DAYS,
        sample_viz_fraction=sample_viz,
        sample_other_fraction=sample_other,
        rng_seed=args.seed,
    )
    val_ds = build_real_sic_dataset(
        sic_by_date, val_dates, clim, taus,
        grid["lat"], grid["lon"], grid["sector_id"], grid["areas"],
        REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
        rng_seed=args.seed + 100,
    )
    test_ds = build_real_sic_dataset(
        sic_by_date, test_dates, clim, taus,
        grid["lat"], grid["lon"], grid["sector_id"], grid["areas"],
        REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
        rng_seed=args.seed + 200,
    )
    ds_s = time.perf_counter() - t0
    print(f"  Datasets built in {ds_s:.1f}s")
    print(f"  Train: {len(train_ds)} rows  Val: {len(val_ds)} rows  Test: {len(test_ds)} rows")
    print(f"  Features: {list(train_ds.feature_names)}")

    # ------------------------------------------------------------------ 5. Train
    print()
    if args.evaluate_only:
        print("  Evaluate-only mode: loading saved model (skip training)...")
        artefact_path_existing = Path(MODELS_DIR) / REAL_ARTEFACT_NAME
        if not artefact_path_existing.is_file():
            print(f"  ERROR: No saved model at {artefact_path_existing}")
            return 1
        model = RealForecast.load(artefact_path_existing)
        fit_s = 0.0
        print(f"  Loaded {artefact_path_existing.name} ({artefact_path_existing.stat().st_size / 1024:.0f} KB)")
    else:
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
    sensor_metrics = None
    if sensor_dates:
        sensor_ds = build_real_sic_dataset(
            sic_by_date, sensor_dates, clim, taus,
            grid["lat"], grid["lon"], grid["sector_id"], grid["areas"],
            REAL_LEAD_DAYS, sample_viz_fraction=val_sample_viz, sample_other_fraction=0.0,
            rng_seed=args.seed + 300,
        )
        if len(sensor_ds) > 0:
            sensor_metrics = model.evaluate(sensor_ds, n_boot=n_boot_quick, seed=args.seed + 3)
            _print_results(sensor_metrics, "SENSOR-CHECK")
        else:
            print("  No sensor-check data available (no 2025+ dates with lead pairs)")
    else:
        print("  No 2025+ data in cache for sensor check")

    # Sensor check date range and sample count.
    sensor_date_range = None
    sensor_n_days = 0
    if sensor_dates:
        sensor_date_range = f"{min(sensor_dates).isoformat()} to {max(sensor_dates).isoformat()}"
        sensor_n_days = len(sensor_dates)

    # ------------------------------------------------------------------ 8. Save model (skip in evaluate-only)
    artefact_path = Path(MODELS_DIR) / REAL_ARTEFACT_NAME
    artefact_path.parent.mkdir(parents=True, exist_ok=True)
    if not args.evaluate_only:
        model.save(artefact_path)
        print()
        print(f"  Saved model to {artefact_path.name} ({artefact_path.stat().st_size / 1024:.0f} KB)")

    # ------------------------------------------------------------------ 9. Scorecard report
    scorecard = _build_scorecard_report(
        test_metrics, taus, val_metrics,
        {},
        sensor_metrics,
        train_dates, val_dates, test_dates,
        len(sic_by_date), len(gaps), fit_s,
        sample_viz, val_sample_viz, sample_other,
        _git_sha(),
        sensor_date_range, sensor_n_days,
    )

    report_path = Path(MODELS_DIR) / "eval" / "real_sic_ml_report.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    _json_dump(scorecard, report_path)
    print(f"  Scorecard report written to {report_path}")

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
    cov = metrics.get("coverage_90_ci", {})
    print(f"  Coverage (90% CI): overall={cov.get('overall', 'n/a')}")


def _build_scorecard_report(
    test_metrics: Dict[str, Any],
    taus: Dict[int, float],
    val_metrics: Dict[str, Any],
    per_lead_test: Dict[str, Any],
    sensor_metrics: Optional[Dict[str, Any]],
    train_dates: List[date],
    val_dates: List[date],
    test_dates: List[date],
    record_length: int,
    n_gaps: int,
    fit_s: float,
    sample_viz: float,
    val_sample_viz: float,
    sample_other: float,
    git_sha: Optional[str] = None,
    sensor_date_range: Optional[str] = None,
    sensor_n_days: int = 0,
) -> Dict[str, Any]:
    """Build the SPRINT contract scorecard report for the scorecard endpoint.

    rows: [{task, lead_days, domain, season, model, rmse, ci:[lo,hi], skill_vs_baseline, n}]
          domain is "all_ocean" or "variable_ice_zone" or "sector:<name>" or "iiee_15pct"
          season is "all" or "nov_mar"
    """
    from src.ml.real_dataset import SECTORS_SIMPLE

    rows: List[Dict[str, Any]] = []
    sector_names = list(SECTORS_SIMPLE.keys())
    test_per_lead = test_metrics["per_lead"]
    cov = test_metrics["coverage_90_ci"]

    for pl in test_per_lead:
        lead = pl["lead_days"]
        viz_model_rmse = pl["viz_model_rmse"]
        viz_baseline_rmse = pl["viz_baseline_rmse"]
        viz_skill = round(1.0 - viz_model_rmse / viz_baseline_rmse, 5) if viz_baseline_rmse > 0 else None
        # Main model row (VIZ cells, all-season).
        rows.append({
            "task": "sic",
            "lead_days": lead,
            "domain": "variable_ice_zone",
            "season": "all",
            "model": "gbm_residual",
            "rmse": viz_model_rmse,
            "ci": pl["viz_rmse_diff_ci"],
            "skill_vs_baseline": viz_skill,
            "n": pl["n_samples"],
        })
        # Nov-Mar VIZ row (own RMSE and n, not all-season).
        viz_nm_rmse = pl.get("viz_nov_mar_model_rmse", float("nan"))
        viz_nm_n = pl.get("viz_nov_mar_n_samples", pl["n_samples"])
        rows.append({
            "task": "sic",
            "lead_days": lead,
            "domain": "variable_ice_zone",
            "season": "nov_mar",
            "model": "gbm_residual",
            "rmse": viz_nm_rmse,
            "ci": pl["viz_nov_mar_rmse_diff_ci"],
            "skill_vs_baseline": None,
            "n": viz_nm_n,
        })
        # Nov-Mar damped-persistence baseline row.
        viz_nm_base_rmse = pl.get("viz_nov_mar_baseline_rmse", float("nan"))
        rows.append({
            "task": "sic",
            "lead_days": lead,
            "domain": "variable_ice_zone",
            "season": "nov_mar",
            "model": "damped_persistence",
            "rmse": viz_nm_base_rmse,
            "ci": [None, None],
            "skill_vs_baseline": None,
            "n": viz_nm_n,
        })
        # IIEE rows (model and damped-persistence baseline), gated on sanity.
        iiee_sanity_passed = bool(pl.get("iiee_sanity_passed", False))
        iiee_all = pl.get("iiee_15_pct")
        iiee_all_base = pl.get("iiee_15_pct_baseline")
        iiee_nov_mar = pl.get("iiee_15_pct_nov_mar")
        iiee_nov_mar_base = pl.get("iiee_15_pct_nov_mar_baseline")
        iiee_all_area = pl.get("iiee_15_pct_area_mkm2_per_day")
        iiee_all_area_base = pl.get("iiee_15_pct_area_mkm2_per_day_baseline")
        iiee_nov_mar_area = pl.get("iiee_15_pct_nov_mar_area_mkm2_per_day")
        iiee_nov_mar_area_base = pl.get("iiee_15_pct_nov_mar_area_mkm2_per_day_baseline")

        if iiee_sanity_passed:
            # Percentage rows.
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "all",
                "model": "gbm_residual",
                "rmse": iiee_all,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_pct",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "all",
                "model": "damped_persistence",
                "rmse": iiee_all_base,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_pct",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "nov_mar",
                "model": "gbm_residual",
                "rmse": iiee_nov_mar,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_pct",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "nov_mar",
                "model": "damped_persistence",
                "rmse": iiee_nov_mar_base,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_pct",
            })

            # Area-based rows (million km² per day).
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "all",
                "model": "gbm_residual",
                "rmse": iiee_all_area,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_area_mkm2_per_day",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "all",
                "model": "damped_persistence",
                "rmse": iiee_all_area_base,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_area_mkm2_per_day",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "nov_mar",
                "model": "gbm_residual",
                "rmse": iiee_nov_mar_area,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_area_mkm2_per_day",
            })
            rows.append({
                "task": "sic",
                "lead_days": lead,
                "domain": "iiee_15pct",
                "season": "nov_mar",
                "model": "damped_persistence",
                "rmse": iiee_nov_mar_area_base,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "metric": "iiee_area_mkm2_per_day",
            })
        else:
            caveats.append(
                f"IIEE rows suppressed for lead {lead}: sanity check failed "
                f"({pl.get('iiee_sanity', {})})."
            )

    # Per-lead, per-sector coverage rows (dedicated coverage field, not rmse).
    for lead, sec_cov in cov.get("per_lead_per_sector", {}).items():
        sec_n = cov.get("per_lead_per_sector_n", {}).get(str(lead), {})
        for s_name, emp_cov in sec_cov.items():
            rows.append({
                "task": "sic",
                "lead_days": int(lead),
                "domain": f"sector:{s_name}",
                "season": "all",
                "model": "gbm_residual",
                "coverage": emp_cov,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": sec_n.get(s_name, 0),
                "metric": "coverage_90ci",
            })

    # Sensor check rows.
    if sensor_metrics is not None:
        for pl in sensor_metrics["per_lead"]:
            s_model_rmse = pl["viz_model_rmse"]
            s_base_rmse = pl["viz_baseline_rmse"]
            s_skill = round(1.0 - s_model_rmse / s_base_rmse, 5) if s_base_rmse > 0 else None
            rows.append({
                "task": "sic",
                "lead_days": pl["lead_days"],
                "domain": "variable_ice_zone",
                "season": "all",
                "model": "gbm_residual_sensor_amsr2",
                "rmse": s_model_rmse,
                "ci": pl["viz_rmse_diff_ci"],
                "skill_vs_baseline": s_skill,
                "n": pl["n_samples"],
                "caveat": "2025+ AMSR2-era sensor, not in training window",
            })
            # Sensor-era damped-persistence baseline row.
            rows.append({
                "task": "sic",
                "lead_days": pl["lead_days"],
                "domain": "variable_ice_zone",
                "season": "all",
                "model": "damped_persistence_sensor_amsr2",
                "rmse": s_base_rmse,
                "ci": [None, None],
                "skill_vs_baseline": None,
                "n": pl["n_samples"],
                "caveat": "2025+ AMSR2-era sensor, not in training window",
            })

    promoted = {str(pl["lead_days"]): pl.get("promoted", False) for pl in test_per_lead}

    # Block bootstrap info per lead (n date-blocks, block length, resamples).
    bootstrap_info: Dict[str, Any] = {}
    for pl in test_per_lead:
        lead = str(pl["lead_days"])
        bootstrap_info[lead] = {
            "n_date_blocks": pl.get("n_date_blocks"),
            "block_length_days": pl.get("block_length_days"),
            "n_bootstrap_resamples": pl.get("n_bootstrap_resamples"),
        }

    # Sensor-era results as a separate field (does not change promoted).
    sensor_era: Dict[str, Any] = {}
    if sensor_metrics is not None:
        for pl in sensor_metrics["per_lead"]:
            lead = str(pl["lead_days"])
            ci = pl.get("viz_rmse_diff_ci", [None, None])
            sensor_era[lead] = {
                "model_rmse": pl.get("viz_model_rmse"),
                "baseline_rmse": pl.get("viz_baseline_rmse"),
                "rmse_diff_ci": ci,
                "rmse_diff_ci_excludes_zero": pl.get("viz_rmse_diff_ci_excludes_zero_all_season", False),
                "n_samples": pl.get("n_samples"),
                "season": "all",
                "caveat": "2025+ AMSR2-era sensor, not in training window",
            }

    coverage_out: Dict[str, Any] = {}
    for lead_str, lead_cov in cov.get("per_lead", {}).items():
        coverage_out[lead_str] = {
            "target": 0.9,
            "empirical": lead_cov,
        }

    caveats = [
        "Trained on NSIDC V6 SSMIS-era (2005-2019). Val 2020-2021, test 2022-2024 untouched.",
        f"Sensor check evaluated on AMSR2-era data ({sensor_date_range or 'no 2025+ data'}, {sensor_n_days} days); out-of-training-distribution, indicative only.",
        "Promoted leads must beat tuned damped-persistence baseline with 95% CI excluding zero in both all-season and Nov-Mar on VIZ cells.",
        "CI computed with block bootstrap over 14+ day date blocks (never pools individual grid cells).",
        "IIEE at 15% threshold per Goessling et al. 2016, area-weighted, per-day averaged.",
        "IIEE rows published only when the per-lead physical sanity check passes "
        "(cell area near nominal 625 km^2, mismatches > 0, mismatch area < daily extent).",
    ]
    if sensor_metrics is None:
        caveats.append("No 2025+ data available in cache for sensor check.")
    else:
        caveats.append(
            f"Sensor check: {sensor_metrics['n_samples']} samples across "
            f"{sensor_metrics['overall']['window_years']}."
        )

    # Promotion caveats if any lead is promoted.
    if any(promoted.values()):
        promoted_leads = [l for l, v in promoted.items() if v]
        caveats.append(
            f"Promoted leads {promoted_leads}: test period is SSMIS-era (2005-2024), "
            f"RMSE gain vs tuned damped-persistence baseline is a few percent, "
            f"and AMSR2-era (2025+) results are indicative only."
        )

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "git_sha": git_sha,
        "data_source": "real",
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "train_years": sorted({d.year for d in train_dates}),
        "val_years": sorted({d.year for d in val_dates}),
        "test_years": sorted({d.year for d in test_dates}),
        "lead_days": list(REAL_LEAD_DAYS),
        "taus": {str(k): round(v, 2) for k, v in taus.items()},
        "record_length_days": record_length,
        "n_gaps": n_gaps,
        "sensor_date_range": sensor_date_range,
        "sensor_n_days": sensor_n_days,
        "rows": rows,
        "promoted": {"sic": promoted},
        "sensor_era": sensor_era,
        "bootstrap_info": bootstrap_info,
        "coverage": coverage_out,
        "coverage_per_lead_per_season": cov.get("per_lead_per_season", {}),
        "coverage_per_lead_per_sector": cov.get("per_lead_per_sector", {}),
        "taus_trained_on": {str(k): round(v, 2) for k, v in taus.items()},
        "evaluation_status": {
            "trained_on": "real",
            "operational_skill_validated": False,
            "used_in_routing": False,
            "promoted_leads": sorted(promoted.keys()) if any(promoted.values()) else [],
            "status": "real_data_training_complete",
        },
        "caveats": caveats,
    }


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        v = float(o)
        return None if not math.isfinite(v) else v
    if isinstance(o, np.ndarray):
        return [_json_default(x) for x in o.tolist()]
    if isinstance(o, (np.bool_,)):
        return bool(o)
    return str(o)


def _json_dump(obj: dict, path: Path) -> None:
    """Dump JSON with NaN/Infinity sanitized to null (valid JSON)."""
    def sanitize(v):
        if isinstance(v, dict):
            return {k: sanitize(x) for k, x in v.items()}
        if isinstance(v, list):
            return [sanitize(x) for x in v]
        if isinstance(v, float):
            return None if not math.isfinite(v) else v
        return v
    with open(path, "w", encoding="utf-8") as f:
        json.dump(sanitize(obj), f, indent=2, ensure_ascii=False)


if __name__ == "__main__":
    raise SystemExit(main())
