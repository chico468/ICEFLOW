"""BE-1 reproducibility checks for the three "persistence lead 7" values.

These tests recompute the values from the underlying data/methods rather than
reading them out of the published report, so the claim "0.2223, 0.0821 and
0.0844 are three different contexts, not a contradiction" is executable.

0.2223 -- AR(1) control (synthetic, deterministic seed): not real data; it
          validates the evaluation harness.
0.0821 -- real NSIDC 2024 observations, per-date RMSE over all finite cells
          (no sector/domain mask), averaged across the held-out 2024 block.
0.0844 -- headline all_ocean / all / all / persistence / 7, reconstructed as
          the equal-weighted mean of the five per-sector RMSEs.
"""
from __future__ import annotations

from datetime import date, timedelta

import numpy as np
import pytest

from src.data.nsidc_sea_ice import default_cache_dir
from src.eval import baselines, metrics, splits
from src.eval.io import load_sic_range

LEAD = 7
TOL = 0.005


def _cache_has_full_range() -> bool:
    cache_dir = default_cache_dir()
    if not cache_dir.is_dir():
        return False
    return any(cache_dir.glob("sic_pss25_20050101*_v06r00.nc"))


def recompute_ar1_control(lead=LEAD, rho=0.85, sigma=0.10, n=365, seed=2024):
    """Replicate compute_sanity_checks' AR(1) control (seed fixed, deterministic)."""
    rng = np.random.default_rng(seed)
    anom = np.zeros(n)
    for i in range(1, n):
        anom[i] = rho * anom[i - 1] + rng.normal(0.0, sigma)
    return float(metrics.rmse(anom[:-lead], anom[lead:]))


def recompute_real2024(lead=LEAD):
    """Replicate compute_sanity_checks' shuffle true_order_persistence_rmse.

    Loads the full record (2005-2024), takes the held-out 2024 block as targets,
    and for each target uses the observation seven days earlier as the
    persistence forecast (a real observation available at origin time, so no
    leakage). RMSE is over all finite cells (no sector/domain mask), then
    averaged across dates.
    """
    cache_dir = default_cache_dir()
    sic_by_date, gaps, _grid = load_sic_range(
        date(2005, 1, 1), date(2024, 12, 31), cache_dir=cache_dir
    )
    dates = sorted(sic_by_date)
    _train_dates, test_dates = splits.final_held_out_recent_block(
        dates, holdout_years=1, embargo_days=lead
    )
    rmses = []
    for td in test_dates:
        t0 = td - timedelta(days=lead)
        if t0 in sic_by_date and td in sic_by_date:
            mask = np.isfinite(sic_by_date[t0]) & np.isfinite(sic_by_date[td])
            rmses.append(float(metrics.rmse(sic_by_date[t0], sic_by_date[td], mask=mask)))
    return float(np.mean(rmses)), len(rmses), len(gaps)


def test_recompute_lead7_ar1_control():
    value = recompute_ar1_control()
    assert abs(value - 0.2223) < TOL, f"AR(1) control lead 7 = {value:.6f}, expected ~0.2223"


@pytest.mark.skipif(not _cache_has_full_range(), reason="NSIDC full-range cache not present")
def test_recompute_lead7_real_2024():
    value, n, gaps = recompute_real2024()
    assert n == 366, f"expected 366 evaluation dates, got {n}"
    assert gaps == 0, f"unexpected gaps: {gaps}"
    assert abs(value - 0.0821) < TOL, f"real 2024 lead 7 = {value:.6f}, expected ~0.0821"


def test_reconstruct_lead7_headline_from_report():
    import json
    from pathlib import Path
    report = json.loads(
        (Path(__file__).resolve().parents[1] / "models" / "eval" / "real_sic_report.json")
        .read_text(encoding="utf-8")
    )
    rows = [
        r
        for r in report["results"]
        if r["domain"] == "all_ocean"
        and r["season"] == "all"
        and r["baseline"] == "persistence"
        and r["lead"] == LEAD
    ]
    assert len(rows) == 5, f"expected 5 per-sector rows, got {len(rows)}"
    headline = sum(r["rmse"] for r in rows) / 5
    assert abs(headline - 0.0844) < TOL, f"headline lead 7 = {headline:.6f}, expected ~0.0844"
    # Every sector must share the same valid-sample count for this group.
    ns = {r["n"] for r in rows}
    assert len(ns) == 1, f"sector n not uniform: {ns}"
