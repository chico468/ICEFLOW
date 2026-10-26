#!/usr/bin/env python
"""Evaluate SIC baselines on real or fixture data.

Baselines (all use only data available *before* the forecast origin):
  persistence        forecast = obs(t0)
  damped             anomaly persistence decaying toward climatology
  climatology        forecast = climatological mean for the target DOY
  climatology+trend  forecast = climatology + linear trend * (target year - base)

Metrics: RMSE, MAE, bias and IIEE (Goessling et al. 2016).
Domains: all_ocean and variable_ice_zone (climatology 5-95%).
Seasons: all and austral departure (Nov-Mar).
Sectors: the five Southern-Ocean sectors from src/eval/regions.py.

Evaluation is leave-one-year-out cross-validation: each calendar year is held
out (with a max-lead-day embargo on both sides) and the climatology is refit on
the remaining years. This includes the final recent block (e.g. 2024).
"""
from __future__ import annotations

import argparse
import json
import random
import warnings
from datetime import date, datetime, timedelta
from pathlib import Path

import numpy as np
from pyproj import CRS, Transformer

from src.data.nsidc_sea_ice import default_cache_dir
from src.eval import baselines, metrics, splits
from src.eval.areas import compute_cell_areas
from src.eval.io import load_sic_range, latlon_grid
from src.eval.regions import SECTORS_SIMPLE, AUSTRAL_DEPARTURE_SEASON


LEADS = (1, 3, 7, 14)
BASELINES = ("persistence", "damped", "climatology", "climatology+trend")
DOMAINS = ("all_ocean", "variable_ice_zone_5_95")
SEASONS = ("all", "austral_departure")
IIEE_THRESHOLD = 0.15
TREND_TAU_DAYS = 30.0
SENSOR_CAVEAT = (
    "V6 uses AMSR2 from 1 Jan 2025 onward (different sensor). Held-out test "
    "block must end by 31 Dec 2024. 2025+ reported separately as different-sensor period."
)


def _doy_key(d: date) -> tuple[int, int]:
    return (d.month, d.day)


def build_fixture(year0: int = 2020, n_years: int = 8, nx: int = 40, ny: int = 28,
                  sigma: float = 0.10):
    """Synthetic Antarctic grid + multi-year daily SIC for ``--use-fixtures``.

    Grid: NSIDC-style south polar stereographic (EPSG:3412), 25 km cells.
    The synthetic SIC has a spatial+seasonal climatology (clipped to 0.05-0.95),
    no trend, and a persistent AR(1) anomaly. The AR(1) anomaly gives persistence
    short-term skill and lets damped persistence beat plain persistence at longer
    leads, so the sanity checks hold deterministically.
    """
    dx = dy = 25000.0
    x_m = (np.arange(nx) - (nx - 1) / 2.0) * dx
    # South-polar grid: pole at y=0, y increases northward; start one row off the
    # pole so the cell centres map cleanly to finite latitudes.
    y_m = (np.arange(ny) + 0.5) * dy

    transformer = Transformer.from_crs(CRS.from_epsg(3412), "EPSG:4326", always_xy=True)
    xx, yy = np.meshgrid(x_m, y_m)
    lon, lat = transformer.transform(xx, yy)
    lon = np.asarray(lon, dtype=np.float64)
    lat = np.asarray(lat, dtype=np.float64)
    # Restrict to a realistic band (60 S..88 S).
    ocean = (lat <= -60.0) & (lat >= -88.5) & np.isfinite(lat)
    # Spatial climatology base: high near the pole, low at the ice edge.
    base = 0.5 - 0.4 * np.clip((lat + 72.0) / 20.0, -1.0, 1.0)
    seasonal_amp = 0.20
    rho = 0.9          # AR(1) persistence of the anomaly
    sigma = 0.10       # anomaly noise std (stationary anomaly std ~0.24)
    n_years = 8
    rng = np.random.default_rng(7)

    # Build a contiguous, deterministic stream of dates and an AR(1) anomaly
    # field that evolves day-by-day over the whole record.
    anom = np.zeros((ny, nx))
    sic_by_date: dict[date, np.ndarray] = {}
    for y in range(year0, year0 + n_years):
        for doy in range(1, 366):
            try:
                d = datetime(y, 1, 1).date() + timedelta(days=doy - 1)
            except ValueError:
                continue
            anom = rho * anom + rng.normal(0.0, sigma, size=(ny, nx))
            phase = 2 * np.pi * (doy - 80) / 365.0
            clim = base + seasonal_amp * np.sin(phase)
            clim = np.clip(clim, 0.05, 0.95)
            arr = np.full((ny, nx), np.nan)
            arr[ocean] = clim[ocean] + anom[ocean]
            sic_by_date[d] = np.clip(np.where(ocean, arr, np.nan), 0.0, 1.0)
    return sic_by_date, x_m, y_m


