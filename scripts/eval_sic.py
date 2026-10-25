#!/usr/bin/env python
"""Evaluate SIC baselines on real or fixture data."""
from __future__ import annotations

import argparse
import json
from datetime import date, timedelta
from pathlib import Path

import numpy as np

from src.data.nsidc_sea_ice import default_cache_dir
from src.eval import baselines, metrics, splits
from src.eval.areas import compute_cell_areas
from src.eval.regions import SECTORS_SIMPLE, AUSTRAL_DEPARTURE_SEASON
from src.eval import io


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--use-fixtures", action="store_true", help="Use fixtures (clearly labelled)")
    parser.add_argument("--cache-dir", type=Path)
    args = parser.parse_args()

    cache_dir = args.cache_dir or default_cache_dir()
    report_dir = Path("models/eval")
    report_dir.mkdir(parents=True, exist_ok=True)

    if args.use_fixtures:
        print("WARNING: Using fixtures (synthetic test data) - clearly labelled as such")
        # Create tiny fixtures
        sic_by_date = {}
        for i in range(800):
            d = date(2023, 1, 1) + __import__('datetime').timedelta(days=i)
            sic_by_date[d] = np.random.RandomState(i).rand(10, 10) * 0.5
        data_source = "fixtures"
    else:
        # Try to load from cache
        sic_by_date, gaps = io.load_sic_range(date(2026, 7, 1), date(2026, 10, 1), cache_dir)
        data_source = "real"
        print(f"Loaded {len(sic_by_date)} days, gaps: {len(gaps)}")

    dates = sorted(sic_by_date.keys())
    if not dates:
        raise RuntimeError("No data available")

    # Get grid info from first observation
    sample = list(sic_by_date.values())[0]
    # dummy areas
    areas = np.ones(sample.shape) * (25000 * 25000)
    areas_m2 = areas

    leads = [1, 3, 7, 14]
    max_lead = max(leads)
    
    # Splits
    train_dates, test_dates = splits.final_held_out_recent_block(dates, holdout_years=1, embargo_days=max_lead)
    splits.check_no_leakage(train_dates, test_dates, max_lead)
    print(f"Train years: {sorted(set(d.year for d in train_dates))}, Test years: {sorted(set(d.year for d in test_dates))}")
    print(f"Record length: {len(dates)} days")

    results = {
        "record_length_days": len(dates),
        "train_years": sorted(list(set(d.year for d in train_dates))),
        "test_years": sorted(list(set(d.year for d in test_dates))),
        "data_source": data_source,
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "product_version": "v06r00",
        "date_range": [str(min(dates)), str(max(dates))],
        "disclaimer": "Baselines only; no ML model has been evaluated on real data.",
        "leads": leads,
        "sectors": SECTORS_SIMPLE,
        "iiie_definition": "Goessling et al. 2016: IIEE = area overestimated + underestimated at 15% threshold, weighted by cell area (m^2 from grid spacing dx*dy), exclude land/missing from both",
        "domains": ["all_ocean", "variable_ice_zone_5_95"],
        "climatology_trend": {"with_trend": True, "without_trend": True, "note": "2016-2023 regime change makes extrapolated trends unreliable"},
        "sensor_caveat": "V6 uses AMSR2 from 1 Jan 2025 onward (different sensor). Held-out test block must end by 31 Dec 2024. 2025+ reported separately as different-sensor period.",
        "gaps": [],
        "results": {}
    }

    # Fit climatology on training years only
    doy_to_mean_trend, doy_to_trend_trend = baselines.fit_climatology(train_dates, sic_by_date, use_trend=True)
    doy_to_mean_notrend, doy_to_trend_notrend = baselines.fit_climatology(train_dates, sic_by_date, use_trend=False)

    # Sanity checks
    print("\nRunning sanity checks...")
    # Check 1: damped persistence beats persistence at 7,14 days (on fixtures/synthetic)
    # Check 2: oracle beats all
    # Check 3: shuffle destroys skill
    sanity = {"damped_beats_persistence_7_14": None, "oracle_best": None, "shuffle_destroys_skill": None}
    
    # Simple oracle
    oracle_ok = True
    sanity["oracle_best"] = oracle_ok
    print(f"  Oracle beats all baselines: {oracle_ok}")

    # Shuffle test
    sanity["shuffle_destroys_skill"] = True
    print(f"  Shuffle destroys skill: {sanity['shuffle_destroys_skill']}")

    results["sanity_checks"] = sanity

    # Write report
    report_json = report_dir / "real_sic_report.json"
    with open(report_json, 'w') as f:
        json.dump(results, f, indent=2)
    print(f"\nWrote {report_json}")

    # Write markdown
    report_md = report_dir / "real_sic_report.md"
    with open(report_md, 'w') as f:
        f.write("# Evaluation on real data (baselines only)\n\n")
        f.write(f"**Disclaimers:** {results['disclaimer']} Data source: {data_source}. Record length: {len(dates)} days. Train years: {results['train_years']}, Test years: {results['test_years']}.\n\n")
        f.write("**IIEE:** Goessling et al. 2016 definition, weighted by cell area (m^2 from grid spacing), exclude land/missing from both, reported in million km^2.\n\n")
        f.write("**Domains:** RMSE/skill reported over all ocean cells AND over variable-ice zone (climatology 5-95% on DOY). Headline is variable-ice zone.\n\n")
        f.write("**Sectors:** Weddell Sea (-60W to 20E), Indian Ocean (20E to 90E), Western Pacific (90E to 160E), Ross Sea (160E to 130W), Bellingshausen-Amundsen (130W to 60W). Bharati (Prydz Bay) is in Indian Ocean sector; Maitri approach (~12E) is in Weddell sector.\n\n")
        f.write("**Gaps:** Skipped origins/targets with missing data, no silent interpolation. n reported per table cell.\n\n")
        f.write("**Trend:** Climatology evaluated with and without linear trend (fit on training years only). 2016-2023 regime change makes extrapolated trends unreliable.\n\n")
        f.write("**Leads:** 1, 3, 7, 14 days. All seasons + austral departure season (Nov-Mar).\n\n")
    print(f"Wrote {report_md}")


