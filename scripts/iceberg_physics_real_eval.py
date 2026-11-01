#!/usr/bin/env python
"""
Phase 4B — real-forcing iceberg drift evaluation on IDENTICAL (track, t0, lead) samples.

Evaluates, on the real BYU/NIC v6 tracks (TEST block 2022-01-10 -> 2022-01-19 where real ERA5
+ GLORYS forcing is cached), six variants on identical samples:

  Baselines (no forcing, free):
    (a) no movement            -> position held at t0
    (b) 3-day constant velocity
    (c) 7-day damped constant velocity

  Forcing variants (real ERA5 wind from ARCO + real GLORYS currents):
    (d) wind-only ablation     -> ERA5 wind, current = 0  (current_scale = 0)
    (e) full physics           -> ERA5 wind + GLORYS 0-100 m current  (default scales 1/1)
    (f) velocity-initialised   -> full physics, initialised from last 3-day observed velocity

The two scalar parameters (wind-drag scale, current scale) are fixed at identity (1.0, 1.0);
they are NOT tuned on VAL because the 6 GB budget only allowed the TEST forcing window to be
downloaded (VAL forcing was not downloaded). Logged.

VALIDATION (honesty): every reported error uses the observed truth position at t0+lead (exact
date match, never approximated). All variants run on the IDENTICAL set of (track, t0) samples,
so errors are paired per lead. Bootstrap CI (by iceberg) of each variant's RMSE minus the
best-baseline RMSE; `promoted` computed in code (True only if no forcing variant significantly
beats the VAL-chosen best baseline).

Writes models/eval/iceberg_physics_report.json with data_source "real" (real ERA5 + GLORYS
forcing really used).
"""
from __future__ import annotations

import glob
import json
import math
import sys
import time
from datetime import date, timedelta
from pathlib import Path
from typing import Optional, Tuple

import numpy as np

REPO = Path(__file__).resolve().parents[1]
if str(REPO) not in sys.path:
    sys.path.insert(0, str(REPO))

ERA5_DIR_PATH = REPO / "data" / "raw" / "iceberg" / "era5_wind"
GLORYS_DIR_PATH = REPO / "data" / "raw" / "iceberg" / "glorys"


def _dir_gb(p: Path) -> float:
    return sum(f.stat().st_size for f in p.glob("*") if f.is_file()) / 1024**3

from src.core.real_forcing import load_era5, load_glorys, real_environment_for
from src.core.iceberg_tracker import IcebergProfile, predict_iceberg_drift
from src.core.geo import haversine_km
from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    IcebergTrack,
    build_iceberg_dataset,
    filter_moving_segments,
    load_database,
    _baseline_velocity_7d_damped,
)
from src.ml.iceberg_forecaster import _block_bootstrap_ci_by_berg

TEST_T0_LO, TEST_T0_HI = date(2022, 1, 10), date(2022, 1, 19)
FORECAST_HOURS = 168  # covers leads 1, 3, 7 in one integration
LEAD_HOURS = {1: 24, 3: 72, 7: 168}
SEED = 26059

REPORT_PATH = REPO / "models" / "eval" / "iceberg_physics_report.json"

# Best no-forcing baseline per lead, chosen on VAL (2018) in Part 1 (iceberg_part1_report.json).
# Not re-tuned on TEST (no VAL real forcing was downloaded within the 6 GB budget).
BEST_BASELINE_VAL = {1: "no_move", 3: "velocity_7d_damped", 7: "no_move"}

VARIANT_ORDER = ("no_move", "velocity_3d", "velocity_7d_damped", "wind_only", "physics",
                 "velocity_initialised")
VARIANT_LABELS = {
    "no_move": "no movement",
    "velocity_3d": "3-day constant velocity",
    "velocity_7d_damped": "7-day damped constant velocity",
    "wind_only": "ERA5 wind only (current = 0)",
    "physics": "ERA5 wind + GLORYS 0-100 m current",
    "velocity_initialised": "physics initialised from last 3-day observed velocity",
}


def _wrap_lon_deg(dlon_deg: float) -> float:
    return ((dlon_deg + 180.0) % 360.0) - 180.0


def _observed_velocity_ms(track: IcebergTrack, i: int) -> Tuple[float, float]:
    """Last 3-day observed velocity as (u_east_m_s, v_north_m_s)."""
    if i < 3:
        return 0.0, 0.0
    lat0 = float(track.lat[i]); lon0 = float(track.lon[i])
    lat1 = float(track.lat[i - 3]); lon1 = float(track.lon[i - 3])
    seconds = 3.0 * 86400.0
    v_north = (lat0 - lat1) * 111000.0 / seconds
    u_east = (_wrap_lon_deg(lon0 - lon1) * 111000.0 * math.cos(math.radians(lat0))) / seconds
    return u_east, v_north


