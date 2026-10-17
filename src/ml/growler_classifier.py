"""
Growler versus sea-clutter discrimination for the near-field radar layer.

THE PROBLEM. An X-band marine radar in a rising sea paints the near field with breaking-wave
returns. A growler - a metre-scale lump of glacial ice with almost no freeboard - produces a
comparable echo, and it is the target that holes hulls. A fixed amplitude threshold either
drowns the operator in clutter or suppresses the one contact that matters, which is why watch
officers turn sea clutter control up and lose targets with it.

WHAT THIS MODEL DOES. A random forest over eight radar-return features decides, per blob,
whether the echo is ice or clutter, and predict_proba supplies the calibrated confidence that
src/core/growler_radar.py wants for its detection_confidence field. Nothing in the radar module
depends on this classifier existing; see registry.ml_status().

BASELINES. Two, both scored on the same held-out scenes: the majority class, and a single
threshold on signal-to-clutter-plus-noise ratio with the cut chosen on the validation split.
The threshold baseline is the honest bar, because a threshold is exactly what the hardware
already gives you for free.

HONEST LABELLING (build spec P2). Returns are generated from a radar-equation model in
src/ml/dataset.py, not recorded from a real PPI. Metrics are simulated-environment metrics.
"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import joblib
import numpy as np
import sklearn
from sklearn.ensemble import RandomForestClassifier
from sklearn.metrics import (
    accuracy_score,
    confusion_matrix,
    f1_score,
    precision_score,
    recall_score,
    roc_auc_score,
)

from src.ml.dataset import GrowlerDataset

DEFAULT_HYPERPARAMETERS: Dict[str, Any] = {
    "n_estimators": 300,
    "max_depth": 14,
    "min_samples_leaf": 3,
    "max_features": "sqrt",
    "n_jobs": -1,
}


class GrowlerClassifier:
    """Random forest over radar-blob features, with a probability output for the radar module."""

    model_name = "growler_classifier"

    def __init__(self, random_state: int = 26_059) -> None:
        self.random_state = random_state
        self.model: Optional[RandomForestClassifier] = None
        self.feature_names: Tuple[str, ...] = ()
        self.hyperparameters: Dict[str, Any] = {}
        self.snr_threshold: Optional[float] = None
        self.metadata: Dict[str, Any] = {}

    # ------------------------------------------------------------------ fitting
    def fit(
        self,
        train: GrowlerDataset,
        val: Optional[GrowlerDataset] = None,
        hyperparameters: Optional[Dict[str, Any]] = None,
    ) -> "GrowlerClassifier":
        """
        Fit the forest, and fit the threshold baseline it has to beat.

        The threshold baseline is chosen on the validation split by sweeping the SNR cut for the
        best F1. Choosing it on the test split would flatter the baseline; choosing it on the
        training split would flatter the forest. The validation split is the right place.
        """
        self.feature_names = tuple(train.feature_names)
        self.hyperparameters = dict(hyperparameters or DEFAULT_HYPERPARAMETERS)
        self.model = RandomForestClassifier(random_state=self.random_state, **self.hyperparameters)
        self.model.fit(train.X, train.y)

        tuning = val if (val is not None and len(val) > 0) else train
        self.snr_threshold = self._fit_snr_threshold(tuning)

        importances = dict(
            zip(self.feature_names, [round(float(v), 5) for v in self.model.feature_importances_])
        )
        self.metadata = {
            "sklearn_version": sklearn.__version__,
            "estimator": "RandomForestClassifier",
            "n_train_rows": int(len(train)),
            "n_val_rows": int(len(val)) if val is not None else 0,
            "n_train_scenes": int(np.unique(train.scene_index).size),
            "train_positive_fraction": round(float(np.mean(train.y)), 5),
            "feature_names": list(self.feature_names),
            "feature_importances": importances,
            "snr_threshold_dB": round(float(self.snr_threshold), 4),
            "random_state": self.random_state,
        }
        return self

    def _fit_snr_threshold(self, ds: GrowlerDataset) -> float:
        """Sweep the SNR cut and keep the one with the best F1 on this split."""
        snr = ds.X[:, self.feature_names.index("snr_db")]
        grid = np.linspace(float(np.percentile(snr, 1)), float(np.percentile(snr, 99)), 120)
        best_threshold, best_f1 = float(grid[0]), -1.0
        for threshold in grid:
            f1 = f1_score(ds.y, (snr >= threshold).astype(int), zero_division=0)
            if f1 > best_f1:
                best_threshold, best_f1 = float(threshold), float(f1)
        return best_threshold

    # --------------------------------------------------------------- prediction
    def predict(self, X: np.ndarray) -> np.ndarray:
        """1 for a real ice target, 0 for clutter."""
        if self.model is None:
            raise RuntimeError("GrowlerClassifier.predict called before fit or load.")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return self.model.predict(X).astype(int)

    def predict_proba(self, X: np.ndarray) -> np.ndarray:
        """
        Probability that the return is a real ice target, in [0, 1].

        Returns the positive-class column only, because that is the single confidence number the
        radar module attaches to a contact. The full two-column array is available on .model.
        """
        if self.model is None:
            raise RuntimeError("GrowlerClassifier.predict_proba called before fit or load.")
        X = np.asarray(X, dtype=np.float64)
        if X.ndim == 1:
            X = X.reshape(1, -1)
        return np.clip(self.model.predict_proba(X)[:, 1], 0.0, 1.0)

    # --------------------------------------------------------------- evaluation
    def evaluate(self, ds: GrowlerDataset) -> Dict[str, Any]:
        """Precision, recall, F1, ROC-AUC and the confusion matrix, against both baselines."""
        pred = self.predict(ds.X)
        proba = self.predict_proba(ds.X)
        cm = confusion_matrix(ds.y, pred, labels=[0, 1])
        tn, fp, fn, tp = (int(v) for v in cm.ravel())

        def block(y_pred: np.ndarray, scores: Optional[np.ndarray] = None) -> Dict[str, Any]:
            out = {
                "accuracy": round(float(accuracy_score(ds.y, y_pred)), 5),
                "precision": round(float(precision_score(ds.y, y_pred, zero_division=0)), 5),
                "recall": round(float(recall_score(ds.y, y_pred, zero_division=0)), 5),
                "f1": round(float(f1_score(ds.y, y_pred, zero_division=0)), 5),
            }
            if scores is not None and len(np.unique(ds.y)) > 1:
                out["roc_auc"] = round(float(roc_auc_score(ds.y, scores)), 5)
            return out

        snr = ds.X[:, self.feature_names.index("snr_db")]
        threshold = float(self.snr_threshold if self.snr_threshold is not None else 0.0)
        majority = int(round(float(np.mean(ds.y))))

        return {
            "n_samples": int(len(ds)),
            "n_scenes": int(np.unique(ds.scene_index).size),
            "positive_fraction": round(float(np.mean(ds.y)), 5),
            "model": block(pred, proba),
            "confusion_matrix": {
                "labels": ["clutter", "ice_target"],
                "true_negative": tn,
                "false_positive": fp,
                "false_negative": fn,
                "true_positive": tp,
            },
            "baselines": {
                "majority_class": block(np.full(len(ds), majority)),
                "snr_threshold": {
                    **block((snr >= threshold).astype(int), snr),
                    "threshold_dB": round(threshold, 4),
                },
            },
            "note": (
                "Radar returns are generated from a radar-equation model, not recorded from a "
                "real PPI. Simulated-environment metrics."
            ),
        }

    # ------------------------------------------------------------- persistence
    def save(self, path: str | Path) -> Path:
        if self.model is None:
            raise RuntimeError("GrowlerClassifier.save called before fit.")
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        joblib.dump(
            {
                "model_name": self.model_name,
                "model": self.model,
                "feature_names": list(self.feature_names),
                "hyperparameters": self.hyperparameters,
                "snr_threshold": self.snr_threshold,
                "metadata": self.metadata,
                "random_state": self.random_state,
            },
            path,
        )
        return path

    @classmethod
    def load(cls, path: str | Path) -> "GrowlerClassifier":
        payload = joblib.load(Path(path))
        obj = cls(random_state=int(payload.get("random_state", 26_059)))
        obj.model = payload["model"]
        obj.feature_names = tuple(payload.get("feature_names", ()))
        obj.hyperparameters = dict(payload.get("hyperparameters", {}))
        snr_threshold = payload.get("snr_threshold")
        obj.snr_threshold = float(snr_threshold) if snr_threshold is not None else None
        obj.metadata = dict(payload.get("metadata", {}))
        return obj
