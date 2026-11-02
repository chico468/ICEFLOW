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
    report = {
        "data_source": "real",
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "generated_at": "2026-01-01T00:00:00+00:00",
        "train_years": [2005],
        "test_years": [2024],
    }
    import json
    with open(eval_dir / "real_sic_ml_report.json", "w") as f:
        json.dump(report, f)
    status = registry.ml_status()
    assert status.get("real_data_report") is not None
    assert status.get("real_data_report").get("path") is not None