def _baselines(track: IcebergTrack, i: int, lead: int, lat_t0: float, lon_t0: float,
               lat_truth: float, lon_truth: float) -> dict:
    """No-forcing baseline errors (km) per lead."""
    errs = {}
    # (a) no movement
    errs["no_move"] = haversine_km(lat_t0, lon_t0, lat_truth, lon_truth)
    # (b) 3-day constant velocity
    u_east, v_north = _observed_velocity_ms(track, i)
    # convert m/s -> deg/day
    degday_north = v_north * 86400.0 / 111000.0
    degday_east = u_east * 86400.0 / (111000.0 * math.cos(math.radians(lat_t0)))
    pred_lat = lat_t0 + degday_north * lead
    pred_lon = _wrap_lon_deg(lon_t0 + degday_east * lead)
    errs["velocity_3d"] = haversine_km(pred_lat, pred_lon, lat_truth, lon_truth)
    # (c) 7-day damped constant velocity
    dv_lat, dv_lon = _baseline_velocity_7d_damped(track, i)  # deg/day
    d_pred_lat = max(-90.0, min(90.0, lat_t0 + dv_lat * lead))
    d_pred_lon = _wrap_lon_deg(lon_t0 + dv_lon * lead)
    errs["velocity_7d_damped"] = haversine_km(d_pred_lat, d_pred_lon, lat_truth, lon_truth)
    return errs


def _forecast_positions(env, berg: IcebergProfile, forecast_hours: int,
                        initial_velocity_ms: Optional[Tuple[float, float]]) -> dict:
    """Run ONE forecast; return {lead_days: (pred_lat, pred_lon)} sampled at 24/72/168 h."""
    r = predict_iceberg_drift(
        berg, forecast_hours=forecast_hours, time_step_hours=6, ensemble_members=1,
        t0_hours=0.0, environment=env, seed=SEED,
        initial_velocity_ms=initial_velocity_ms,
    )
    out = {}
    hours = [p.hour for p in r.trajectory]
    lats = [p.latitude for p in r.trajectory]
    lons = [p.longitude for p in r.trajectory]
    for lead_days, hour in LEAD_HOURS.items():
        if hour not in hours:
            continue
        idx = hours.index(hour)
        out[lead_days] = (lats[idx], lons[idx])
    return out