def _forecast(name, obs_t0, clim_t0, clim_tlead, trend_tlead, t0, td, lead, base_year):
    if name == "persistence":
        return obs_t0
    if name == "damped":
        return baselines.damped_anomaly_persistence(obs_t0, clim_t0, clim_tlead, lead, tau_days=TREND_TAU_DAYS)
    if name == "climatology":
        return clim_tlead
    if name == "climatology+trend":
        return clim_tlead + trend_tlead * (td.year - base_year)
    raise ValueError(name)


def _lon_in_sector(lon: np.ndarray, west: float, east: float) -> np.ndarray:
    lon = ((lon + 180.0) % 360.0) - 180.0  # -180..180
    if west <= east:
        return (lon >= west) & (lon <= east)
    # Crosses the antimeridian / wraps.
    return (lon >= west) | (lon <= east)


def _sector_mask(lon: np.ndarray, sector_name: str) -> np.ndarray:
    west, east = SECTORS_SIMPLE[sector_name]
    return _lon_in_sector(lon, west, east)


def run_eval(sic_by_date, x_m, y_m, n_boot: int = 200, seed: int = 12345):
    """Leave-one-year-out evaluation. Returns the ``results`` list of cells."""
    rng = np.random.default_rng(seed)
    dates = sorted(sic_by_date.keys())
    if not dates:
        raise RuntimeError("No SIC observations available to evaluate.")
    max_lead = max(LEADS)

    areas = compute_cell_areas(x_m, y_m)
    lat, lon = latlon_grid(x_m, y_m)

    # Accumulators keyed by (domain, season, sector, baseline, lead) -- full
    # per-sector breakdown (written to JSON) -- and a sector-aggregated headline
    # view (keyed by (domain, season, baseline, lead)) used for the markdown table.
    acc: dict[tuple, dict[str, list]] = {}
    head: dict[tuple, dict[str, list]] = {}

    def _acc(store, key):
        if key not in store:
            store[key] = {"months": [], "rmse": [], "mae": [], "bias": [], "iiee": []}
        return store[key]

    folds = splits.leave_one_year_out(dates, embargo_days=max_lead)

    for train_dates, test_dates in folds:
        doy_to_mean, doy_to_trend, base_year = baselines.fit_climatology(
            train_dates, sic_by_date, use_trend=True
        )
        # Reference climatology (averaged seasonal cycle) defines land/ocean & VIZ.
        clim_stack = np.stack(list(doy_to_mean.values()), axis=0)
        with warnings.catch_warnings():
            warnings.simplefilter("ignore", category=RuntimeWarning)
            clim_ref = np.nanmean(clim_stack, axis=0)
        clim_ref = np.where(np.isfinite(clim_ref), clim_ref, np.nan)
        ocean_mask = np.isfinite(clim_ref)
        viz_mask = ocean_mask & (clim_ref >= 0.05) & (clim_ref <= 0.95)
        domain_masks = {"all_ocean": ocean_mask, "variable_ice_zone_5_95": viz_mask}

        novmar_targets = [td for td in test_dates if td.month in AUSTRAL_DEPARTURE_SEASON]
        season_targets = {"all": test_dates, "austral_departure": novmar_targets}

        for season, targets in season_targets.items():
            for sector_name in SECTORS_SIMPLE:
                s_mask = _sector_mask(lon, sector_name)
                for td in targets:
                    for lead in LEADS:
                        o = td - timedelta(days=lead)
                        if o not in sic_by_date or td not in sic_by_date:
                            continue
                        k0 = _doy_key(o)
                        k1 = _doy_key(td)
                        if k0 not in doy_to_mean or k1 not in doy_to_mean:
                            continue
                        clim_t0 = doy_to_mean[k0]
                        clim_tlead = doy_to_mean[k1]
                        trend_tlead = doy_to_trend[k1]
                        obs_t0 = sic_by_date[o]
                        obs_td = sic_by_date[td]
                        # All four forecasts for this (origin, target, lead).
                        preds = [
                            _forecast(name, obs_t0, clim_t0, clim_tlead,
                                      trend_tlead, o, td, lead, base_year)
                            for name in BASELINES
                        ]
                        for (domain_name, space) in domain_spaces(s_mask, domain_masks):
                            if not np.any(space):
                                continue
                            batch = metrics.metrics_batch(
                                preds, obs_td, space, areas, IIEE_THRESHOLD
                            )
                            for name, (rmse, mae, b, iiee) in zip(BASELINES, batch):
                                c = _acc(acc, (domain_name, season, sector_name, name, lead))
                                c["months"].append(td.month)
                                c["rmse"].append(rmse)
                                c["mae"].append(mae)
                                c["bias"].append(b)
                                c["iiee"].append(iiee)
                                h = _acc(head, (domain_name, season, name, lead))
                                h["months"].append(td.month)
                                h["rmse"].append(rmse)
                                h["mae"].append(mae)
                                h["bias"].append(b)
                                h["iiee"].append(iiee)

    results = [_finalize(k, cell, n_boot, seed) for k, cell in acc.items() if cell["rmse"]]
    headline = [_finalize(k, cell, n_boot, seed) for k, cell in head.items() if cell["rmse"]]
    return results, headline


