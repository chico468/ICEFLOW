#!/usr/bin/env python
"""
Phase 4 PART 1 — tracks-only iceberg physics hindcast.

Runs the RK4 drift physics (src/core/iceberg_tracker.py) on real BYU/NIC v6 iceberg
tracks using the synthetic EnvironmentModel (no ERA5 wind download — that is PART 2).
For each track, picks t0 start points and forecasts forward 1/3/7 days, then compares
the simulated position against the observed position at each lead. Reports median and
p90 great-circle error in km per lead.

No ML, no real wind data. Pure physics hindcast against observed truth.
"""
from __future__ import annotations

import json
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Any, Dict, List, Tuple

import numpy as np

REPO_ROOT = Path(__file__).resolve().parents[1]
if str(REPO_ROOT) not in sys.path:
    sys.path.insert(0, str(REPO_ROOT))

from src.core.environment import EnvironmentModel, get_environment
from src.core.geo import haversine_km
from src.core.iceberg_tracker import IcebergProfile, predict_iceberg_drift
from src.ml.iceberg_dataset import (
    DEFAULT_DATABASE_PATH,
    IcebergTrack,
    filter_moving_segments,
    load_database,
)

LEADS_DAYS = (1, 3, 7)
FORECAST_HOURS = max(LEADS_DAYS) * 24  # 168 h, covers every lead in one integration
ENSEMBLE_MEMBERS = 1  # control only for tracks-only physics hindcast
SAMPLE_TRACKS = 30  # full run over all 464 moving tracks timed out (>10 min); sample keeps PART 1 tractable
T0_STRIDE = 7
MAX_T0S_PER_TRACK = 8
HOUR_TOLERANCE = 6.0


def _median(values: List[float]) -> float:
    return float(np.median(values)) if values else float("nan")


def _p90(values: List[float]) -> float:
    return float(np.percentile(values, 90)) if values else float("nan")


def _track_position_at(track: IcebergTrack, target: date, start_idx: int) -> Tuple[float, float] | None:
    """Find observed position at exact target date. No approximate matching."""
    for j in range(start_idx + 1, len(track.dates)):
        if track.dates[j] == target:
            return float(track.lat[j]), float(track.lon[j])
        if track.dates[j] > target:
            break
    return None


def _hindcast_track(
    track: IcebergTrack,
    env: EnvironmentModel,
    results: Dict[int, Dict[str, List[float]]],
) -> int:
    """
    Hindcast one iceberg track: for each valid t0 (sampled at T0_STRIDE), run a single
    predict_iceberg_drift integration out to FORECAST_HOURS and evaluate every lead from that
    one trajectory, comparing the simulated position against the observed position at each lead.

    Returns number of (t0, lead) forecasts produced.
    """
    n_forecasts = 0
    t0_indices = list(range(0, len(track.dates), T0_STRIDE))[:MAX_T0S_PER_TRACK]
    for i in t0_indices:
        t0 = track.dates[i]
        lat_t0 = float(track.lat[i])
        lon_t0 = float(track.lon[i])
        if lat_t0 == 0.0 and lon_t0 == 0.0:
            continue
        if abs(lat_t0) > 90.0 or abs(lon_t0) > 180.0:
            continue

        berg = IcebergProfile(
            berg_id=track.berg_id,
            latitude=lat_t0,
            longitude=lon_t0,
            length_m=float(track.size_major_nm[i]) if np.isfinite(track.size_major_nm[i]) else 800.0,
            width_m=float(track.size_minor_nm[i]) if np.isfinite(track.size_minor_nm[i]) else 400.0,
        )

        result = predict_iceberg_drift(
            berg,
            forecast_hours=FORECAST_HOURS,
            time_step_hours=6,
            ensemble_members=ENSEMBLE_MEMBERS,
            t0_hours=0.0,
            environment=env,
            seed=26059,
        )

        # Index trajectory by hour for fast lead lookup.
        points_by_hour = {p.hour: p for p in result.trajectory}

        for lead in LEADS_DAYS:
            target = t0 + timedelta(days=lead)
            observed = _track_position_at(track, target, i)
            if observed is None:
                continue
            lat_obs, lon_obs = observed

            # Find trajectory point nearest to lead*24 hours, within tolerance.
            best_point = None
            best_hour_diff = float("inf")
            for hour in range(0, FORECAST_HOURS + 1, 6):
                if hour not in points_by_hour:
                    continue
                diff = abs(hour - lead * 24)
                if diff <= HOUR_TOLERANCE and diff < best_hour_diff:
                    best_hour_diff = diff
                    best_point = points_by_hour[hour]

            if best_point is None:
                continue

            err_km = haversine_km(
                best_point.latitude, best_point.longitude, lat_obs, lon_obs,
            )
            results[lead]["errors"].append(err_km)
            results[lead]["n_forecasts"] += 1
            results[lead]["berg_ids"].add(track.berg_id)
            n_forecasts += 1

    return n_forecasts


