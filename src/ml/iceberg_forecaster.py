"""
Per-lead HistGradientBoosting iceberg drift residual forecaster.

Trains one pair of gradient-boosted regressors per lead time (1, 3, 7 days)
to predict the lat/lon residual (truth - baseline_position) from the 3-day
constant-velocity baseline.  The final forecast is baseline + residual.

Baselines (evaluated on TEST only, never trained on):
  (a) No movement (position held fixed).
  (b) Constant velocity from the last 3 days.  <-- the baseline the ML competes against.
  (c) Constant velocity from the last 7 days, damped.

Promotion gate: a lead is promoted only if the ML model's RMSE of great-circle
error (km) beats baseline (b) with the bootstrap CI of the RMSE difference
excluding zero, CI computed by iceberg (block bootstrap across iceberg IDs).

Uncertainty: split-conformal on validation residuals, giving p50/p90 radius
bands per lead.
"""
from __future__ import annotations

import math
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import HistGradientBoostingRegressor

from src.ml.iceberg_dataset import (
    ICELEAD_DAYS,
    FEATURE_NAMES_ICEBERG,
    IcebergSplit,
)
from src.core.constants import EARTH_RADIUS_KM, KM_PER_NM
from src.core.geo import haversine_km


ICEBERG_PROMOTION_CI_ALPHA = 0.05

ICEBERG_CANDIDATE_HYPERPARAMETERS: Tuple[Dict[str, Any], ...] = (
    {
        "learning_rate": 0.05,
        "max_iter": 400,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 50,
        "l2_regularization": 2.0,
    },
    {
        "learning_rate": 0.08,
        "max_iter": 300,
        "max_leaf_nodes": 63,
        "min_samples_leaf": 100,
        "l2_regularization": 1.0,
    },
    {
        "learning_rate": 0.12,
        "max_iter": 200,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 200,
        "l2_regularization": 0.5,
    },
)


def _vectorized_haversine_km(
    lat1: np.ndarray, lon1: np.ndarray,
    lat2: np.ndarray, lon2: np.ndarray,
) -> np.ndarray:
    """Vectorised great-circle distance in km."""
    phi1 = np.radians(lat1)
    phi2 = np.radians(lat2)
    dphi = np.radians(lat2 - lat1)
    dlam = np.radians(lon2 - lon1)
    a = np.sin(dphi / 2.0) ** 2 + np.cos(phi1) * np.cos(phi2) * np.sin(dlam / 2.0) ** 2
    a = np.clip(a, 0.0, 1.0)
    c = 2.0 * np.arctan2(np.sqrt(a), np.sqrt(1.0 - a))
    return EARTH_RADIUS_KM * c


def _block_bootstrap_ci_by_berg(
    pred_err: np.ndarray,
    base_err: np.ndarray,
    berg_ids: np.ndarray,
    n_boot: int = 200,
    seed: int = 26059,
    alpha: float = ICEBERG_PROMOTION_CI_ALPHA,
) -> Tuple[float, float, float, float]:
    """Bootstrap (block-by-iceberg) CI of (model_rmse - baseline_rmse).

    Returns (model_rmse, baseline_rmse, ci_lo, ci_hi).
    Each bootstrap iteration resamples iceberg IDs with replacement and
    accumulates all rows for the resampled icebergs.
    """
    if len(pred_err) == 0 or len(base_err) == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")

    model_rmse = float(np.sqrt(np.mean(pred_err ** 2)))
    baseline_rmse = float(np.sqrt(np.mean(base_err ** 2)))

    unique_bergs = np.unique(berg_ids)
    if len(unique_bergs) < 2:
        return model_rmse, baseline_rmse, model_rmse - baseline_rmse, model_rmse - baseline_rmse

    berg_to_idx = {b: np.where(berg_ids == b)[0] for b in unique_bergs}

    rng = np.random.default_rng(seed)
    n_bergs = len(unique_bergs)
    boot_diffs = np.empty(n_boot)

    for i in range(n_boot):
        sampled = rng.choice(unique_bergs, size=n_bergs, replace=True)
        sel_p = np.concatenate([pred_err[berg_to_idx[b]] for b in sampled if len(berg_to_idx[b]) > 0])
        sel_b = np.concatenate([base_err[berg_to_idx[b]] for b in sampled if len(berg_to_idx[b]) > 0])
        if len(sel_p) == 0:
            boot_diffs[i] = model_rmse - baseline_rmse
            continue
        rm_p = float(np.sqrt(np.mean(sel_p ** 2)))
        rm_b = float(np.sqrt(np.mean(sel_b ** 2)))
        boot_diffs[i] = rm_p - rm_b

    ci_lo = float(np.percentile(boot_diffs, 100 * alpha / 2.0))
    ci_hi = float(np.percentile(boot_diffs, 100 * (1.0 - alpha / 2.0)))
    return model_rmse, baseline_rmse, ci_lo, ci_hi


