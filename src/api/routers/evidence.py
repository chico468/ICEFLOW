"""Evidence scorecard.

Reads the real model-evaluation reports under ``models/eval/`` (only those whose metadata says
``data_source == "real"``) and normalizes them to the frontend contract:

GET /api/v1/evidence/scorecard -> {generated_at, git_sha, data_source, product, version,
train_years, test_years, rows[], promoted{}, coverage{}, caveats[]}

Nothing here is fabricated: every number comes from a committed eval report. When no real report
exists the endpoint returns data_source "none" with empty rows.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List

from fastapi import APIRouter

router = APIRouter(prefix="/api/v1/evidence", tags=["evidence"])

_EVAL_DIR = Path(__file__).resolve().parents[3] / "models" / "eval"


def _load_reports() -> List[Dict[str, Any]]:
    reports: List[Dict[str, Any]] = []
    if not _EVAL_DIR.is_dir():
        return reports
    for path in sorted(_EVAL_DIR.glob("*.json")):
        try:
            report = json.loads(path.read_text())
        except Exception:
            continue
        if isinstance(report, dict) and report.get("data_source") == "real":
            reports.append(report)
    return reports


def _domain(name: str) -> str:
    return (
        name.replace("variable_ice_zone", "variable-ice-zone")
        .replace("antarctic_waters", "antarctic-waters")
        .replace("sector:", "sector: ")
        .replace("_", "-")
    )


def _season(name: str) -> str:
    return {"all": "all-season", "nov_mar": "nov-mar"}.get(name, name)


def _task(name: str) -> str:
    return "iceberg" if "iceberg" in name else "sic"


def _rows(report: Dict[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for row in report.get("rows", []) or []:
        task = _task(row.get("task", ""))
        ci = row.get("ci")
        if not (isinstance(ci, list) and len(ci) == 2 and all(isinstance(c, (int, float)) for c in ci)):
            # Baseline reference rows carry no conformal CI; skip them to keep the contract honest.
            continue
        metric = row.get("metric")
        is_error_km = metric == "great_circle_error_km"
        value = row.get("rmse")
        out.append({
            "task": task,
            "lead_days": row.get("lead_days"),
            "domain": _domain(row.get("domain", "")),
            "season": _season(row.get("season", "")),
            "model": row.get("model"),
            "rmse": None if is_error_km else value,
            "error_km": value if is_error_km else None,
            "ci": [float(ci[0]), float(ci[1])],
            "skill_vs_baseline": row.get("skill_vs_baseline"),
            "n": row.get("n"),
        })
    return out


def _promoted(report: Dict[str, Any]) -> Dict[str, Dict[str, bool]]:
    promoted = report.get("promoted") or {}
    return {
        "sic": {str(k): bool(v) for k, v in (promoted.get("sic") or {}).items()},
        "iceberg": {str(k): bool(v) for k, v in (promoted.get("iceberg") or {}).items()},
    }


@router.get("/scorecard")
def scorecard() -> Dict[str, Any]:
    reports = _load_reports()
    if not reports:
        return {
            "generated_at": None,
            "git_sha": None,
            "data_source": "none",
            "product": None,
            "version": None,
            "train_years": None,
            "test_years": None,
            "rows": [],
            "promoted": {"sic": {}, "iceberg": {}},
            "coverage": {},
            "caveats": ["No real model-evaluation report found in models/eval/."],
        }

    # Merge every real report; the newest generated_at / git_sha wins for the header.
    rows: List[Dict[str, Any]] = []
    promoted: Dict[str, Dict[str, bool]] = {"sic": {}, "iceberg": {}}
    coverage: Dict[str, Any] = {}
    caveats: List[str] = []
    generated_at = None
    git_sha = None
    product = None
    version = None
    train_years = None
    test_years = None

    for report in reports:
        rows.extend(_rows(report))
        rep_promoted = _promoted(report)
        for side in ("sic", "iceberg"):
            promoted[side].update(rep_promoted.get(side, {}))
        coverage.update(report.get("coverage") or {})
        caveats.extend(report.get("caveats") or [])
        if report.get("generated_at"):
            generated_at = report["generated_at"]
        if report.get("git_sha"):
            git_sha = report["git_sha"]
        if report.get("product"):
            product = report["product"]
        if report.get("version"):
            version = report["version"]
        if report.get("train_years") is not None:
            train_years = report["train_years"]
        if report.get("test_years") is not None:
            test_years = report["test_years"]

    return {
        "generated_at": generated_at,
        "git_sha": git_sha,
        "data_source": "real",
        "product": product,
        "version": version,
        "train_years": train_years,
        "test_years": test_years,
        "rows": rows,
        "promoted": promoted,
        "coverage": coverage,
        "caveats": sorted(set(caveats)),
    }
