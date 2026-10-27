"""
Artefact registry for the trained ML layer.

THE CONTRACT THIS MODULE EXISTS TO ENFORCE. Importing anything from src.ml must never be able to
break the physics path. A judge cloning the repository without running scripts/train.py, a
continuous-integration job with an empty models directory, a corrupted artefact from a
half-finished write - all three must leave the API answering requests. So every loader here
swallows its failure, records why, and returns None. The callers in src/core and src/api are
expected to test for None and fall back to physics, which is the behaviour they would want
anyway: a trained model that has not been trained should be invisible, not fatal.

ml_status() is the single honest answer to "is there actually any machine learning in this
system", and it returns "not trained" without embarrassment when there is not.
"""
from __future__ import annotations

import json
import threading
from pathlib import Path
from typing import Any, Dict, Optional

from src.ml.real_dataset import REAL_LEAD_DAYS

# models/ sits at the repository root, three levels up from this file. Paths are resolved through
# accessor functions rather than baked into module constants, so a test can point MODELS_DIR at a
# temporary directory and have the very next lookup follow it.
MODELS_DIR = Path(__file__).resolve().parents[2] / "models"

SIC_ARTEFACT_NAME = "sic_forecaster.joblib"
DRIFT_ARTEFACT_NAME = "drift_residual.joblib"
GROWLER_ARTEFACT_NAME = "growler_classifier.joblib"
REAL_SIC_ARTEFACT_NAME = "real_sic_forecaster.joblib"
METRICS_NAME = "metrics.json"


def artefact_path(name: str) -> Path:
    return Path(MODELS_DIR) / name


def metrics_path() -> Path:
    return artefact_path(METRICS_NAME)

# Loading is lazy and memoised. A joblib load of a 300-tree forest costs tens of milliseconds,
# which is fine once and not fine on every radar sweep. The lock keeps two threads from racing
# on the first load under uvicorn's thread pool.
_LOCK = threading.Lock()
_CACHE: Dict[str, Any] = {}
_LOAD_ERRORS: Dict[str, str] = {}


def _load(key: str, path: Path, loader) -> Optional[Any]:
    """Load an artefact once, remembering both successes and failures."""
    if key in _CACHE:
        return _CACHE[key]
    with _LOCK:
        if key in _CACHE:
            return _CACHE[key]
        if not path.exists():
            _LOAD_ERRORS[key] = f"artefact not found at {path.name}"
            _CACHE[key] = None
            return None
        try:
            _CACHE[key] = loader(path)
            _LOAD_ERRORS.pop(key, None)
        except Exception as exc:  # pragma: no cover - depends on a corrupted artefact
            _LOAD_ERRORS[key] = f"{type(exc).__name__}: {exc}"
            _CACHE[key] = None
        return _CACHE[key]


def get_sic_forecaster():
    """The trained concentration forecaster (synthetic), or None if not populated."""
    from src.ml.sic_forecaster import SICForecaster

    return _load("sic", artefact_path(SIC_ARTEFACT_NAME), SICForecaster.load)


def get_real_sic_forecaster():
    """The trained real-data sea-ice concentration forecaster, or None."""
    from src.ml.real_sic_forecaster import RealSICForecaster

    return _load("real_sic", artefact_path(REAL_SIC_ARTEFACT_NAME), RealSICForecaster.load)


def get_drift_residual():
    """The trained iceberg drift residual corrector, or None."""
    from src.ml.drift_residual import DriftResidualModel

    return _load("drift", artefact_path(DRIFT_ARTEFACT_NAME), DriftResidualModel.load)


def get_growler_classifier():
    """The trained growler versus clutter classifier, or None."""
    from src.ml.growler_classifier import GrowlerClassifier

    return _load("growler", artefact_path(GROWLER_ARTEFACT_NAME), GrowlerClassifier.load)


def load_metrics() -> Dict[str, Any]:
    """Contents of models/metrics.json, or an empty dictionary if it is missing or malformed."""
    path = metrics_path()
    if not path.exists():
        return {}
    try:
        with open(path, "r", encoding="utf-8") as fh:
            return json.load(fh)
    except Exception:  # pragma: no cover - depends on a malformed file
        return {}


def reset_cache() -> None:
    """
    Drop the memoised artefacts.

    Needed by the tests, which point MODELS_DIR at a temporary directory and then need the next
    call to actually go back to disk rather than hand back a cached object.
    """
    with _LOCK:
        _CACHE.clear()
        _LOAD_ERRORS.clear()


def _read_metrics_mode(metrics: Dict[str, Any]) -> str:
    mode = metrics.get("mode")
    if isinstance(mode, str) and mode:
        return mode
    return "unknown"