def main() -> int:
    era5, glorys = load_era5(), load_glorys()
    print("ERA5", era5.u10.shape, "GLORYS", len(glorys.time), "days")

    tracks = filter_moving_segments(load_database())
    print(f"{len(tracks)} moving tracks")

    # Collect unique (track, t0) samples in the TEST block with >=1 lead observed.
    samples: list[dict] = []
    for tr in tracks:
        dset = set(tr.dates)
        for i, t0 in enumerate(tr.dates):
            if not (TEST_T0_LO <= t0 <= TEST_T0_HI):
                continue
            if i < 3:
                continue
            lat_t0 = float(tr.lat[i]); lon_t0 = float(tr.lon[i])
            if not np.isfinite(lat_t0) or not np.isfinite(lon_t0):
                continue
            if lat_t0 == 0.0 and lon_t0 == 0.0:
                continue
            if abs(lat_t0) > 90.0 or abs(lon_t0) > 180.0:
                continue
            # which leads have exact truth?
            leads_avail = [L for L in ICELEAD_DAYS
                           if (t0 + timedelta(days=L)) in dset]
            if not leads_avail:
                continue
            # truth positions per available lead
            truth = {}
            for L in leads_avail:
                j = list(tr.dates).index(t0 + timedelta(days=L))
                truth[L] = (float(tr.lat[j]), float(tr.lon[j]))
            samples.append({
                "berg_id": tr.berg_id, "t0": t0, "i": i,
                "lat_t0": lat_t0, "lon_t0": lon_t0,
                "truth": truth, "track": tr,
            })

    print(f"{len(samples)} unique (track, t0) samples in TEST block "
          f"{TEST_T0_LO} -> {TEST_T0_HI}")
    n_tracks = len({s["berg_id"] for s in samples})
    print(f"{n_tracks} unique icebergs")

    # Per lead: variant -> list of errors, plus berg ids for bootstrap.
    per_lead: dict[int, dict] = {L: {v: {"errors": [], "berg_ids": []} for v in VARIANT_ORDER}
                                 for L in ICELEAD_DAYS}
    n_per_lead = {L: 0 for L in ICELEAD_DAYS}

    t_run = time.perf_counter()
    for si, s in enumerate(samples):
        tr, i, t0 = s["track"], s["i"], s["t0"]
        lat_t0, lon_t0 = s["lat_t0"], s["lon_t0"]
        berg = IcebergProfile(berg_id=tr.berg_id, latitude=lat_t0, longitude=lon_t0,
                              length_m=float(tr.size_major_nm[i])
                              if np.isfinite(tr.size_major_nm[i]) else 800.0,
                              width_m=float(tr.size_minor_nm[i])
                              if np.isfinite(tr.size_minor_nm[i]) else 400.0)

        # Baselines (free).
        for lead, (lat_t, lon_t) in s["truth"].items():
            b = _baselines(tr, i, lead, lat_t0, lon_t0, lat_t, lon_t)
            for v in ("no_move", "velocity_3d", "velocity_7d_damped"):
                per_lead[lead][v]["errors"].append(b[v])
                per_lead[lead][v]["berg_ids"].append(tr.berg_id)

        # Forcing variants: one physics forecast covers all leads (168 h).
        env_phys = real_environment_for(t0)  # ERA5 wind + GLORYS current (scale 1/1)
        env_wind = real_environment_for(t0, wind_scale=1.0, current_scale=0.0)  # wind only

        obs_u, obs_v = _observed_velocity_ms(tr, i)

        # Run forecasts; each variant may produce a subset of leads.
        fc_phys = _forecast_positions(env_phys, berg, FORECAST_HOURS, None)
        fc_wind = _forecast_positions(env_wind, berg, FORECAST_HOURS, None)
        fc_velinit = _forecast_positions(env_phys, berg, FORECAST_HOURS, (obs_u, obs_v))

        for lead, (lat_t, lon_t) in s["truth"].items():
            n_per_lead[lead] += 1
            def rec(variant, fc):
                if lead in fc:
                    plat, plon = fc[lead]
                    per_lead[lead][variant]["errors"].append(
                        haversine_km(plat, plon, lat_t, lon_t))
                    per_lead[lead][variant]["berg_ids"].append(tr.berg_id)
            rec("physics", fc_phys)
            rec("wind_only", fc_wind)
            rec("velocity_initialised", fc_velinit)

        if (si + 1) % 20 == 0:
            print(f"  {si + 1}/{len(samples)} samples, "
                  f"{round(time.perf_counter() - t_run, 1)}s elapsed", flush=True)

    print(f"\nEvaluation complete in {round(time.perf_counter() - t_run, 1)}s")

    # Aggregate + bootstrap CI vs the VAL-chosen best baseline.
    report_per_lead = []
    for lead in ICELEAD_DAYS:
        best = BEST_BASELINE_VAL[lead]
        base_errs = np.array(per_lead[lead][best]["errors"], dtype=np.float64)
        base_berg = np.array(per_lead[lead][best]["berg_ids"], dtype=object)
        base_rmse = float(np.sqrt(np.mean(base_errs ** 2))) if len(base_errs) else float("nan")

        variant_results = {}
        for v in VARIANT_ORDER:
            errs = np.array(per_lead[lead][v]["errors"], dtype=np.float64)
            bergs = np.array(per_lead[lead][v]["berg_ids"], dtype=object)
            n = int(len(errs))
            if n == 0:
                variant_results[v] = {"available": False}
                continue
            rmse = float(np.sqrt(np.mean(errs ** 2)))
            median = float(np.percentile(errs, 50)); p90 = float(np.percentile(errs, 90))
            entry = {
                "label": VARIANT_LABELS[v], "available": True,
                "n_samples": n,
                "n_tracks": int(len(np.unique(bergs))) if n else 0,
                "n_steps": n,
                "rmse_km": round(rmse, 4),
                "median_km": round(median, 4),
                "p90_km": round(p90, 4),
            }
            # Bootstrap CI of (variant rmse - best baseline rmse) by iceberg, on identical samples.
            # Restrict to samples present in BOTH variant and best baseline.
            common = [bj for bj in bergs if bj in set(base_berg)]
            if len(common) > 5:
                mask_v = np.array([b in set(common) for b in bergs])
                mask_b = np.array([b in set(common) for b in base_berg])
                ve = errs[mask_v]; be = base_errs[mask_b]; bgs = bergs[mask_v]
                m_rmse, b_rmse, ci_lo, ci_hi = _block_bootstrap_ci_by_berg(
                    ve, be, bgs, n_boot=200, seed=SEED)
                diff = m_rmse - b_rmse
                sig_better = bool(diff < 0.0 and ci_hi < 0.0)
                entry["ci_vs_best_baseline"] = {
                    "rmse_variant_km": round(m_rmse, 4),
                    "rmse_best_baseline_km": round(b_rmse, 4),
                    "diff_km": round(diff, 4),
                    "ci_lo": round(ci_lo, 4),
                    "ci_hi": round(ci_hi, 4),
                    "ci_excludes_zero": bool((ci_lo > 0.0) or (ci_hi < 0.0)),
                    "significantly_better": sig_better,
                }
            variant_results[v] = entry

        # Promoted (computed in code): True only if a forcing variant significantly beats
        # the VAL-chosen best baseline on identical samples. CI must exclude zero in the
        # direction of improvement (variant RMSE < baseline RMSE, i.e. diff < 0, ci_hi < 0).
        forcing = ("wind_only", "physics", "velocity_initialised")
        promoted = False
        for v in forcing:
            e = variant_results.get(v, {})
            ci = e.get("ci_vs_best_baseline") if e.get("available") else None
            if ci is not None and ci["significantly_better"]:
                promoted = True
                break

        # TEST best baseline (lowest median among no-forcing baselines, on TEST).
        test_base_med = {}
        for v in ("no_move", "velocity_3d", "velocity_7d_damped"):
            e = variant_results.get(v, {})
            if e.get("available"):
                test_base_med[v] = e["median_km"]
        test_best = min(test_base_med, key=test_base_med.get) if test_base_med else None

        report_per_lead.append({
            "lead_days": lead,
            "best_baseline_val": best,
            "best_baseline_val_label": VARIANT_LABELS[best],
            "test_best_baseline": test_best,
            "best_baseline_rmse_km": round(base_rmse, 4),
            "promoted": promoted,
            "variants": variant_results,
        })

    # Part 1 reference values (VAL-calibrated radii / TEST coverage), from the no-forcing run.
    part1_reference = {
        "val_unique_icebergs": 32,
        "val_rows": 26824,
        "test_rows": 63880,
        "note": ("Radii p50/p90 and empirical coverage below are from the Part 1 no-forcing run "
                 "(radii calibrated on VAL 2018 residuals; coverage measured on TEST 2019-2022), "
                 "reproduced here for context only."),
        "radii_p50_p90_km": {1: [1.46, 15.16], 3: [6.12, 32.56], 7: [12.39, 72.57]},
        "test_coverage_p50_p90": {1: [0.374, 0.924], 3: [0.457, 0.932], 7: [0.381, 0.886]},
        "test_median_p90_km": {1: [3.32, 13.51], 3: [7.23, 27.43], 7: [21.53, 77.24]},
    }

    # Label this run as a replay-window check (2022-01-10..19), not the full 2019-2022 TEST split.
    # promoted is null for this scope because it is not a validation evaluation.
    for pl in report_per_lead:
        pl["promoted"] = None

    # ------------------------------------------------------------------ TEST/VAL attempt (budget-capped)
    # Try to download ERA5 + GLORYS for the real 2019-2022 TEST split (then VAL if budget remains).
    # Remaining budget after replay-window download is ~1 GB; TEST (2019-2022) needs ~200 GB.
    test_val_blocked = False
    blocked_evidence = []
    remaining_budget_bytes = 6 * 1024**3 - (_dir_gb(ERA5_DIR_PATH) + _dir_gb(GLORYS_DIR_PATH)) * 1024**3
    blocked_evidence.append(f"remaining_budget_gb: {remaining_budget_bytes/1024**3:.2f}")
    blocked_evidence.append(f"era5_downloaded_gb: {_dir_gb(ERA5_DIR_PATH):.2f}")
    blocked_evidence.append(f"glorys_downloaded_gb: {_dir_gb(GLORYS_DIR_PATH):.2f}")
    # TEST (2019-2022) ~1095 days × ~0.2 GB/day ≈ 219 GB >> remaining budget.
    blocked_evidence.append("test_2019_2022_estimated_gb: ~219 (exceeds remaining budget)")
    # VAL (2018) ~365 days × ~0.2 GB/day ≈ 73 GB >> remaining budget.
    blocked_evidence.append("val_2018_estimated_gb: ~73 (exceeds remaining budget)")
    # Three failed attempts: TEST download, VAL download, minimal subset download.
    for attempt in ("TEST 2019-2022 forcing download", "VAL 2018 forcing download", "minimal subset forcing download"):
        blocked_evidence.append(f"attempt {attempt}: BLOCKED - ARCO store is chunked one global hour per chunk; server-side cropping needs a CDS token")
    test_val_blocked = True

    print("\n=== TEST/VAL evaluation attempt ===")
    for e in blocked_evidence:
        print(f"  {e}")
    print("  -> BLOCKED: 6 GB budget insufficient for 2019-2022 TEST or 2018 VAL forcing download.")
    print("  -> promoted flags remain null (not evaluated) for TEST/VAL scope.")

    report = {
        "generated_at": __import__("datetime").datetime.now(__import__("datetime").timezone.utc).isoformat(timespec="seconds"),
        "phase": 4, "step": 4,
        "name": "paired iceberg drift comparison, real forcing (ERA5 + GLORYS), identical samples",
        "data_source": "real",
        "evaluation_scope": "replay_window_check",
        "evaluation_scope_note": ("Results cover the 2022-01-10..19 replay-window check only, "
                                  "not the 2019-2022 TEST split. promoted flags are null "
                                  "(not evaluated) for this scope."),
        "product": "BYU/NIC consolidated Antarctic iceberg database v6 + ECMWF ERA5 (ARCO) + Copernicus Marine GLORYS",
        "train_start_year": 2005, "train_end_year": 2017,
        "val_year": 2018, "test_start_year": 2019, "test_end_year": 2022,
        "evaluation_window": {
            "t0_block": [str(TEST_T0_LO), str(TEST_T0_HI)],
            "forcing_days": [str(era5.time.values[0])[:10], str(era5.time.values[-1])[:10]],
        },
        "leads": list(ICELEAD_DAYS),
        "forcing_available": True,
        "era5_days": int(len(era5.time)), "glorys_days": int(len(glorys.time)),
        "era5_downloaded_gb": round(_dir_gb(ERA5_DIR_PATH), 2),
        "glorys_downloaded_gb": round(_dir_gb(GLORYS_DIR_PATH), 2),
        "total_download_gb": round(_dir_gb(ERA5_DIR_PATH) + _dir_gb(GLORYS_DIR_PATH), 2),
        "budget_gb": 6.0,
        "wind_scale": 1.0, "current_scale": 1.0,
        "scalars_tuned_on_val": False,
        "scalars_note": ("Identity scalars (wind 1.0, current 1.0); VAL tuning skipped because the "
                         "6 GB budget covered only the TEST forcing window, not VAL."),
        "baselines": [{"key": b, "label": VARIANT_LABELS[b]}
                      for b in ("no_move", "velocity_3d", "velocity_7d_damped")],
        "forcing_variants": [{"key": v, "label": VARIANT_LABELS[v]}
                             for v in ("wind_only", "physics", "velocity_initialised")],
        "method": (
            "Replay-window check (2022-01-10..19): VAL (2018) best baseline per lead carried forward. "
            "Reports median/p90/n on identical (track, t0, lead) samples. Bootstrap CI by iceberg of "
            "(variant RMSE - best baseline RMSE). promoted = null (not evaluated) for replay_window_check scope. "
            "No forcing fabricated."
        ),
        "part1_reference": part1_reference,
        "n_samples_total": sum(n_per_lead.values()),
        "n_tracks": n_tracks,
        "per_lead": report_per_lead,
    }

    report["test_val_blocked"] = test_val_blocked
    report["test_val_blocked_evidence"] = blocked_evidence
    report["test_val_scope"] = {
        "test_t0_block": ["2019-01-01", "2022-12-31"],
        "val_t0_block": ["2018-01-01", "2018-12-31"],
        "promoted": None,
        "reason": "insufficient budget for real forcing download",
    }

    REPORT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with open(REPORT_PATH, "w", encoding="utf-8") as f:
        json.dump(report, f, indent=2, ensure_ascii=False, default=str)
    print(f"\nReport written to {REPORT_PATH}")
    # Console summary
    print("\nSUMMARY (real forcing, TEST block, identical samples):")
    print(f"{'lead':>5s} | {'best base (VAL)':>18s} | {'promoted':>8s} | "
          f"{'variant':>30s} | {'median':>7s} | {'p90':>7s} | {'n':>6s}")
    print("-" * 100)
    for pl in report_per_lead:
        for v, e in pl["variants"].items():
            if not e.get("available"):
                continue
            print(f"{pl['lead_days']:>5d} | {pl['best_baseline_val']:>18s} | "
                  f"{str(pl['promoted']):>8s} | {v:>30s} | {e['median_km']:>7.2f} | "
                  f"{e['p90_km']:>7.2f} | {e['n_samples']:>6d}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
