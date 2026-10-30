#!/usr/bin/env python
"""
BE-3 iceberg dataset audit (Task 3).

Computes MEDIAN & P90 great-circle error (km) per lead (1, 3, 7) for three
baselines — no-movement, 3-day constant velocity, 7-day damped (0.5x) constant
velocity — on the VAL (2018) and TEST (2019-2022) splits separately, with
n_tracks and n_steps.  Also computes the median daily displacement of moving
segments and reports candidate data/implementation bugs.
"""
from __future__ import annotations

import json
import math
import sys
from collections import Counter
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    IcebergTrack,
    load_database,
    filter_moving_segments,
    _parse_float,
    _consolidate_day,
    _sensor_columns,
)
from src.core.geo import haversine_km
from src.core.constants import KM_PER_NM

VAL_YEAR = 2018
TEST_START_YEAR = 2019
TEST_END_YEAR = 2022
BASELINE_WINDOW = 3
DAMPING = 0.5
DAMPING_WINDOW = 7

DB_PATH = REPO_ROOT / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"


def _median(values: list[float]) -> float:
    if not values:
        return float("nan")
    return float(np.median(values))


def _p90(values: list[float]) -> float:
    if not values:
        return float("nan")
    return float(np.percentile(values, 90))


def _evaluate_baseline_for_split(
    tracks: list[IcebergTrack],
    start_date: date,
    end_date: date,
    leads: tuple[int, ...],
) -> dict:
    """Evaluate three baselines for one split.

    For each (iceberg, t0, lead):
      - no_movement: position held at t0
      - velocity_3d: 3-day constant velocity from last 3 days
      - velocity_7d_damped: 7-day constant velocity, damped 0.5x

    Returns a dict keyed by lead -> {baseline_name: {median, p90, n_steps, n_tracks}}
    """
    results: dict[int, dict] = {}

    for lead in leads:
        no_move_errors: list[float] = []
        vel3_errors: list[float] = []
        vel7damped_errors: list[float] = []
        berg_ids: set[str] = set()

        for track in tracks:
            if len(track.dates) < max(leads) + 2:
                continue

            for i in range(len(track.dates)):
                t0 = track.dates[i]
                if t0 < start_date or t0 > end_date:
                    continue
                if i < BASELINE_WINDOW:
                    continue

                # Find target date (exact match required for audit)
                target = t0 + timedelta(days=lead)
                found_idx = _find_exact_date(track.dates, target, i)
                if found_idx is None:
                    continue

                lat_t0 = float(track.lat[i])
                lon_t0 = float(track.lon[i])
                lat_t = float(track.lat[found_idx])
                lon_t = float(track.lon[found_idx])

                if abs(lat_t0) > 90 or abs(lon_t0) > 180:
                    continue
                if abs(lat_t) > 90 or abs(lon_t) > 180:
                    continue
                if lat_t0 == 0.0 and lon_t0 == 0.0:
                    continue
                if lat_t == 0.0 and lon_t == 0.0:
                    continue

                berg_ids.add(track.berg_id)

                # Baseline (a): no movement
                err_no_move = haversine_km(lat_t0, lon_t0, lat_t, lon_t)
                no_move_errors.append(err_no_move)

                # Baseline (b): 3-day constant velocity
                start_b = max(0, i - BASELINE_WINDOW)
                dt_days = (t0 - track.dates[start_b]).days
                if dt_days > 0:
                    vlat = (lat_t0 - float(track.lat[start_b])) / dt_days
                    vlon = float(track.lon[start_b])
                    # handle lon wrapping
                    dlon_raw = lon_t0 - vlon
                    dlon = ((dlon_raw + 180) % 360) - 180
                    vlon = dlon / dt_days
                else:
                    vlat, vlon = 0.0, 0.0

                pred_lat = lat_t0 + vlat * lead
                # predict lon with wrapping
                pred_lon = lon_t0 + vlon * lead
                pred_lon = ((pred_lon + 180) % 360) - 180
                pred_lat = max(-90, min(90, pred_lat))
                err_vel3 = haversine_km(pred_lat, pred_lon, lat_t, lon_t)
                vel3_errors.append(err_vel3)

                # Baseline (c): 7-day damped (0.5x)
                start_d = max(0, i - DAMPING_WINDOW)
                dt7 = (t0 - track.dates[start_d]).days
                if dt7 > 0:
                    dvlat = (lat_t0 - float(track.lat[start_d])) / dt7
                    dlon_raw = lon_t0 - float(track.lon[start_d])
                    dlon = ((dlon_raw + 180) % 360) - 180
                    dvlon = dlon / dt7
                else:
                    dvlat, dvlon = 0.0, 0.0

                pred_lat = lat_t0 + dvlat * lead * DAMPING
                pred_lon = lon_t0 + dvlon * lead * DAMPING
                pred_lon = ((pred_lon + 180) % 360) - 180
                pred_lat = max(-90, min(90, pred_lat))
                err_vel7 = haversine_km(pred_lat, pred_lon, lat_t, lon_t)
                vel7damped_errors.append(err_vel7)

        n_steps = len(no_move_errors)
        results[lead] = {
            "no_movement": {
                "median_km": _median(no_move_errors),
                "p90_km": _p90(no_move_errors),
                "n_steps": n_steps,
                "n_tracks": len(berg_ids),
            },
            "velocity_3d": {
                "median_km": _median(vel3_errors),
                "p90_km": _p90(vel3_errors),
                "n_steps": len(vel3_errors),
                "n_tracks": len(berg_ids),
            },
            "velocity_7d_damped": {
                "median_km": _median(vel7damped_errors),
                "p90_km": _p90(vel7damped_errors),
                "n_steps": len(vel7damped_errors),
                "n_tracks": len(berg_ids),
            },
        }

    return results