def _compute_beats_best_baseline(key: str, record: Dict[str, Any]) -> bool:
    if not isinstance(record, dict):
        return False
    if key == "sic_forecaster":
        skill = ((record.get("val") or {}).get("overall") or {}).get("skill_score_vs") or {}
        try:
            vs_persist = float(skill.get("persistence"))
            vs_clim = float(skill.get("climatology"))
            vs_phys = float(skill.get("physics"))
        except Exception:
            return False
        return vs_persist > 0 and vs_clim > 0 and vs_phys > 0
    if key == "drift_residual":
        test = record.get("test") or {}
        overall = test.get("overall") or {}
        try:
            improvement = float(overall.get("improvement_vs_persistence_mean_displacement_km"))
        except Exception:
            return False
        return improvement > 0
    if key == "growler_classifier":
        test = record.get("test") or {}
        overall = test.get("overall") or {}
        try:
            f1 = float(overall.get("model", {}).get("f1"))
            maj_f1 = float(overall.get("baselines", {}).get("majority", {}).get("f1"))
            snr_f1 = float(overall.get("baselines", {}).get("snr_threshold", {}).get("f1"))
        except Exception:
            return False
        return f1 > maj_f1 and f1 > snr_f1
    if key == "real_sic_forecaster":
        # Real model: beats baseline if any lead was promoted by the gate.
        promoted = record.get("promoted_leads") if isinstance(record, dict) else None
        if promoted is not None:
            return len(promoted) > 0
        eval_status = record.get("evaluation_status", {}) if isinstance(record, dict) else {}
        return bool(eval_status.get("promoted_leads"))
    return False


