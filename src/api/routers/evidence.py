"""Evidence scorecard: a single read-only endpoint that condenses every real-data report.

Reads ``models/eval/*.json`` and emits the shared-contract shape. Reports whose metadata
says ``data_source != "real"`` are skipped entirely, so a clean checkout with only fixture
reports still returns a well-formed scorecard.
"""
from __future__ import annotations

import json
import os
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])

_TARGET_COVERAGE = 0.9
_PROMOTION_LEADS = {"sic": [3, 7, 14], "iceberg": [1, 3, 7]}


def _eval_dir() -> Path:
    configured = os.environ.get("ICEFLOW_EVAL_DIR")
    if configured:
        return Path(configured).expanduser()
    return Path(__file__).resolve().parents[3] / "models" / "eval"


def _load_reports() -> List[Dict[str, Any]]:
    eval_dir = _eval_dir()
    reports: List[Dict[str, Any]] = []
    if not eval_dir.is_dir():
        return reports
    for path in sorted(eval_dir.glob("*.json")):
        try:
            with open(path) as fh:
                report = json.load(fh)
        except (json.JSONDecodeError, OSError):
            continue
        if not isinstance(report, dict):
            continue
        if report.get("data_source") != "real":
            continue
        reports.append(report)
    return reports


def _to_rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    """Convert a real-data report to scorecard rows.

    Handles two report shapes:
      * Stage-2 evaluation reports with a ``results`` list (baseline-keyed).
      * BE-2/BE-3 ML reports with a ``rows`` list (already condensed).
    """
    results = report.get("results", [])
    if results:
        return _to_rows_from_results(report)
    rows = report.get("rows", [])
    if rows:
        return _to_rows_from_ml_rows(rows)
    return []