def _find_exact_date(dates: list[date], target: date, start: int) -> int | None:
    """Binary search for exact date, no tolerance."""
    lo, hi = start, len(dates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] == target:
            return mid
        if dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def _find_approx_date(dates: list[date], target: date, start: int) -> int | None:
    """Replica of the production _find_date (approximate, within 1 day)."""
    lo, hi = start, len(dates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] == target:
            return mid
        if dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    if lo < len(dates) and abs((dates[lo] - target).days) <= 1:
        return lo
    return None


def _compute_median_daily_displacement(tracks: list[IcebergTrack]) -> float:
    """Median daily displacement (km) across all moving segments."""
    displacements: list[float] = []
    for track in tracks:
        for i in range(len(track.dates) - 1):
            lat1, lon1 = float(track.lat[i]), float(track.lon[i])
            lat2, lon2 = float(track.lat[i+1]), float(track.lon[i+1])
            if lat1 == 0.0 and lon1 == 0.0:
                continue
            if lat2 == 0.0 and lon2 == 0.0:
                continue
            dist = haversine_km(lat1, lon1, lat2, lon2)
            if math.isfinite(dist) and dist > 0:
                displacements.append(dist)
    return float(np.median(displacements)) if displacements else float("nan")


def _audit_approximate_vs_exact_dates(
    tracks: list[IcebergTrack], leads: tuple[int, ...]
) -> dict:
    """Compare _find_exact_date vs _find_approx_date (production's _find_date).

    Reports how many lead predictions match a date that is NOT the exact
    target (i.e., the approximate match is off by ±1 day), which inflates errors.
    """
    exact_count = 0
    approx_mismatch = 0
    approx_total = 0

    for lead in leads:
        for track in tracks:
            if len(track.dates) < lead + 2:
                continue
            for i in range(len(track.dates)):
                t0 = track.dates[i]
                if i < BASELINE_WINDOW:
                    continue
                target = t0 + timedelta(days=lead)
                exact = _find_exact_date(track.dates, target, i)
                approx = _find_approx_date(track.dates, target, i)

                if exact is not None:
                    exact_count += 1
                if approx is not None:
                    approx_total += 1
                    if exact is None or track.dates[approx] != target:
                        approx_mismatch += 1

    return {
        "exact_matches_total": exact_count,
        "approx_matches_total": approx_total,
        "approx_off_by_day_total": approx_mismatch,
        "approx_false_positives": approx_mismatch,  # approx matched but exact didn't
    }


def _audit_antimeridian(tracks: list[IcebergTrack]) -> dict:
    """Count day-to-day longitude jumps > 300 degrees (antimeridian crossings)."""
    crossings = 0
    for track in tracks:
        for i in range(len(track.dates) - 1):
            lon1 = float(track.lon[i])
            lon2 = float(track.lon[i + 1])
            if lon1 == 0.0 and lon2 == 0.0:
                continue
            dlon = abs(lon2 - lon1)
            if dlon > 300:
                crossings += 1
    return {"antimeridian_day_jumps_gt300deg": crossings}