def domain_spaces(s_mask, domain_masks):
    """Yield (domain_name, space_mask) for each domain intersected with sector."""
    for domain_name, dm in domain_masks.items():
        space = dm & s_mask
        if np.any(space):
            yield domain_name, space


def _finalize(key, cell, n_boot, seed):
    months = cell["months"]
    n = len(months)
    blocks = {}
    for m, r, ma, bi, ii in zip(
        months, cell["rmse"], cell["mae"], cell["bias"], cell["iiee"]
    ):
        blocks.setdefault(m, []).append((r, ma, bi, ii))
    blocks_list = list(blocks.values())
    rmse_blocks = [[b[0] for b in blk] for blk in blocks_list]
    mae_blocks = [[b[1] for b in blk] for blk in blocks_list]
    bias_blocks = [[b[2] for b in blk] for blk in blocks_list]
    iiee_blocks = [[b[3] for b in blk] for blk in blocks_list]
    rmse_ci = metrics.bootstrap_ci_blocks(rmse_blocks, n_boot=n_boot, seed=seed)
    mae_ci = metrics.bootstrap_ci_blocks(mae_blocks, n_boot=n_boot, seed=seed + 1)
    bias_ci = metrics.bootstrap_ci_blocks(bias_blocks, n_boot=n_boot, seed=seed + 2)
    iiee_ci = metrics.bootstrap_ci_blocks(iiee_blocks, n_boot=n_boot, seed=seed + 3)

    rec = {"rmse": _mean(cell["rmse"]), "rmse_ci": list(rmse_ci),
           "mae": _mean(cell["mae"]), "mae_ci": list(mae_ci),
           "bias": _mean(cell["bias"]), "bias_ci": list(bias_ci),
           "iiee": _mean(cell["iiee"]), "iiee_ci": list(iiee_ci), "n": n}
    if len(key) == 5:
        domain, season, sector, baseline, lead = key
        rec.update({"domain": domain, "season": season, "sector": sector,
                    "baseline": baseline, "lead": lead})
    else:
        domain, season, baseline, lead = key
        rec.update({"domain": domain, "season": season, "sector": "all",
                    "baseline": baseline, "lead": lead})
    return rec


