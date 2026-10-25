from pathlib import Path
from src.ml import registry


def test_ml_status_real_data_report_null_when_missing(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    status = registry.ml_status()
    assert status.get("real_data_report") is None


def test_ml_status_real_data_report_present(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir(parents=True)
    report = {"data_source": "real", "date": "2026-01-01"}
    import json
    with open(eval_dir / "real_sic_report.json", "w") as f:
        json.dump(report, f)
    status = registry.ml_status()
    assert status.get("real_data_report") is not None
    assert status.get("real_data_report").get("path") is not None