def main() -> int:
    print("=" * 92)
    print("PHASE 4 PART 1 — tracks-only iceberg physics hindcast")
    print("=" * 92)
    print()

    # Load environment (synthetic forcing, no ERA5 wind)
    env = get_environment()
    print(f"Environment: synthetic EnvironmentModel (seed={env.seed}, ref_doy={env.reference_doy})")
    print(f"Iceberg database: {DEFAULT_DATABASE_PATH}")
    print()

    # Load tracks
    t0 = time.perf_counter()
    tracks = load_database(DEFAULT_DATABASE_PATH)
    load_s = time.perf_counter() - t0
    print(f"Loaded {len(tracks)} raw iceberg tracks in {load_s:.1f}s")

    # Filter moving (drop grounded)
    moving = filter_moving_segments(tracks)
    print(f"After removing grounded (<0.1 kt): {len(moving)} moving tracks")
    print(f"Total position-days: {sum(len(t.dates) for t in moving)}")

    # Sample a representative subset for PART 1 (full run over all moving tracks is too slow).
    # Take first SAMPLE_TRACKS moving tracks (already sorted by berg_id, spans 1976-2022).
    sample = moving[:SAMPLE_TRACKS]
    print(f"PART 1 sample: {len(sample)} tracks (decision: per-track sparse t0 sampling at stride {T0_STRIDE}, "
          f"max {MAX_T0S_PER_TRACK} t0s/track, one {FORECAST_HOURS}h forecast per t0 covering all leads)")
    print()

    # Hindcast
    results: Dict[int, Dict[str, Any]] = {
        lead: {"errors": [], "n_forecasts": 0, "berg_ids": set()}
        for lead in LEADS_DAYS
    }

    t0 = time.perf_counter()
    total_forecasts = 0
    for ti, track in enumerate(sample):
        total_forecasts += _hindcast_track(track, env, results)
        if (ti + 1) % 10 == 0:
            print(f"  Processed {ti + 1}/{len(sample)} tracks, {total_forecasts} forecasts so far...", flush=True)
    hindcast_s = time.perf_counter() - t0
    print(f"\nHindcast complete in {hindcast_s:.1f}s — {total_forecasts} total (t0, lead) forecasts")
    print()

    # Report
    print("RESULTS — tracks-only physics hindcast (synthetic environment forcing)")
    print(f"{'lead(d)':>7s} | {'n_forecasts':>12s} | {'n_icebergs':>11s} | {'median_km':>10s} | {'p90_km':>10s}")
    print("-" * 60)
    report: Dict[str, Any] = {}
    for lead in LEADS_DAYS:
        r = results[lead]
        errs = r["errors"]
        med = _median(errs)
        p90 = _p90(errs)
        print(
            f"{lead:>7d} | {r['n_forecasts']:>12d} | {len(r['berg_ids']):>11d} | "
            f"{med:>10.2f} | {p90:>10.2f}"
        )
        report[str(lead)] = {
            "lead_days": lead,
            "n_forecasts": r["n_forecasts"],
            "n_icebergs": len(r["berg_ids"]),
            "median_error_km": med,
            "p90_error_km": p90,
        }

    report_path = REPO_ROOT / "models" / "eval" / "iceberg_hindcast_tracks_only.json"
    report_path.parent.mkdir(parents=True, exist_ok=True)
    full_report = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "phase": 4,
        "part": 1,
        "name": "tracks-only hindcast",
        "environment": "synthetic EnvironmentModel (no ERA5 wind)",
        "database": str(DEFAULT_DATABASE_PATH),
        "forecast_hours": FORECAST_HOURS,
        "leads": list(LEADS_DAYS),
        "n_raw_tracks": len(tracks),
        "n_moving_tracks": len(moving),
        "n_sample_tracks": len(sample),
        "results": report,
    }
    with open(report_path, "w") as f:
        json.dump(full_report, f, indent=2, default=str)
    print(f"\nReport written to {report_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
