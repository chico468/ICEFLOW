import json
from pathlib import Path
from src.ml import registry


def test_fixture_report_not_reported(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir(parents=True)
    report = {"data_source": "fixture", "product": "NOAA/NSIDC G02202 Version 6", "version": "v06r00"}
    with open(eval_dir / "real_sic_report.json", "w") as f:
        json.dump(report, f)
    status = registry.ml_status()
    assert status.get("real_data_report") is None


def test_real_report_only_if_metadata_says_real(tmp_path, monkeypatch):
    registry.reset_cache()
    monkeypatch.setattr(registry, "MODELS_DIR", tmp_path)
    eval_dir = tmp_path / "eval"
    eval_dir.mkdir(parents=True)
    report = {"data_source": "real", "product": "NOAA/NSIDC CDR G02202 Version 6", "version": "v06r00", "date_range": ["1978-10-25", "2024-12-31"]}
    with open(eval_dir / "real_sic_report.json", "w") as f:
        json.dump(report, f)
    status = registry.ml_status()
    assert status.get("real_data_report") is not None
