"""
Learned residual corrector for the iceberg drift momentum balance.

WHAT THIS IS, AND WHAT IT IS NOT. This is a residual learner sitting on top of a physics core.
The RK4 momentum balance in src/core/iceberg_tracker.py does the work; this module learns the
part of the observed velocity that the momentum balance systematically misses, and adds it back.
The corrected velocity is

    v_corrected = v_physics + f_theta(forcing, geometry, latitude, v_physics)

It is NOT a physics-informed neural network. A PINN puts the governing equation into the loss
function and penalises the network for violating it; nothing of that kind happens here. Calling
this a PINN would be a false claim, so the codebase does not make it. What can be said honestly
is narrower and still worth saying: the network never has to learn drift from scratch, it only
has to learn the error of a model that is already right to first order, so it trains on a few
thousand rows instead of needing a research archive, and it cannot produce an unphysical track
because the physics term dominates the sum.

WHY THERE IS A RESIDUAL TO LEARN. The forecast uses one air-drag and one water-drag coefficient
for every berg. Real form drag depends on the shape presented to the flow. dataset.py builds the
synthetic observations with shape-dependent true coefficients, reported geometry that carries
measurement error, and a perturbed wind. The learnable part is the shape dependence; the rest is
an irreducible floor that keeps the corrected position error from reaching zero.

THE METRIC THAT MATTERS. A velocity RMSE in metres per second means nothing to a navigator. The
number this module reports is the 72-hour position error in kilometres, for pure physics and for
physics plus residual, on bergs that were never seen during training.

HONEST LABELLING (build spec P2). The observed tracks are synthetic. Metrics here are
simulated-environment metrics, not verification against USNIC or BYU observed drift.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import sklearn
from sklearn.compose import TransformedTargetRegressor
from sklearn.linear_model import Ridge
from sklearn.neural_network import MLPRegressor
from sklearn.pipeline import Pipeline
from sklearn.preprocessing import StandardScaler

from src.core.geo import haversine_km
from src.ml.dataset import DriftDataset


def _rmse(a: np.ndarray, b: np.ndarray) -> float:
    return float(np.sqrt(np.mean((np.asarray(a) - np.asarray(b)) ** 2)))


def _build_mlp(random_state: int) -> TransformedTargetRegressor:
    """
    Two hidden layers, inputs and targets both standardised.

    The targets are velocity residuals of order a few centimetres per second while the inputs run
    to tens of metres per second. Without standardising both ends the optimiser spends its budget
    rescaling rather than fitting, so the target transform is not cosmetic.
    """
    return TransformedTargetRegressor(
        regressor=Pipeline(
            [
                ("scale", StandardScaler()),
                (
                    "mlp",
                    MLPRegressor(
                        hidden_layer_sizes=(96, 64),
                        activation="relu",
                        alpha=1e-3,
                        learning_rate_init=1e-3,
                        max_iter=800,
                        early_stopping=True,
                        n_iter_no_change=25,
                        validation_fraction=0.15,
                        random_state=random_state,
                    ),
                ),
            ]
        ),
        transformer=StandardScaler(),
    )


def _build_ridge() -> TransformedTargetRegressor:
    """Linear fallback. Also the honest floor: if the MLP cannot beat this, say so."""
    return TransformedTargetRegressor(
        regressor=Pipeline([("scale", StandardScaler()), ("ridge", Ridge(alpha=1.0))]),
        transformer=StandardScaler(),
    )


class DriftResidualModel:
    """
    Physics-informed residual corrector: MLP by default, Ridge when the MLP cannot beat it.

    The choice is made on the validation split and recorded in metadata, so the artefact always
    says which estimator is actually inside it.
    """

    model_name = "drift_residual"

    def __init__(self, random_state: int = 26_059) -> None:
        self.random_state = random_state
        self.model: Optional[TransformedTargetRegressor] = None
        self.estimator_kind: str = ""
        self.feature_names: Tuple[str, ...] = ()
        self.target_names: Tuple[str, ...] = ()
        self.metadata: Dict[str, Any] = {}

    # ------------------------------------------------------------------ fitting
    def fit(self, train: DriftDataset, val: Optional[DriftDataset] = None) -> "DriftResidualModel":
        """
        Fit the MLP, then keep it only if it beats Ridge on the validation split.

        An MLP on a few thousand rows of a noisy residual can diverge or settle into a worse
        optimum than a linear fit. Rather than assert that the network is better, this measures
        it and takes the winner.
        """
        self.feature_names = tuple(train.feature_names)
        self.target_names = tuple(train.target_names)

        candidates: List[Tuple[str, Any]] = []
        mlp = _build_mlp(self.random_state)
        try:
            mlp.fit(train.X, train.y)
            if np.all(np.isfinite(mlp.predict(train.X))):
                candidates.append(("mlp", mlp))
        except Exception:  # pragma: no cover - guards a genuinely unstable optimisation
            pass

        ridge = _build_ridge()
        ridge.fit(train.X, train.y)
        candidates.append(("ridge", ridge))

        selection: List[Dict[str, Any]] = []
        best_kind, best_model, best_rmse = None, None, float("inf")
        for kind, model in candidates:
            if val is None or len(val) == 0:
                best_kind, best_model = kind, model
                selection.append({"estimator": kind, "val_residual_rmse_ms": None, "selected": True})
                break
            rmse = _rmse(model.predict(val.X), val.y)
            selection.append({"estimator": kind, "val_residual_rmse_ms": round(rmse, 6), "selected": False})
            if rmse < best_rmse:
                best_kind, best_model, best_rmse = kind, model, rmse

        for entry in selection:
            entry["selected"] = entry["estimator"] == best_kind

        self.model = best_model
        self.estimator_kind = str(best_kind)
        self.metadata = {
            "sklearn_version": sklearn.__version__,
            "estimator": self.estimator_kind,
            "n_train_rows": int(len(train)),
            "n_val_rows": int(len(val)) if val is not None else 0,
            "n_train_bergs": int(np.unique(train.berg_index).size),
            "train_window_hours": list(train.window_hours),
            "val_window_hours": list(val.window_hours) if val is not None else None,
            "feature_names": list(self.feature_names),
            "target_names": list(self.target_names),
            "estimator_selection": selection,
            "random_state": self.random_state,
            "claim": (
                "Residual corrector on an RK4 physics core. Not a physics-informed neural "
                "network: the governing equation is not part of the loss function."
            ),
        }
        return self

    # --------------------------------------------------------------- prediction
    def predict(self, X: np.ndarray) -> np.ndarray:
        """Velocity residual in m/s, shape (n, 2) as (du, dv)."""
        if self.model is None:
            raise RuntimeError("DriftResidualModel.predict called before fit or load.")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return np.asarray(self.model.predict(X), dtype=np.float64).reshape(X.shape[0], 2)

    def correct(self, X: np.ndarray, physics_uv: np.ndarray) -> np.ndarray:
        """Physics velocity plus the learned residual, which is what a caller actually wants."""
        return np.asarray(physics_uv, dtype=np.float64) + self.predict(X)

    # --------------------------------------------------------------- evaluation
    def _track_features(self, tracks: Dict[str, np.ndarray], step: int) -> np.ndarray:
        """Rebuild the feature matrix for one output step of every berg in a track set."""
        return np.column_stack(
            [
                tracks["nominal_ua"][step],
                tracks["nominal_va"][step],
                tracks["nominal_uo"][step],
                tracks["nominal_vo"][step],
                tracks["rep_length"],
                tracks["rep_width"],
                tracks["rep_sail"],
                tracks["rep_keel"],
                tracks["nominal_lat"][step],
                tracks["nominal_u"][step],
                tracks["nominal_v"][step],
            ]
        )

    def position_error(self, ds: DriftDataset) -> Dict[str, Any]:
        """
        Integrate both forecasts forward and measure how far each ends up from the observed berg.

        Both the physics-only and the corrected track are integrated with the SAME forward-Euler
        scheme on the output grid, starting from the same initial position. That matters: the
        stored nominal track came from a sub-stepped RK4 integration, so comparing an Euler
        reconstruction against it would credit the residual model with a discretisation
        difference it did not earn. The RK4 track's own error is reported alongside as
        physics_rk4, so the size of that discretisation gap is visible rather than hidden.
        """
        tracks = ds.tracks
        hours = np.asarray(tracks["hour"], dtype=np.float64)
        n_out = hours.size
        n_bergs = int(tracks["nominal_lat"].shape[1])
        dt_s = float(tracks["output_interval_h"][0]) * 3600.0

        lat_phys = np.array(tracks["lat0"], dtype=np.float64, copy=True)
        lon_phys = np.array(tracks["lon0"], dtype=np.float64, copy=True)
        lat_corr = lat_phys.copy()
        lon_corr = lon_phys.copy()

        for step in range(n_out - 1):
            u_phys = tracks["nominal_u"][step]
            v_phys = tracks["nominal_v"][step]
            residual = self.predict(self._track_features(tracks, step))

            cos_p = np.maximum(0.02, np.cos(np.radians(lat_phys)))
            lat_phys = lat_phys + v_phys * dt_s / 111_132.0
            lon_phys = lon_phys + u_phys * dt_s / (111_320.0 * cos_p)

            cos_c = np.maximum(0.02, np.cos(np.radians(lat_corr)))
            lat_corr = lat_corr + (v_phys + residual[:, 1]) * dt_s / 111_132.0
            lon_corr = lon_corr + (u_phys + residual[:, 0]) * dt_s / (111_320.0 * cos_c)

        obs_lat = tracks["observed_lat"][-1]
        obs_lon = tracks["observed_lon"][-1]
        rk4_lat = tracks["nominal_lat"][-1]
        rk4_lon = tracks["nominal_lon"][-1]

        def errors(lat: np.ndarray, lon: np.ndarray) -> np.ndarray:
            return np.array(
                [haversine_km(float(obs_lat[i]), float(obs_lon[i]), float(lat[i]), float(lon[i]))
                 for i in range(n_bergs)]
            )

        err_phys = errors(lat_phys, lon_phys)
        err_corr = errors(lat_corr, lon_corr)
        err_rk4 = errors(rk4_lat, rk4_lon)

        def stats(e: np.ndarray) -> Dict[str, float]:
            return {
                "mean_km": round(float(np.mean(e)), 4),
                "median_km": round(float(np.median(e)), 4),
                "p90_km": round(float(np.percentile(e, 90)), 4),
                "max_km": round(float(np.max(e)), 4),
            }

        mean_phys = float(np.mean(err_phys))
        mean_corr = float(np.mean(err_corr))
        median_phys = float(np.median(err_phys))
        median_corr = float(np.median(err_corr))

        return {
            "horizon_hours": float(hours[-1]),
            "n_bergs": n_bergs,
            "physics_euler": stats(err_phys),
            "physics_plus_residual": stats(err_corr),
            "physics_rk4_reference": stats(err_rk4),
            "mean_improvement_km": round(mean_phys - mean_corr, 4),
            "mean_improvement_percent": round(
                100.0 * (mean_phys - mean_corr) / mean_phys if mean_phys > 1e-9 else 0.0, 3
            ),
            "median_improvement_percent": round(
                100.0 * (median_phys - median_corr) / median_phys if median_phys > 1e-9 else 0.0, 3
            ),
            "bergs_improved_fraction": round(float(np.mean(err_corr < err_phys)), 4),
        }

    def evaluate(self, ds: DriftDataset) -> Dict[str, Any]:
        """Velocity-residual accuracy plus the 72-hour position error that actually matters."""
        pred = self.predict(ds.X)
        zero_rmse = _rmse(np.zeros_like(ds.y), ds.y)
        model_rmse = _rmse(pred, ds.y)
        return {
            "n_samples": int(len(ds)),
            "n_bergs": int(np.unique(ds.berg_index).size),
            "window_hours": list(ds.window_hours),
            "residual_rmse_ms": round(model_rmse, 6),
            "residual_mae_ms": round(float(np.mean(np.abs(pred - ds.y))), 6),
            "uncorrected_residual_rmse_ms": round(zero_rmse, 6),
            "residual_variance_explained": round(
                float(1.0 - (model_rmse ** 2) / (zero_rmse ** 2)) if zero_rmse > 1e-12 else float("nan"), 5
            ),
            "position_error": self.position_error(ds),
            "note": (
                "Observed tracks are synthetic, generated by perturbing the same RK4 momentum "
                "balance. Simulated-environment metrics, not USNIC or BYU verification."
            ),
        }

    # ------------------------------------------------------------- persistence
    def save(self, path: str | Path) -> Path:
        if self.model is None:
            raise RuntimeError("DriftResidualModel.save called before fit.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model_name": self.model_name,
                "model": self.model,
                "estimator_kind": self.estimator_kind,
                "feature_names": list(self.feature_names),
                "target_names": list(self.target_names),
                "metadata": self.metadata,
                "random_state": self.random_state,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "DriftResidualModel":
        payload = joblib.load(Path(path))
        obj = cls(random_state=int(payload.get("random_state", 26_059)))
        obj.model = payload["model"]
        obj.estimator_kind = str(payload.get("estimator_kind", ""))
        obj.feature_names = tuple(payload.get("feature_names", ()))
        obj.target_names = tuple(payload.get("target_names", ()))
        obj.metadata = dict(payload.get("metadata", {}))
        return obj