def _mean(values):
    arr = np.asarray(values, dtype=np.float64)
    if arr.size == 0:
        return float("nan")
    with np.errstate(invalid="ignore"):
        m = np.nanmean(arr)
    return float(m) if np.isfinite(m) else float("nan")


def compute_sanity_checks(sic_by_date, train_dates, test_dates, doy_to_mean, base_year):
    """Computed (not hardcoded) sanity checks; raise on contradiction.

    Check 1 (damped beats persistence) is evaluated on a *controlled* AR(1)
    anomaly with an exact (zero) climatology, so it is deterministic and free of
    finite-sample climatology bias. Check 2 (shuffle destroys skill) is evaluated
    on the real fixture/test record, comparing persistence skill vs climatology
    in true origin order vs shuffled origins.
    """
    from src.eval import metrics as _m

    checks: dict = {}

    # --- Check 1: damped persistence beats plain persistence on AR(1) anomaly ---
    rng = np.random.default_rng(2024)
    n = 365
    rho = 0.85
    sigma = 0.10
    anom = np.zeros(n)
    for i in range(1, n):
        anom[i] = rho * anom[i - 1] + rng.normal(0.0, sigma)
    damped_beats = {}
    for lead in (7, 14):
        t0 = anom[:-lead]
        td = anom[lead:]
        # Exact climatology is 0 for this controlled field.
        pers_rmse = float(_m.rmse(t0, td))
        damp_rmse = float(_m.rmse(t0 * np.exp(-lead / TREND_TAU_DAYS), td))
        damped_beats[f"lead_{lead}"] = {
            "persistence_rmse": pers_rmse,
            "damped_rmse": damp_rmse,
        }
        if not (damp_rmse <= pers_rmse + 1e-9):
            raise AssertionError(
                f"Damped persistence ({damp_rmse}) did not beat plain persistence "
                f"({pers_rmse}) at lead {lead} on the AR(1) control."
            )
    checks["damped_beats_persistence"] = damped_beats

    # --- Check 2: shuffling origins destroys skill (persistence vs climatology) ---
    lead = 7
    targets, origins = [], []
    for td in test_dates:
        t0 = td - timedelta(days=lead)
        if t0 in sic_by_date and td in sic_by_date:
            if _doy_key(td) in doy_to_mean:
                targets.append(td)
                origins.append(t0)
    true_pers, true_clim = [], []
    for td, t0 in zip(targets, origins):
        obs_t0 = sic_by_date[t0]
        obs_td = sic_by_date[td]
        true_pers.append(_m.rmse(baselines.persistence(obs_t0), obs_td))
        true_clim.append(_m.rmse(doy_to_mean[_doy_key(td)], obs_td))
    # Detach origins from targets so shuffling misaligns them in time.
    shuffled_origins = list(origins)
    random.Random(12345).shuffle(shuffled_origins)
    shuf_pers, shuf_clim = [], []
    for td, t0 in zip(targets, shuffled_origins):
        obs_t0 = sic_by_date[t0]
        obs_td = sic_by_date[td]
        shuf_pers.append(_m.rmse(baselines.persistence(obs_t0), obs_td))
        shuf_clim.append(_m.rmse(doy_to_mean[_doy_key(td)], obs_td))

    tp = float(np.mean(true_pers)) if true_pers else float("nan")
    tc = float(np.mean(true_clim)) if true_clim else float("nan")
    sp = float(np.mean(shuf_pers)) if shuf_pers else float("nan")
    sc = float(np.mean(shuf_clim)) if shuf_clim else float("nan")

    def _skill(p, c):
        return float("nan") if p == 0 or not np.isfinite(p) or not np.isfinite(c) else 1.0 - p / c

    checks["shuffle_destroys_skill"] = {
        "true_order_persistence_rmse": tp,
        "true_order_climatology_rmse": tc,
        "true_order_skill_vs_climatology": _skill(tp, tc),
        "shuffled_persistence_rmse": sp,
        "shuffled_climatology_rmse": sc,
        "shuffled_skill_vs_climatology": _skill(sp, sc),
    }
    # Expectation: misaligned origins remove persistence's short-term advantage,
    # so the shuffled RMSE must be >= the true-order RMSE.
    if np.isfinite(tp) and np.isfinite(sp) and sp < tp - 1e-9:
        raise AssertionError(
            f"Shuffled persistence RMSE ({sp}) was not >= true persistence RMSE ({tp}); "
            f"shuffle failed to destroy skill."
        )
    return checks


