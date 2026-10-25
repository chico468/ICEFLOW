from pathlib import Path

from src.ml import registry


def test_ml_status_without_artefacts(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    status = registry.ml_status()
    assert "models" in status
    for key in ("sic_forecaster", "drift_residual", "growler_classifier"):
        entry = status["models"][key]
        assert entry["status"] == "not trained"
        assert entry["trained_on"] == "synthetic"
        assert entry["operational_skill_validated"] is False
        assert entry["used_in_routing"] is False
        assert "beats_best_baseline" in entry
        assert "metrics_mode" in entry


def test_ml_status_with_current_metrics(tmp_path, monkeypatch):
    registry.reset_cache()
    # Use repo models dir
    from src.ml import registry as reg

    status = reg.ml_status()
    for key in ("sic_forecaster", "drift_residual", "growler_classifier"):
        entry = status["models"][key]
        assert entry["status"] in ("demo_synthetic", "not trained")
        assert entry["trained_on"] == "synthetic"
        assert entry["operational_skill_validated"] is False
        assert entry["used_in_routing"] is False
        assert "caveat" in entry


def test_beats_best_baseline_false_for_current_metrics():
    from src.ml import registry as reg

    status = reg.ml_status()
    # Current metrics show negative/worse results
    for key in ("sic_forecaster", "drift_residual", "growler_classifier"):
        assert status["models"][key]["beats_best_baseline"] is False


def test_ml_status_missing_metrics_no_exception(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    # Ensure no metrics file
    metrics = tmp_path / "metrics.json"
    if metrics.exists():
        metrics.unlink()
    status = registry.ml_status()
    assert status["metrics_file_present"] is False
    assert "models" in status