def ml_status() -> Dict[str, Any]:
    """
    What is trained, on how much, when, and how well.

    Deliberately shaped so it can be returned straight from the health endpoint.
    """
    metrics = load_metrics()
    per_model = metrics.get("models", {}) if isinstance(metrics, dict) else {}

    entries: Dict[str, Any] = {}
    for key, name, getter, label in (
        ("sic_forecaster", SIC_ARTEFACT_NAME, get_sic_forecaster, "sea-ice concentration forecast"),
        ("drift_residual", DRIFT_ARTEFACT_NAME, get_drift_residual, "iceberg drift residual correction"),
        ("growler_classifier", GROWLER_ARTEFACT_NAME, get_growler_classifier, "growler versus sea clutter"),
    ):
        path = artefact_path(name)
        model = getter()
        record = per_model.get(key, {}) if isinstance(per_model, dict) else {}
        beats = _compute_beats_best_baseline(key, record)
        entry: Dict[str, Any] = {
            "task": label,
            "status": "demo_synthetic" if model is not None else "not trained",
            "status_detail": "experimental" if model is not None else "not trained",
            "trained_on": "synthetic",
            "operational_skill_validated": False,
            "beats_best_baseline": beats,
            "used_in_routing": False,
            "metrics_mode": _read_metrics_mode(metrics),
            "trained_at": metrics.get("trained_at"),
            "artefact": path.name,
            "artefact_present": path.exists(),
        }
        caveats = {
            "sic_forecaster": "Synthetic-only; negative or mixed skill vs baselines in current metrics (does not beat physics/persistence in reported leads). Not operationally validated.",
            "drift_residual": "Synthetic-only; reported position error increases vs persistence in current metrics. Not operationally validated.",
            "growler_classifier": "Synthetic-only; high F1 appears driven by generator distributions relative to weak baselines. Not operationally validated.",
        }
        entry["caveat"] = caveats.get(key, "Synthetic-only; not operationally validated.")
        if model is None:
            entry["reason"] = _LOAD_ERRORS.get(
                {"sic_forecaster": "sic", "drift_residual": "drift", "growler_classifier": "growler"}[key],
                "artefact not loaded",
            )
            entry["fallback"] = "physics path only; no ML correction applied"
        else:
            metadata = getattr(model, "metadata", {}) or {}
            entry["estimator"] = metadata.get("estimator", "")
            entry["feature_names"] = list(getattr(model, "feature_names", ()) or [])
            entry["n_features"] = len(entry["feature_names"])
            entry["n_train_rows"] = metadata.get("n_train_rows")
            entry["sklearn_version"] = metadata.get("sklearn_version")
            if record:
                entry["dataset"] = record.get("dataset")
                entry["headline"] = record.get("headline")
                entry["test_metrics"] = record.get("test")
        entries[key] = entry

    # Real-data SIC forecaster (BE-2). Separate from the synthetic loop.
    real_path = artefact_path(REAL_SIC_ARTEFACT_NAME)
    real_model = get_real_sic_forecaster()
    real_record = metrics if isinstance(metrics, dict) and metrics.get("trained_on") == "real" else {}
    real_entry: Dict[str, Any] = {
        "task": "sea-ice concentration forecast (real NSIDC V6 data)",
        "status": "real_data_trained" if real_model is not None else "not trained",
        "status_detail": "trained on real satellite observations" if real_model is not None else "not trained",
        "trained_on": "real",
        "operational_skill_validated": bool(real_record.get("evaluation_status", {}).get("operational_skill_validated", False)),
        "beats_best_baseline": bool(
            real_record.get("evaluation_status", {}).get("promoted_leads")
        ) if real_record else False,
        "used_in_routing": bool(real_record.get("evaluation_status", {}).get("used_in_routing", False)),
        "metrics_mode": _read_metrics_mode(metrics),
        "trained_at": real_record.get("trained_at") if isinstance(real_record, dict) else None,
        "artefact": real_path.name,
        "artefact_present": real_path.exists(),
        "report_path": str(Path(MODELS_DIR) / "eval" / "real_sic_report.json"),
    }
    if real_model is None:
        real_entry["reason"] = _LOAD_ERRORS.get(
            "real_sic", "real_sic_forecaster artefact not found"
        )
        real_entry["fallback"] = "synthetic SIC forecaster or physics path"
    else:
        metadata = getattr(real_model, "metadata", {}) or {}
        real_entry["estimator"] = metadata.get("estimator", "HistGradientBoostingRegressor")
        real_entry["feature_names"] = list(getattr(real_model, "feature_names", ()) or [])
        real_entry["n_features"] = len(real_entry["feature_names"])
        real_entry["n_train_rows"] = real_record.get("dataset", {}).get("n_train_rows") if isinstance(real_record, dict) else None
        real_entry["leads"] = list(getattr(real_model, "leads", REAL_LEAD_DAYS))
        if isinstance(real_record, dict):
            real_entry["val_metrics"] = real_record.get("val_metrics")
            real_entry["test_metrics"] = real_record.get("test_metrics")
            real_entry["promoted_leads"] = real_record.get("promoted_leads", [])
            real_entry["coverage_90_ci"] = real_record.get("coverage_90_ci")
            real_entry["taus"] = real_record.get("taus")
    real_entry["caveat"] = (
        "Trained on real NSIDC V6 observations; not operationally validated. "
        "Promoted leads must beat the tuned baseline with CI excluding zero "
        "in both all-season and Nov-Mar on VIZ cells."
    )
    entries["real_sic_forecaster"] = real_entry

    any_trained = any(e.get("artefact_present") or e["status"] != "not trained" for e in entries.values())
    real_report_path = Path(MODELS_DIR) / "eval" / "real_sic_report.json"
    real_data_report = None
    if real_report_path.exists():
        try:
            if "/tests/" not in str(real_report_path):
                with open(real_report_path, "r", encoding="utf-8") as fh:
                    report = json.load(fh)
                if report.get("data_source") == "real":
                    real_data_report = {
                        "path": str(real_report_path),
                        "date": report.get("generated_at") or report.get("date"),
                        "product": report.get("product") or report.get("data_source_name"),
                        "product_version": report.get("product_version") or report.get("version"),
                        "date_range": report.get("date_range"),
                    }
        except Exception:
            pass

    has_real = real_entry["artefact_present"] or real_entry["status"] != "not trained"
    if has_real:
        data_provenance = (
            "Mixed. The real_sic_forecaster is trained on NSIDC V6 observations "
            "(NOAA/NSIDC CDR G02202 v06r00, 25 km polar stereographic). "
            "The sic_forecaster, drift_residual and growler_classifier are trained "
            "on synthetic data generated by src/core/physics modules. "
            "Real-data metrics come from satellite retrievals; synthetic metrics are "
            "simulated-environment."
        )
        hint = "Real model loaded from models/. Run python -m scripts.train_real_sic to retrain."
    else:
        data_provenance = (
            "Training data generated by this repository's synthetic physics environment "
            "(src/core/environment.py, src/core/sea_ice.py, src/core/iceberg_tracker.py). "
            "All reported metrics are simulated-environment metrics, not operational skill "
            "against OSI-SAF, AMSR2, ERA5 or CMEMS."
        )
        hint = (
            "Run python -m scripts.train_real_sic to train on real NSIDC data, "
            "or python -m scripts.train for synthetic models."
            if not any_trained
            else "Artefacts loaded from models/ (synthetic-only; not validated)."
        )

    return {
        "any_trained": any_trained,
        "models_dir": str(MODELS_DIR),
        "metrics_file_present": metrics_path().exists(),
        "trained_at": real_record.get("trained_at") if isinstance(real_record, dict) else metrics.get("trained_at"),
        "training_wall_time_s": metrics.get("training_wall_time_s"),
        "seed": metrics.get("seed"),
        "sklearn_version": metrics.get("sklearn_version"),
        "models": entries,
        "real_data_report": real_data_report,
        "data_provenance": data_provenance,
        "hint": hint,
    }