def _to_rows_from_results(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    results = report.get("results", [])
    task = "sic"
    persistence = {}
    for r in results:
        if r.get("baseline") == "persistence":
            persistence[(r.get("lead"), r.get("domain"), r.get("season"), r.get("sector"))] = r
    rows: List[Dict[str, Any]] = []
    for r in results:
        if r.get("baseline") == "damped":
            key = (r.get("lead"), r.get("domain"), r.get("season"), r.get("sector"))
            persist = persistence.get(key)
            skill = None
            if persist is not None and persist.get("rmse", 0) > 0:
                skill = round(1.0 - r["rmse"] / persist["rmse"], 4)
            rows.append({
                "task": task,
                "lead_days": r.get("lead"),
                "domain": r.get("domain"),
                "season": r.get("season"),
                "sector": r.get("sector"),
                "model": "damped_anomaly_persistence",
                "rmse": round(r.get("rmse", 0.0), 4),
                "ci": [round(r.get("rmse_ci", [0, 0])[0], 4), round(r.get("rmse_ci", [0, 0])[1], 4)],
                "skill_vs_baseline": skill,
                "n": r.get("n"),
            })
    return rows


def _to_rows_from_ml_rows(rows: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for r in rows:
        out.append({
            "task": r.get("task"),
            "lead_days": r.get("lead_days"),
            "domain": r.get("domain"),
            "season": r.get("season"),
            "sector": r.get("sector"),
            "model": r.get("model"),
            "rmse": round(r.get("rmse", 0.0), 4) if r.get("rmse") is not None else None,
            "ci": [round(v, 4) if v is not None else None for v in (r.get("ci") or [None, None])],
            "skill_vs_baseline": r.get("skill_vs_baseline"),
            "n": r.get("n"),
        })
    return out


def _compute_promoted(reports: List[Dict[str, Any]]) -> Dict[str, Dict[str, bool]]:
    promoted: Dict[str, Dict[str, bool]] = {"sic": {}, "iceberg": {}}
    for report in reports:
        # ML reports carry their own promoted_leads.
        ml_promoted = report.get("promoted", {})
        if isinstance(ml_promoted, dict):
            for task, leads in ml_promoted.items():
                if isinstance(leads, dict):
                    promoted.setdefault(task, {})
                    for lead, val in leads.items():
                        promoted[task][str(lead)] = bool(val)
        results = report.get("results", [])
        if not results:
            continue
        task = "sic"
        damped = {}
        persistence = {}
        for r in results:
            if r.get("baseline") == "damped":
                damped[(r.get("lead"), r.get("domain"), r.get("season"), r.get("sector"))] = r
            if r.get("baseline") == "persistence":
                persistence[(r.get("lead"), r.get("domain"), r.get("season"), r.get("sector"))] = r
        for lead in _PROMOTION_LEADS.get(task, []):
            all_pass = True
            for season in ("all", "austral_departure"):
                sectors_present = set(
                    k[3] for k in damped
                    if k[0] == lead and k[1] == "variable_ice_zone_5_95" and k[2] == season
                )
                season_pass = True
                for sector in sectors_present:
                    d_key = (lead, "variable_ice_zone_5_95", season, sector)
                    p_key = (lead, "variable_ice_zone_5_95", season, sector)
                    d = damped.get(d_key)
                    p = persistence.get(p_key)
                    if d is None or p is None:
                        season_pass = False
                        continue
                    d_ci = d.get("rmse_ci", [0, 0])
                    p_rmse = p.get("rmse", 0)
                    if not (d_ci[1] < p_rmse):
                        season_pass = False
                if not season_pass:
                    all_pass = False
            promoted[task][str(lead)] = all_pass
    return promoted


def _compute_coverage(reports: List[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    coverage: Dict[str, Dict[str, Any]] = {}
    for report in reports:
        leads = report.get("leads", [])
        for lead in leads:
            coverage[str(lead)] = {
                "target": _TARGET_COVERAGE,
                "empirical": None,
            }
    return coverage


def _collect_caveats(reports: List[Dict[str, Any]]) -> List[str]:
    caveats: List[str] = []
    for report in reports:
        if report.get("disclaimer"):
            caveats.append(report["disclaimer"])
        if report.get("sensor_caveat"):
            caveats.append(report["sensor_caveat"])
        for c in report.get("caveats", []) or []:
            caveats.append(c)
    return caveats


@router.get("/scorecard")
def scorecard() -> Dict[str, Any]:
    """Condensed evidence scorecard read from ``models/eval/*.json``.

    Only reports whose ``data_source`` is ``"real"`` contribute. A checkout with no real
    reports returns a well-formed scorecard with ``data_source: "none"`` and empty rows.
    """
    reports = _load_reports()
    generated_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    git_sha = os.environ.get("ICEFLOW_GIT_SHA", "")

    if not reports:
        return {
            "generated_at": generated_at,
            "git_sha": git_sha or None,
            "data_source": "none",
            "product": None,
            "version": None,
            "train_years": [],
            "test_years": [],
            "rows": [],
            "promoted": {"sic": {}, "iceberg": {}},
            "coverage": {},
            "caveats": ["No real-data reports found in models/eval/."],
        }

    # Merge all real reports into rows.
    all_rows: List[Dict[str, Any]] = []
    train_years: set = set()
    test_years: set = set()
    product: Optional[str] = None
    version: Optional[str] = None
    for report in reports:
        all_rows.extend(_to_rows(report))
        for y in report.get("train_years", []):
            train_years.add(y)
        for y in report.get("test_years", []):
            test_years.add(y)
        if not product:
            product = report.get("product")
        if not version:
            version = report.get("version")

    promoted = _compute_promoted(reports)
    coverage = _compute_coverage(reports)
    caveats = _collect_caveats(reports)

    return {
        "generated_at": generated_at,
        "git_sha": git_sha or None,
        "data_source": "real",
        "product": product,
        "version": version,
        "train_years": sorted(train_years),
        "test_years": sorted(test_years),
        "rows": all_rows,
        "promoted": promoted,
        "coverage": coverage,
        "caveats": caveats,
    }