@dataclass
class IcebergConformalCalibrator:
    """Split-conformal calibration for position error in km."""

    scores: np.ndarray
    alpha: float = 0.10

    def radius(self) -> float:
        """Return the prediction-interval radius (km) at 1-alpha."""
        n = len(self.scores)
        if n == 0:
            return 50.0
        q_idx = int(math.ceil((n + 1) * (1.0 - self.alpha))) - 1
        q_idx = max(0, min(q_idx, n - 1))
        return float(np.sort(self.scores)[q_idx])

    def p50_p90(self) -> Tuple[float, float]:
        """Return (p50, p90) error radii in km."""
        if len(self.scores) == 0:
            return 10.0, 50.0
        return float(np.percentile(self.scores, 50)), float(np.percentile(self.scores, 90))


@dataclass
class _LeadModel:
    """Pair of lat/lon residual models for one lead."""

    model_lat: Optional[HistGradientBoostingRegressor]
    model_lon: Optional[HistGradientBoostingRegressor]
    hyperparameters: Dict[str, Any]
    selection_log: List[Dict[str, Any]]


class IcebergForecaster:
    """Per-lead HistGradientBoostingRegressor forecasting iceberg drift residuals.

    For each lead L, trains two regressors (lat and lon) on the position
    residual (truth_pos - baseline_pos in degrees).  The full forecast
    is baseline_position + (residual_lat, residual_lon), and the error
    metric is the great-circle distance from the corrected position to
    the truth, in km.
    """

    model_name = "iceberg_forecaster"

    def __init__(
        self,
        leads: Sequence[int] = ICELEAD_DAYS,
        random_state: int = 26059,
    ) -> None:
        self.leads = tuple(int(l) for l in leads)
        self.random_state = random_state
        self.models: Dict[int, _LeadModel] = {}
        self.hyperparameters: Dict[int, Dict[str, Any]] = {}
        self.selection_log: Dict[int, List[Dict[str, Any]]] = {}
        self.conformal: Dict[int, IcebergConformalCalibrator] = {}
        self.metadata: Dict[str, Any] = {}
        self.taus: Dict[int, float] = {}
        self.feature_names: Tuple[str, ...] = FEATURE_NAMES_ICEBERG
        for lead in self.leads:
            self.models[lead] = _LeadModel(
                model_lat=None, model_lon=None,
                hyperparameters={}, selection_log=[],
            )

    def _rows_for_lead(self, ds: IcebergSplit, lead: int) -> Dict[str, np.ndarray]:
        mask = ds.lead_days == float(lead)
        return {
            "X": ds.X[mask],
            "y_lat": ds.y_lat[mask],
            "y_lon": ds.y_lon[mask],
            "base_lat": ds.baseline_lat[mask],
            "base_lon": ds.baseline_lon[mask],
            "truth_lat": ds.truth_lat[mask],
            "truth_lon": ds.truth_lon[mask],
            "base_err": ds.baseline_error_km[mask],
            "berg_id": ds.berg_id[mask],
            "month": ds.month[mask],
        }

    def predict_residual(
        self, ds: IcebergSplit, lead: int,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Predicted (lat_residual, lon_residual) for each row at ``lead``."""
        mask = ds.lead_days == float(lead)
        n = int(mask.sum())
        lat_res = np.zeros(n, dtype=np.float64)
        lon_res = np.zeros(n, dtype=np.float64)
        lm = self.models.get(lead)
        if lm is not None and n > 0 and lm.model_lat is not None and lm.model_lon is not None:
            X = ds.X[mask]
            lat_res = np.nan_to_num(lm.model_lat.predict(X), nan=0.0)
            lon_res = np.nan_to_num(lm.model_lon.predict(X), nan=0.0)
        return lat_res, lon_res

    def fit(
        self, train: IcebergSplit, val: IcebergSplit,
    ) -> "IcebergForecaster":
        """Train per-lead HistGradientBoostingRegistr for lat and lon residuals."""
        for lead in self.leads:
            t0 = time.perf_counter()
            lm, meta = self._train_one_lead(lead, train, val)
            self.models[lead] = lm
            fit_s = time.perf_counter() - t0
            print(
                f"   lead {lead:>2d}d  train {meta.get('n_train_rows', 0):>7d} rows  "
                f"val {meta.get('n_val_rows', 0):>6d}  fit {fit_s:.1f}s  "
                f"val_rmse {meta.get('val_full_rmse', float('nan'))}"
            )

        self.metadata = {
            "sklearn_version": sklearn.__version__,
            "estimator": "HistGradientBoostingRegressor (lat/lon residual pair)",
            "leads": list(self.leads),
            "feature_names": list(self.feature_names),
            "random_state": self.random_state,
            "per_lead_selection": self.selection_log,
        }
        return self

    def _train_one_lead(
        self, lead: int, train: IcebergSplit, val: IcebergSplit,
    ) -> Tuple[_LeadModel, Dict[str, Any]]:
        """Train and select models for one lead on the validation split."""
        tr = self._rows_for_lead(train, lead)
        va = self._rows_for_lead(val, lead)

        X_tr, y_tr_lat, y_tr_lon = tr["X"], tr["y_lat"], tr["y_lon"]
        X_val, y_val_lat, y_val_lon = va["X"], va["y_lat"], va["y_lon"]
        base_val_lat, base_val_lon = va["base_lat"], va["base_lon"]
        truth_val_lat, truth_val_lon = va["truth_lat"], va["truth_lon"]

        if len(X_tr) == 0 or len(X_val) == 0:
            model_lat = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **ICEBERG_CANDIDATE_HYPERPARAMETERS[0],
            )
            model_lon = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **ICEBERG_CANDIDATE_HYPERPARAMETERS[0],
            )
            X_dummy = np.zeros((1, len(self.feature_names)))
            y_dummy = np.zeros(1)
            model_lat.fit(X_dummy, y_dummy)
            model_lon.fit(X_dummy, y_dummy)
            self.selection_log[lead] = [{"note": "insufficient data for selection"}]
            self.conformal[lead] = IcebergConformalCalibrator(scores=np.array([0.0]))
            lm = _LeadModel(
                model_lat=model_lat, model_lon=model_lon,
                hyperparameters=dict(ICEBERG_CANDIDATE_HYPERPARAMETERS[0]),
                selection_log=self.selection_log[lead],
            )
            return lm, {
                "n_train_rows": 0, "n_val_rows": 0,
                "val_full_rmse": None, "note": "insufficient data for this lead",
            }

        selection: List[Dict[str, Any]] = []
        best_model_lat: Optional[HistGradientBoostingRegressor] = None
        best_model_lon: Optional[HistGradientBoostingRegressor] = None
        best_rmse = math.inf
        best_params: Dict[str, Any] = {}

        for params in ICEBERG_CANDIDATE_HYPERPARAMETERS:
            m_lat = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False, **params
            )
            m_lon = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False, **params
            )
            m_lat.fit(X_tr, y_tr_lat)
            m_lon.fit(X_tr, y_tr_lon)

            pred_lat = base_val_lat + m_lat.predict(X_val)
            pred_lon = base_val_lon + m_lon.predict(X_val)
            err = _vectorized_haversine_km(
                pred_lat, pred_lon, truth_val_lat, truth_val_lon
            )
            full_rmse = float(np.sqrt(np.mean(err ** 2)))

            val_rmse_lat = float(np.sqrt(np.mean((m_lat.predict(X_val) - y_val_lat) ** 2)))
            val_rmse_lon = float(np.sqrt(np.mean((m_lon.predict(X_val) - y_val_lon) ** 2)))

            selection.append({
                "lead": lead,
                "hyperparameters": dict(params),
                "val_residual_rmse_lat": round(val_rmse_lat, 6),
                "val_residual_rmse_lon": round(val_rmse_lon, 6),
                "val_full_rmse": round(full_rmse, 6),
                "selected": False,
            })
            if full_rmse < best_rmse:
                best_rmse = full_rmse
                best_model_lat = m_lat
                best_model_lon = m_lon
                best_params = dict(params)

        if best_model_lat is None:
            best_params = dict(ICEBERG_CANDIDATE_HYPERPARAMETERS[0])
            best_model_lat = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **best_params,
            )
            best_model_lon = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **best_params,
            )
            best_model_lat.fit(X_tr, y_tr_lat)
            best_model_lon.fit(X_tr, y_tr_lon)

        for entry in selection:
            entry["selected"] = entry["hyperparameters"] == best_params
        self.selection_log[lead] = selection
        self.hyperparameters[lead] = best_params

        # Conformal calibration on validation great-circle errors.
        val_pred_lat = base_val_lat + best_model_lat.predict(X_val)
        val_pred_lon = base_val_lon + best_model_lon.predict(X_val)
        val_err = _vectorized_haversine_km(
            val_pred_lat, val_pred_lon, truth_val_lat, truth_val_lon
        )
        self.conformal[lead] = IcebergConformalCalibrator(
            scores=np.sort(val_err),
        )

        lm = _LeadModel(
            model_lat=best_model_lat, model_lon=best_model_lon,
            hyperparameters=best_params,
            selection_log=self.selection_log[lead],
        )
        return lm, {
            "n_train_rows": int(len(X_tr)),
            "n_val_rows": int(len(X_val)),
            "val_full_rmse": round(best_rmse, 6),
        }

    def evaluate(
        self, ds: IcebergSplit, n_boot: int = 200, seed: int = 26059,
    ) -> Dict[str, Any]:
        """Full evaluation with promotion-gate logic and error radii."""
        per_lead_results: List[Dict[str, Any]] = []
        promoted: Dict[str, bool] = {}

        for lead in self.leads:
            r = self._rows_for_lead(ds, lead)
            mask = ds.lead_days == float(lead)
            if not np.any(mask):
                continue

            X_l = r["X"]
            base_lat = r["base_lat"]
            base_lon = r["base_lon"]
            truth_lat = r["truth_lat"]
            truth_lon = r["truth_lon"]
            base_err = r["base_err"]
            berg_ids = r["berg_id"]

            # Baseline (b): great-circle error of the 3-day velocity prediction.
            baseline_err = base_err.copy()

            # Baseline (a): no-movement error (t0 position held fixed).
            no_move_err = _vectorized_haversine_km(
                np.full_like(base_lat, np.nan),
                np.full_like(base_lon, np.nan),
                truth_lat, truth_lon,
            )
            # Actually compute no-movement: predict t0 position for all leads.
            t0_lat = ds.X[mask][:, 0]  # lat_t0
            t0_lon = ds.X[mask][:, 1]  # lon_t0
            no_move_err = _vectorized_haversine_km(
                t0_lat, t0_lon, truth_lat, truth_lon
            )

            # Model prediction.
            lm = self.models.get(lead)
            if lm is not None and lm.model_lat is not None and lm.model_lon is not None:
                residual_lat, residual_lon = self.predict_residual(ds, lead)
                pred_lat = base_lat + residual_lat
                pred_lon = base_lon + residual_lon
            else:
                pred_lat = base_lat
                pred_lon = base_lon

            pred_err = _vectorized_haversine_km(
                pred_lat, pred_lon, truth_lat, truth_lon
            )

            model_rmse, baseline_rmse, ci_lo, ci_hi = _block_bootstrap_ci_by_berg(
                pred_err, baseline_err, berg_ids, n_boot, seed + lead,
            )

            excludes_zero = bool(ci_lo > 0.0 or ci_hi < 0.0)
            beats = model_rmse < baseline_rmse and excludes_zero

            abs_err = np.abs(pred_err)
            median_err = float(np.median(abs_err)) if len(abs_err) > 0 else float("nan")
            p90_err = float(np.percentile(abs_err, 90)) if len(abs_err) > 0 else float("nan")

            no_move_rmse = float(np.sqrt(np.mean(no_move_err ** 2)))

            result: Dict[str, Any] = {
                "lead_days": lead,
                "model_rmse_km": round(model_rmse, 4) if math.isfinite(model_rmse) else None,
                "baseline_rmse_km": round(baseline_rmse, 4) if math.isfinite(baseline_rmse) else None,
                "rmse_diff_ci": [
                    round(ci_lo, 4) if math.isfinite(ci_lo) else None,
                    round(ci_hi, 4) if math.isfinite(ci_hi) else None,
                ],
                "rmse_diff_ci_excludes_zero": excludes_zero,
                "beats_baseline": beats,
                "skill_vs_baseline": round(1.0 - model_rmse / baseline_rmse, 5)
                    if baseline_rmse > 0 else None,
                "median_error_km": round(median_err, 4) if math.isfinite(median_err) else None,
                "p90_error_km": round(p90_err, 4) if math.isfinite(p90_err) else None,
                "baseline_a_no_movement_rmse_km": round(no_move_rmse, 4) if math.isfinite(no_move_rmse) else None,
                "n_samples": int(mask.sum()),
                "n_icebergs": int(len(np.unique(berg_ids))),
            }

            cal = self.conformal.get(lead)
            if cal is not None:
                p50, p90 = cal.p50_p90()
                result["cal_p50_km"] = round(p50, 4) if math.isfinite(p50) else None
                result["cal_p90_km"] = round(p90, 4) if math.isfinite(p90) else None
                result["cal_radius_km"] = round(cal.radius(), 4) if math.isfinite(cal.radius()) else None

            promoted[str(lead)] = beats
            per_lead_results.append(result)

        radii: Dict[str, Any] = {}
        for r in per_lead_results:
            if r.get("cal_p50_km") is not None:
                radii[str(r["lead_days"])] = {
                    "p50": r["cal_p50_km"],
                    "p90": r["cal_p90_km"],
                }

        overall_err: List[float] = []
        for lead in self.leads:
            r = self._rows_for_lead(ds, lead)
            mask = ds.lead_days == float(lead)
            if not np.any(mask):
                continue
            lm = self.models.get(lead)
            if lm is not None and lm.model_lat is not None and lm.model_lon is not None:
                residual_lat, residual_lon = self.predict_residual(ds, lead)
                pred_lat = r["base_lat"] + residual_lat
                pred_lon = r["base_lon"] + residual_lon
            else:
                pred_lat = r["base_lat"]
                pred_lon = r["base_lon"]
            err = _vectorized_haversine_km(
                pred_lat, pred_lon, r["truth_lat"], r["truth_lon"]
            )
            overall_err.extend(err.tolist())

        overall_rmse = float(np.sqrt(np.mean(overall_err))) if overall_err else float("nan")

        return {
            "n_samples": int(len(ds)),
            "feature_names": list(self.feature_names),
            "overall": {
                "model_rmse_km": round(overall_rmse, 4) if math.isfinite(overall_rmse) else None,
                "n_samples": len(overall_err),
            },
            "per_lead": per_lead_results,
            "promoted": {"iceberg": promoted},
            "radii": radii,
            "baseline_models": {
                "a": "no movement",
                "b": "3-day constant velocity",
                "c": "7-day constant velocity damped",
            },
            "metric": "great_circle_error_km",
            "note": (
                "Trained on BYU/NIC consolidated Antarctic iceberg database v6. "
                "Train 2005-2017, val 2018, test 2019-2022. Baseline (b) = 3-day velocity. "
                "Gate: ML must beat baseline (b) with bootstrap-CI-by-iceberg excluding zero."
            ),
        }

    def save(self, path: str | Path) -> Path:
        """Write the per-lead models and metadata to a joblib artefact."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_name": self.model_name,
            "models": {
                str(lead): {
                    "model_lat": lm.model_lat,
                    "model_lon": lm.model_lon,
                }
                for lead, lm in self.models.items()
            },
            "feature_names": list(self.feature_names),
            "hyperparameters": {str(k): v for k, v in self.hyperparameters.items()},
            "selection_log": {str(k): v for k, v in self.selection_log.items()},
            "calibration": {
                str(k): {
                    "scores": cal.scores,
                    "alpha": cal.alpha,
                }
                for k, cal in self.conformal.items()
            },
            "taus": {str(k): v for k, v in self.taus.items()},
            "metadata": self.metadata,
            "random_state": self.random_state,
            "leads": list(self.leads),
        }
        joblib.dump(payload, path)
        return path

    @classmethod
    def load(cls, path: str | Path) -> "IcebergForecaster":
        payload = joblib.load(Path(path))
        leads = tuple(int(l) for l in payload.get("leads", ICELEAD_DAYS))
        obj = cls(leads=leads, random_state=int(payload.get("random_state", 26059)))
        for lead_s, m in payload.get("models", {}).items():
            lead = int(lead_s)
            obj.models[lead] = _LeadModel(
                model_lat=m["model_lat"],
                model_lon=m["model_lon"],
                hyperparameters={},
                selection_log=[],
            )
        obj.feature_names = tuple(payload.get("feature_names", FEATURE_NAMES_ICEBERG))
        obj.hyperparameters = {int(k): v for k, v in payload.get("hyperparameters", {}).items()}
        obj.selection_log = {int(k): v for k, v in payload.get("selection_log", {}).items()}
        obj.taus = {int(k): v for k, v in payload.get("taus", {}).items()}
        obj.metadata = dict(payload.get("metadata", {}))
        for lead_s, cal in payload.get("calibration", {}).items():
            lead = int(lead_s)
            obj.conformal[lead] = IcebergConformalCalibrator(
                scores=cal["scores"], alpha=cal.get("alpha", 0.10),
            )
        return obj