def _audit_duplicate_consecutive_positions(tracks: list[IcebergTrack]) -> dict:
    """Count consecutive positions that are identical (stuck position)."""
    dupes = 0
    for track in tracks:
        for i in range(len(track.dates) - 1):
            if track.lat[i] == track.lat[i+1] and track.lon[i] == track.lon[i+1]:
                if track.lat[i] != 0.0 or track.lon[i] != 0.0:
                    dupes += 1
    return {"duplicate_consecutive_positions": dupes}


def _audit_corrupt_dates(tracks: list[IcebergTrack]) -> dict:
    """Check for out-of-range years in dates."""
    bad_years = Counter()
    for track in tracks:
        for d in track.dates:
            if d.year < 1976 or d.year > 2022:
                bad_years[d.year] += 1
    return {"corrupt_year_counts": dict(bad_years)}


def main() -> int:
    print("=" * 92)
    print("BE-3 ICEBERG DATASET AUDIT (Task 3)")
    print("=" * 92)
    print()

    # 1. Load
    tracks = load_database(DB_PATH)
    print(f"Loaded {len(tracks)} raw iceberg tracks")

    # Corrupt dates
    corrupt = _audit_corrupt_dates(tracks)
    print(f"Corrupt years in raw tracks: {corrupt}")

    # 2. Filter
    moving = filter_moving_segments(tracks)
    print(f"After filter_moving_segments: {len(moving)} tracks")

    # 3. Daily displacement
    median_disp = _compute_median_daily_displacement(moving)
    print(f"\nMedian daily displacement of moving segments: {median_disp:.3f} km/day")

    # 4. Bug audits
    print("\n--- Bug audits ---")
    approx = _audit_approximate_vs_exact_dates(moving, ICELEAD_DAYS)
    print(f"Approximate _find_date vs exact: {approx}")

    am = _audit_antimeridian(moving)
    print(f"Antimeridian: {am}")

    dupes = _audit_duplicate_consecutive_positions(moving)
    print(f"Duplicate consecutive positions: {dupes}")

    # 5. Baseline evaluations
    print("\n--- Baseline evaluations (exact date matching) ---")

    val_start = date(VAL_YEAR, 1, 1)
    val_end = date(VAL_YEAR, 12, 31)
    test_start = date(TEST_START_YEAR, 1, 1)
    test_end = date(TEST_END_YEAR, 12, 31)

    val_results = _evaluate_baseline_for_split(moving, val_start, val_end, ICELEAD_DAYS)
    test_results = _evaluate_baseline_for_split(moving, test_start, test_end, ICELEAD_DAYS)

    report = {
        "dataset": "BYU/NIC consolidated Antarctic iceberg database v6",
        "n_raw_tracks": len(tracks),
        "n_moving_tracks": len(moving),
        "leads": list(ICELEAD_DAYS),
        "median_daily_displacement_moving_km": median_disp,
        "val": {"date_range": [str(val_start), str(val_end)], "results": val_results},
        "test": {"date_range": [str(test_start), str(test_end)], "results": test_results},
        "bug_audits": {
            "approx_date_mismatches": approx,
            "antimeridian_jumps": am,
            "duplicate_consecutive_positions": dupes,
            "corrupt_dates": corrupt,
        },
    }

    report_path = REPO_ROOT / "models" / "eval" / "iceberg_audit_report.json"
    with open(report_path, "w") as f:
        json.dump(report, f, indent=2, default=str)
    print(f"\nAudit report written to: {report_path}")

    # Print summary table
    print("\n--- Summary (VAL) ---")
    _print_results(val_results)
    print("\n--- Summary (TEST) ---")
    _print_results(test_results)

    return 0


def _print_results(results: dict) -> None:
    print(f"  {'lead':>4s} | {'baseline':>16s} | {'median_km':>12s} {'p90_km':>12s} {'n_steps':>8s} {'n_tracks':>9s}")
    print("  " + "-" * 68)
    for lead in sorted(results.keys()):
        for bl_name in ("no_movement", "velocity_3d", "velocity_7d_damped"):
            r = results[lead][bl_name]
            print(f"  {lead:>4d} | {bl_name:>16s} | {r['median_km']:>12.4f} {r['p90_km']:>12.4f} {r['n_steps']:>8d} {r['n_tracks']:>9d}")


if __name__ == "__main__":
    raise SystemExit(main())