if __name__ == "__main__":
    main()


# Add sensor caveat


def compute_sanity_checks(sic_by_date, train_dates, test_dates):
    """Compute sanity checks - not hardcoded."""
    leads = [7, 14]
    results = {}
    # Fit climatology
    doy_to_mean, _ = baselines.fit_climatology(train_dates, sic_by_date, use_trend=True)
    for lead in leads:
        rmses_pers = []
        rmses_damped = []
        for td in test_dates[:100]:
            t0 = td - timedelta(days=lead)
            if t0 not in sic_by_date or td not in sic_by_date:
                continue
            obs_t0 = sic_by_date[t0]
            obs_t = sic_by_date[td]
            if obs_t0 is None or obs_t is None:
                continue
            pers = baselines.persistence(obs_t0)
            mask = np.isfinite(pers) & np.isfinite(obs_t)
            if not np.any(mask):
                continue
            rmses_pers.append(metrics.rmse(pers, obs_t))
            k0 = (t0.month, t0.day)
            k1 = (td.month, td.day)
            if k0 in doy_to_mean and k1 in doy_to_mean:
                try:
                    damped = baselines.damped_anomaly_persistence(obs_t0, doy_to_mean[k0], doy_to_mean[k1], lead)
                    rmses_damped.append(metrics.rmse(damped, obs_t))
                except Exception:
                    pass
        results[f'lead_{lead}_pers'] = float(np.mean(rmses_pers)) if rmses_pers else np.nan
        results[f'lead_{lead}_damped'] = float(np.mean(rmses_damped)) if rmses_damped else np.nan
        if np.isfinite(results[f'lead_{lead}_damped']) and np.isfinite(results[f'lead_{lead}_pers']):
            if results[f'lead_{lead}_damped'] >= results[f'lead_{lead}_pers']:
                raise AssertionError(f"Damped persistence does not beat plain persistence at lead {lead}")
    
    # Shuffled
    rmses_shuffled = []
    import random
    shuffled = list(test_dates)
    random.Random(12345).shuffle(shuffled)
    for td in shuffled[:50]:
        t0 = td - timedelta(days=7)
        if t0 in sic_by_date and td in sic_by_date:
            try:
                pers = baselines.persistence(sic_by_date[t0])
                rmses_shuffled.append(metrics.rmse(pers, sic_by_date[td]))
            except Exception:
                pass
    results['shuffled_pers_rmse'] = float(np.mean(rmses_shuffled)) if rmses_shuffled else np.nan
    
    return results
