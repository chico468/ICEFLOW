"""Per-lead HistGradientBoosting sea-ice concentration forecaster on real data.

Trains one gradient-boosted regressor per lead time (3, 7, 14 days) to predict
the concentration *residual* (truth - damped-anomaly-persistence baseline).
The final forecast is baseline + residual.

The baseline is not a fixed tau=30; tau is tuned per lead on the training block
(see src/eval/baselines.fit_damped_tau). The model competes against a baseline
that already has that lead's best achievable damped persistence.

Uncertainty is split-conformal on the validation residuals, stratified by lead
and forecast-concentration bin, producing clipped [0, 1] 90% intervals.

Promotion gate: a lead is promoted only if the model's RMSE beats the tuned
baseline with the bootstrap CI of the RMSE difference excluding zero, in BOTH
all-season and austral-departure (Nov-Mar), on the variable ice zone.
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

from src.ml.real_dataset import RealSICSplit, FEATURE_NAMES_REAL, REAL_LEAD_DAYS


PROMOTION_CI_ALPHA = 0.05  # 95% CI of RMSE difference must exclude zero
AUSTRAL_DEPARTURE_SEASON = (11, 12, 1, 2, 3)


CANDIDATE_HYPERPARAMETERS: Tuple[Dict[str, Any], ...] = (
    {
        "learning_rate": 0.05,
        "max_iter": 400,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 100,
        "l2_regularization": 2.0,
    },
    {
        "learning_rate": 0.08,
        "max_iter": 300,
        "max_leaf_nodes": 63,
        "min_samples_leaf": 200,
        "l2_regularization": 1.0,
    },
    {
        "learning_rate": 0.12,
        "max_iter": 200,
        "max_leaf_nodes": 31,
        "min_samples_leaf": 500,
        "l2_regularization": 0.5,
    },
)


def _rmse(pred: np.ndarray, truth: np.ndarray, mask: np.ndarray) -> float:
    diff = pred[mask] - truth[mask]
    return float(np.sqrt(np.mean(diff ** 2))) if len(diff) > 0 else float("nan")


def _compute_rmse_diff_ci(
    pred: np.ndarray,
    truth: np.ndarray,
    baseline: np.ndarray,
    month: np.ndarray,
    mask: np.ndarray,
    n_boot: int = 200,
    seed: int = 26059,
) -> Tuple[float, float, float, float]:
    """Bootstrap (block-by-month) CI of (RMSE_model - RMSE_baseline).

    Returns (model_rmse, baseline_rmse, ci_lo, ci_hi).
    """
    m = mask
    if m.sum() == 0:
        return float("nan"), float("nan"), float("nan"), float("nan")

    p = pred[m]
    t = truth[m]
    b = baseline[m]
    months = month[m].astype(int)

    model_rmse = _rmse(p, t, np.ones(len(p), dtype=bool))
    baseline_rmse = _rmse(b, t, np.ones(len(p), dtype=bool))
    point_diff = model_rmse - baseline_rmse

    unique_months = sorted(set(months))
    if len(unique_months) < 2:
        return model_rmse, baseline_rmse, point_diff, point_diff

    blocks_p = [p[months == mk] for mk in unique_months]
    blocks_t = [t[months == mk] for mk in unique_months]
    blocks_b = [b[months == mk] for mk in unique_months]

    rng = np.random.default_rng(seed)
    n_blocks = len(unique_months)
    idx = rng.integers(0, n_blocks, size=(n_boot, n_blocks))
    boot_diffs = np.empty(n_boot)
    for i in range(n_boot):
        sel = idx[i]
        bp = np.concatenate([blocks_p[j] for j in sel])
        bt = np.concatenate([blocks_t[j] for j in sel])
        bb = np.concatenate([blocks_b[j] for j in sel])
        if len(bt) == 0:
            boot_diffs[i] = point_diff
            continue
        rm_p = float(np.sqrt(np.mean((bp - bt) ** 2)))
        rm_b = float(np.sqrt(np.mean((bb - bt) ** 2)))
        boot_diffs[i] = rm_p - rm_b

    alpha = PROMOTION_CI_ALPHA
    ci_lo = float(np.percentile(boot_diffs, 100 * alpha / 2.0))
    ci_hi = float(np.percentile(boot_diffs, 100 * (1.0 - alpha / 2.0)))
    return model_rmse, baseline_rmse, ci_lo, ci_hi


@dataclass
class ConformalCalibrator:
    """Split-conformal calibration, per lead with forecast-concentration bins."""

    scores: np.ndarray
    bins: np.ndarray
    alpha: float = 0.10

    def interval(self, forecast: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        """Return (lower, upper) prediction interval at 1-alpha."""
        n = len(self.scores)
        if n == 0:
            return np.clip(forecast - 0.1, 0, 1), np.clip(forecast + 0.1, 0, 1)

        q_idx = int(math.ceil((n + 1) * (1.0 - self.alpha))) - 1
        q_idx = max(0, min(q_idx, n - 1))
        q = float(np.sort(self.scores)[q_idx])

        lo = np.clip(forecast - q, 0.0, 1.0)
        hi = np.clip(forecast + q, 0.0, 1.0)
        return lo, hi


class RealSICForecaster:
    """Per-lead HistGradientBoostingRegressor forecasting SIC residuals.

    For each lead L:
      * HistGradientBoostingRegressor trained on (X, y) where y = truth - baseline.
      * Selected on validation RMSE of the full forecast (baseline + residual).
      * Split-conformal calibration on validation residuals for prediction intervals.

    Final forecast for lead L = baseline + model.predict(X), clipped to [0, 1].
    """

    model_name = "real_sic_forecaster"

    def __init__(
        self,
        leads: Sequence[int] = REAL_LEAD_DAYS,
        random_state: int = 26059,
    ) -> None:
        self.leads = tuple(int(l) for l in leads)
        self.random_state = random_state
        self.models: Dict[int, Optional[HistGradientBoostingRegressor]] = {}
        self.hyperparameters: Dict[int, Dict[str, Any]] = {}
        self.selection_log: Dict[int, List[Dict[str, Any]]] = {}
        self.conformal: Dict[int, ConformalCalibrator] = {}
        self.taus: Dict[int, float] = {}
        self.metadata: Dict[str, Any] = {}
        self.feature_names: Tuple[str, ...] = FEATURE_NAMES_REAL
        for lead in self.leads:
            self.models[lead] = None

    def _rows_for_lead(self, ds: RealSICSplit, lead: int) -> Tuple[np.ndarray, ...]:
        mask = (ds.lead_days == float(lead)) & np.isfinite(ds.y) & np.isfinite(ds.truth)
        return (
            ds.X[mask], ds.y[mask], ds.baseline[mask],
            ds.truth[mask], ds.persistence[mask], ds.month[mask],
        )

    def _train_one_lead(
        self, lead: int, ds_train: RealSICSplit, ds_val: RealSICSplit,
    ) -> Tuple[HistGradientBoostingRegressor, Dict[str, Any], Dict[str, Any]]:
        """Train and select a model for one lead on the validation split."""
        X_tr, y_tr, _, _, _, _ = self._rows_for_lead(ds_train, lead)
        X_val, y_val, base_val, truth_val, _, month_val = self._rows_for_lead(ds_val, lead)

        if len(X_tr) == 0 or len(X_val) == 0:
            model = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **CANDIDATE_HYPERPARAMETERS[0],
            )
            X_dummy = np.zeros((1, len(self.feature_names)))
            y_dummy = np.zeros(1)
            if len(X_tr) > 0:
                X_dummy, y_dummy = X_tr, y_tr
            model.fit(X_dummy, y_dummy)
            self.selection_log[lead] = [{"note": "insufficient data for selection"}]
            self.conformal[lead] = ConformalCalibrator(
                scores=np.array([0.0]), bins=np.array([0.0, 1.0]))
            return model, dict(CANDIDATE_HYPERPARAMETERS[0]), {
                "n_train_rows": int(len(X_tr)), "n_val_rows": int(len(X_val)),
                "val_full_rmse": None, "note": "insufficient data for this lead",
            }

        selection: List[Dict[str, Any]] = []
        best_model: Optional[HistGradientBoostingRegressor] = None
        best_rmse = math.inf
        best_params: Dict[str, Any] = {}

        for params in CANDIDATE_HYPERPARAMETERS:
            model = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False, **params
            )
            model.fit(X_tr, y_tr)

            val_pred = np.clip(model.predict(X_val), -1.0, 1.0)
            val_rmse_residual = float(np.sqrt(np.mean((val_pred - y_val) ** 2)))
            full_pred = np.clip(base_val + val_pred, 0.0, 1.0)
            full_rmse = _rmse(full_pred, truth_val, np.ones(len(truth_val), dtype=bool))

            selection.append({
                "lead": lead,
                "hyperparameters": dict(params),
                "val_residual_rmse": round(val_rmse_residual, 6),
                "val_full_rmse": round(full_rmse, 6),
                "selected": False,
            })
            if full_rmse < best_rmse:
                best_rmse = full_rmse
                best_model = model
                best_params = dict(params)

        if best_model is None:
            best_model = HistGradientBoostingRegressor(
                random_state=self.random_state, early_stopping=False,
                **CANDIDATE_HYPERPARAMETERS[0],
            )
            best_model.fit(X_tr, y_tr)
            best_params = dict(CANDIDATE_HYPERPARAMETERS[0])

        for entry in selection:
            entry["selected"] = entry["hyperparameters"] == best_params
        self.selection_log[lead] = selection
        self.hyperparameters[lead] = best_params

        # Split-conformal calibration on validation residuals.
        full_pred_val = np.clip(base_val + best_model.predict(X_val), 0.0, 1.0)
        residuals = np.abs(truth_val - full_pred_val)
        scores_sorted = np.sort(residuals)
        bin_edges = np.percentile(full_pred_val, [0, 25, 50, 75, 100])
        bin_edges = np.unique(bin_edges)
        if len(bin_edges) < 2:
            bin_edges = np.array([0.0, 1.0])

        self.conformal[lead] = ConformalCalibrator(
            scores=scores_sorted, bins=bin_edges, alpha=0.10,
        )

        return best_model, dict(best_params), {
            "n_train_rows": int(len(X_tr)),
            "n_val_rows": int(len(X_val)),
            "val_full_rmse": round(best_rmse, 6),
        }

    def fit(
        self, train: RealSICSplit, val: RealSICSplit, taus: Dict[int, float],
    ) -> "RealSICForecaster":
        """Train one HistGradientBoostingRegressor per lead on real data."""
        self.taus = dict(taus)

        for lead in self.leads:
            t0 = time.perf_counter()
            model, hp, meta = self._train_one_lead(lead, train, val)
            self.models[lead] = model
            fit_s = time.perf_counter() - t0

            lead_mask = val.lead_days == float(lead)
            n_val = int(lead_mask.sum())
            val_rmse_str = f"{meta.get('val_full_rmse', float('nan'))}"
            print(
                f"   lead {lead:>2d}d  train {meta.get('n_train_rows', 0):>7d} rows  "
                f"val {n_val:>6d}  fit {fit_s:.1f}s  val_rmse {val_rmse_str}"
            )

        self.metadata = {
            "sklearn_version": sklearn.__version__,
            "estimator": "HistGradientBoostingRegressor",
            "leads": list(self.leads),
            "feature_names": list(self.feature_names),
            "random_state": self.random_state,
            "taus": {str(k): v for k, v in self.taus.items()},
            "per_lead_selection": self.selection_log,
        }
        return self

    def predict_full(self, ds: RealSICSplit) -> np.ndarray:
        """Full forecast (baseline + residual) for every row, clipped to [0, 1]."""
        out = np.empty(len(ds), dtype=np.float64)
        for lead in self.leads:
            mask = ds.lead_days == float(lead)
            if not np.any(mask):
                continue
            model = self.models.get(lead)
            if model is None:
                out[mask] = ds.baseline[mask]
                continue
            X = ds.X[mask]
            residual = np.clip(np.nan_to_num(model.predict(X), nan=0.0), -1.0, 1.0)
            base_v = np.nan_to_num(ds.baseline[mask], nan=0.5)
            out[mask] = np.clip(base_v + residual, 0.0, 1.0)
        return out

    def predict_interval(
        self, ds: RealSICSplit, alpha: float = 0.10,
    ) -> Tuple[np.ndarray, np.ndarray]:
        """Prediction interval (default 90%) per row."""
        lo = np.empty(len(ds), dtype=np.float64)
        hi = np.empty(len(ds), dtype=np.float64)
        full_pred = self.predict_full(ds)
        for lead in self.leads:
            mask = ds.lead_days == float(lead)
            if not np.any(mask):
                continue
            fc = full_pred[mask]
            cal = self.conformal.get(lead)
            if cal is None:
                lo[mask] = np.clip(fc - 0.1, 0, 1)
                hi[mask] = np.clip(fc + 0.1, 0, 1)
            else:
                l, h = cal.interval(fc)
                lo[mask] = l
                hi[mask] = h
        return lo, hi

    def evaluate(
        self, ds: RealSICSplit, n_boot: int = 200, seed: int = 26059,
    ) -> Dict[str, Any]:
        """Full evaluation with promotion-gate logic and coverage metrics."""
        full_pred = self.predict_full(ds)
        truth = ds.truth

        def score_block(mask: np.ndarray) -> Dict[str, Any]:
            m = mask & np.isfinite(full_pred) & np.isfinite(truth)
            if m.sum() == 0:
                return {"n_samples": 0, "model_rmse": float("nan"),
                        "baseline_rmse": float("nan"),
                        "persistence_rmse": float("nan"),
                        "skill_vs_baseline": float("nan"),
                        "rmse_diff_ci": [float("nan"), float("nan")],
                        "rmse_diff_ci_excludes_zero": False}
            t = truth[m]
            p = full_pred[m]
            b = ds.baseline[m]
            pers = ds.persistence[m]
            mo = _compute_rmse_diff_ci(
                full_pred, truth, ds.baseline, ds.month, m, n_boot, seed,
            )
            model_rmse = _rmse(p, t, np.ones(len(t), dtype=bool))
            baseline_rmse = _rmse(b, t, np.ones(len(t), dtype=bool))
            pers_rmse = _rmse(pers, t, np.ones(len(t), dtype=bool))
            return {
                "n_samples": int(m.sum()),
                "model_rmse": round(model_rmse, 5),
                "baseline_rmse": round(baseline_rmse, 5),
                "persistence_rmse": round(pers_rmse, 5),
                "skill_vs_baseline": round(1.0 - model_rmse / baseline_rmse, 5)
                    if baseline_rmse > 0 else float("nan"),
                "rmse_diff_ci": [round(mo[2], 5), round(mo[3], 5)],
                "rmse_diff_ci_excludes_zero": bool(mo[2] > 0.0 or mo[3] < 0.0),
            }

        per_lead: List[Dict[str, Any]] = []
        for lead in self.leads:
            mask = ds.lead_days == float(lead)
            if not np.any(mask):
                continue

            # VIZ cells: truth between 5% and 95%.
            viz_mask = mask & (truth >= 0.05) & (truth <= 0.95)
            novmar_viz_mask = viz_mask & np.isin(
                ds.month, np.array(AUSTRAL_DEPARTURE_SEASON, dtype=float)
            )

            # All-season VIZ CI.
            _, _, ci_lo_viz, ci_hi_viz = _compute_rmse_diff_ci(
                full_pred, truth, ds.baseline, ds.month, viz_mask, n_boot, seed + 1,
            )
            all_season_excludes = bool(ci_lo_viz > 0.0 or ci_hi_viz < 0.0)

            # Nov-Mar VIZ CI.
            if np.any(novmar_viz_mask):
                _, _, ci_lo_nm, ci_hi_nm = _compute_rmse_diff_ci(
                    full_pred, truth, ds.baseline, ds.month,
                    novmar_viz_mask, n_boot, seed + 2,
                )
                novmar_excludes = bool(ci_lo_nm > 0.0 or ci_hi_nm < 0.0)
            else:
                ci_lo_nm, ci_hi_nm = float("nan"), float("nan")
                novmar_excludes = False

            model_rmse_viz = _rmse(
                full_pred[viz_mask], truth[viz_mask],
                np.ones(int(viz_mask.sum()), dtype=bool),
            )
            baseline_rmse_viz = _rmse(
                ds.baseline[viz_mask], truth[viz_mask],
                np.ones(int(viz_mask.sum()), dtype=bool),
            )

            promoted = bool(
                all_season_excludes and novmar_excludes
                and model_rmse_viz < baseline_rmse_viz
            )

            block = score_block(mask)
            block["lead_days"] = lead
            block["viz_model_rmse"] = round(model_rmse_viz, 5)
            block["viz_baseline_rmse"] = round(baseline_rmse_viz, 5)
            block["viz_rmse_diff_ci"] = [round(ci_lo_viz, 5), round(ci_hi_viz, 5)]
            block["viz_nov_mar_rmse_diff_ci"] = [
                round(ci_lo_nm, 5) if np.isfinite(ci_lo_nm) else float("nan"),
                round(ci_hi_nm, 5) if np.isfinite(ci_hi_nm) else float("nan"),
            ]
            block["viz_rmse_diff_ci_excludes_zero_all_season"] = all_season_excludes
            block["viz_rmse_diff_ci_excludes_zero_nov_mar"] = novmar_excludes
            block["promoted"] = promoted
            per_lead.append(block)

        overall = score_block(np.ones(len(ds), dtype=bool))
        overall["window_years"] = list(ds.window_years)

        # Coverage.
        lo, hi = self.predict_interval(ds, alpha=0.10)
        inside = (truth >= lo) & (truth <= hi) & np.isfinite(truth)
        coverage = {"overall": round(float(np.mean(inside)), 4), "per_lead": {}}
        for lead in self.leads:
            m = ds.lead_days == float(lead)
            if np.any(m):
                coverage["per_lead"][str(lead)] = round(float(np.mean(inside[m])), 4)

        return {
            "n_samples": int(len(ds)),
            "feature_names": list(self.feature_names),
            "overall": overall,
            "per_lead": per_lead,
            "promoted_leads": [pl["lead_days"] for pl in per_lead if pl.get("promoted")],
            "coverage_90_ci": coverage,
            "taus": {str(k): v for k, v in self.taus.items()},
            "note": (
                "Trained on real NSIDC V6 observations (2005-2019), validated on "
                "2020-2021, tested on 2022-2024. Per-lead HistGradientBoostingRegressor "
                "on damped-anomaly-persistence residuals with tuned per-lead tau."
            ),
        }

    def save(self, path: str | Path) -> Path:
        """Write the per-lead models and metadata to a joblib artefact."""
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        payload = {
            "model_name": self.model_name,
            "models": {str(k): v for k, v in self.models.items()},
            "feature_names": list(self.feature_names),
            "hyperparameters": {str(k): v for k, v in self.hyperparameters.items()},
            "selection_log": {str(k): v for k, v in self.selection_log.items()},
            "conformal": {
                str(k): {
                    "scores": cal.scores,
                    "bins": cal.bins,
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
    def load(cls, path: str | Path) -> "RealSICForecaster":
        payload = joblib.load(Path(path))
        leads = tuple(int(l) for l in payload.get("leads", REAL_LEAD_DAYS))
        obj = cls(leads=leads, random_state=int(payload.get("random_state", 26059)))
        obj.models = {int(k): v for k, v in payload.get("models", {}).items()}
        obj.feature_names = tuple(payload.get("feature_names", FEATURE_NAMES_REAL))
        obj.hyperparameters = {int(k): v for k, v in payload.get("hyperparameters", {}).items()}
        obj.selection_log = {int(k): v for k, v in payload.get("selection_log", {}).items()}
        obj.taus = {int(k): v for k, v in payload.get("taus", {}).items()}
        obj.metadata = dict(payload.get("metadata", {}))
        for lead_s, cal in payload.get("conformal", {}).items():
            lead = int(lead_s)
            obj.conformal[lead] = ConformalCalibrator(
                scores=cal["scores"], bins=cal["bins"], alpha=cal["alpha"],
            )
        return obj