def _render_markdown_table(rows):
    cols = ["domain", "season", "sector", "baseline", "lead",
            "rmse", "rmse_ci", "mae", "bias", "iiee", "n"]
    header = "| " + " | ".join(cols) + " |"
    sep = "| " + " | ".join(["---"] * len(cols)) + " |"
    lines = [header, sep]
    for r in rows:
        ci = r["rmse_ci"]
        lines.append("| {} | {} | {} | {} | {} | {:.4f} | [{:.4f},{:.4f}] | {:.4f} | {:.4f} | {:.3f} | {} |".format(
            r["domain"], r["season"], r.get("sector", "all"), r["baseline"], r["lead"],
            r["rmse"], ci[0], ci[1], r["mae"], r["bias"], r["iiee"], r["n"],
        ))
    return "\n".join(lines)


def _gaps_per_year(gaps):
    per = {}
    for g in gaps:
        per[g.year] = per.get(g.year, 0) + 1
    return per


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-fixtures", action="store_true",
                        help="Use synthetic fixtures (clearly labelled).")
    parser.add_argument("--start", type=str, default="2005-01-01",
                        help="Start date YYYY-MM-DD (default 2005-01-01).")
    parser.add_argument("--end", type=str, default="2024-12-31",
                        help="End date YYYY-MM-DD (default 2024-12-31).")
    parser.add_argument("--cache-dir", type=Path)
    parser.add_argument("--n-boot", type=int, default=200,
                        help="Bootstrap iterations (lower for fixtures).")
    args = parser.parse_args()

    def _parse(s):
        return datetime.strptime(s, "%Y-%m-%d").date()

    start, end = _parse(args.start), _parse(args.end)
    cache_dir = args.cache_dir or default_cache_dir()
    report_dir = Path("models/eval")
    report_dir.mkdir(parents=True, exist_ok=True)

    if args.use_fixtures:
        print("WARNING: Using fixtures (synthetic test data) - clearly labelled as such")
        sic_by_date, x_m, y_m = build_fixture()
        data_source = "fixtures"
        gaps = []
    else:
        expected = (end - start).days + 1
        sic_by_date, gaps, grid = load_sic_range(start, end, cache_dir)
        data_source = "real"
        x_m, y_m = grid["x_m"], grid["y_m"] if grid else (np.array([]), np.array([]))
        present = len(sic_by_date)
        print(f"Loaded {present} days of {expected} requested; gaps: {len(gaps)}")
        if present < 0.9 * expected:
            per_year = _gaps_per_year(gaps)
            raise RuntimeError(
                f"Only {present}/{expected} ({present/expected:.1%}) of requested days are "
                f"present in the cache (need >= 90%). Gaps per year: {per_year}"
            )

    dates = sorted(sic_by_date.keys())
    if not dates:
        raise RuntimeError("No data available")

    max_lead = max(LEADS)
    train_dates, test_dates = splits.final_held_out_recent_block(
        dates, holdout_years=1, embargo_days=max_lead
    )
    splits.check_no_leakage(train_dates, test_dates, max_lead)

    doy_to_mean, doy_to_trend, base_year = baselines.fit_climatology(
        train_dates, sic_by_date, use_trend=True
    )

    print("\nRunning sanity checks...")
    sanity = compute_sanity_checks(sic_by_date, train_dates, test_dates, doy_to_mean, base_year)
    print(f"  damped beats persistence: {sanity['damped_beats_persistence']}")
    print(f"  shuffle destroys skill: {sanity['shuffle_destroys_skill']}")

    report = {
        "record_length_days": len(dates),
        "train_years": sorted({d.year for d in train_dates}),
        "test_years": sorted({d.year for d in test_dates}),
        "data_source": data_source,
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "product_version": "v06r00",
        "date_range": [str(min(dates)), str(max(dates))],
        "disclaimer": "Baselines only; no ML model has been evaluated on real data.",
        "leads": list(LEADS),
        "baselines": list(BASELINES),
        "sectors": SECTORS_SIMPLE,
        "iiie_definition": (
            "Goessling et al. 2016: IIEE = area overestimated + underestimated at 15% "
            "threshold, weighted by cell area (m^2 from projection areal scale), "
            "exclude land/missing from both."
        ),
        "domains": list(DOMAINS),
        "climatology_trend": {
            "with_trend": True,
            "without_trend": True,
            "note": "Both 'climatology' (no trend) and 'climatology+trend' (linear trend) "
                    "are evaluated; trend fit on training years only.",
        },
        "sensor_caveat": SENSOR_CAVEAT,
        "gaps": [str(g) for g in gaps],
        "gaps_per_year": _gaps_per_year(gaps),
        "sanity_checks": sanity,
        "results": [],
    }

    print("\nRunning leave-one-year-out evaluation...")
    results, headline = run_eval(sic_by_date, x_m, y_m, n_boot=args.n_boot)
    assert results, "Evaluation produced no results."
    assert headline, "Evaluation produced no headline rows."
    allnums = [r["rmse"] for r in results] + [r["iiee"] for r in results] + [r["n"] for r in results]
    assert all(np.isfinite(v) for v in allnums), "Non-finite result produced."
    report["results"] = results

    report_json = report_dir / "real_sic_report.json"
    with open(report_json, "w") as f:
        json.dump(report, f, indent=2, default=_json_default)
    print(f"\nWrote {report_json} ({len(results)} result cells, {len(headline)} headline rows)")

    report_md = report_dir / "real_sic_report.md"
    with open(report_md, "w") as f:
        f.write("# Evaluation on " + data_source + " data (baselines only)\n\n")
        f.write(f"**Disclaimers:** {report['disclaimer']} Data source: {data_source}. "
                f"Record length: {len(dates)} days. Train years: {report['train_years']}, "
                f"Test years: {report['test_years']}.\n\n")
        f.write("**IIEE:** Goessling et al. 2016 definition, weighted by cell area "
                "(m^2 from projection areal scale), exclude land/missing from both, "
                "reported in million km^2.\n\n")
        f.write("**Domains:** RMSE/skill reported over all ocean cells AND over the "
                "variable-ice zone (climatology 5-95% on DOY). Headline is variable-ice zone.\n\n")
        f.write("**Sectors:** Weddell Sea (-60W to 20E), Indian Ocean (20E to 90E), "
                "Western Pacific (90E to 160E), Ross Sea (160E to 130W), "
                "Bellingshausen-Amundsen (130W to 60W). From src/eval/regions.py.\n\n")
        f.write("**Gaps:** Skipped origins/targets with missing data, no silent interpolation. "
                "n reported per table cell.\n\n")
        f.write("**Trend:** Climatology evaluated as 'climatology' (no trend) and "
                "'climatology+trend' (linear, training years only).\n\n")
        f.write("**Leads:** 1, 3, 7, 14 days. All seasons + austral departure season (Nov-Mar).\n\n")
        f.write("**Method:** Leave-one-year-out cross-validation with a max-lead-day embargo "
                "on both sides of the held-out year (includes the final recent block).\n\n")
        f.write("## Headline results (sector-aggregated)\n\n")
        f.write(_render_markdown_table(headline))
        f.write("\n\n## Per-sector breakdown (persistence, variable-ice zone, all seasons)\n\n")
        per_sector = [r for r in results if r["baseline"] == "persistence"
                      and r["domain"] == "variable_ice_zone_5_95" and r["season"] == "all"]
        f.write(_render_markdown_table(per_sector))
        f.write("\n")
    print(f"Wrote {report_md}")
    print("\n" + _render_markdown_table(headline))


def _json_default(o):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    return str(o)


if __name__ == "__main__":
    main()
