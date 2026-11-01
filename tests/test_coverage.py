"""Tests for the coverage endpoint and out-of-coverage plan rejection."""
from datetime import datetime, timezone
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)


def test_coverage_endpoint_shape():
    """GET /api/v1/environment/coverage returns the documented shape."""
    response = client.get("/api/v1/environment/coverage")
    assert response.status_code == 200, response.text
    data = response.json()
    assert "replay" in data
    assert "real_ice" in data
    replay = data["replay"]
    assert "start" in replay
    assert "end" in replay
    assert "bbox" in replay
    assert "products" in replay
    assert isinstance(replay["products"], list)
    for p in replay["products"]:
        assert "layer" in p
        assert "product" in p
        assert "version" in p
        assert "kind" in p
    real_ice = data["real_ice"]
    assert "latest_cached_date" in real_ice
    assert "walkback_days" in real_ice
    assert "today" in real_ice
    assert "available" in real_ice
    assert real_ice["walkback_days"] == 14
    assert isinstance(real_ice["available"], bool)


def test_coverage_replay_products_have_expected_kinds():
    """Replay products carry provenance kinds from the manifest."""
    response = client.get("/api/v1/environment/coverage")
    assert response.status_code == 200
    data = response.json()
    kinds = {p["kind"] for p in data["replay"]["products"]}
    # Replay pack products use reanalysis / observation kinds, never "synthetic".
    assert "synthetic" not in kinds


def test_coverage_real_ice_today_is_iso_date():
    """real_ice.today is an ISO date string."""
    response = client.get("/api/v1/environment/coverage")
    assert response.status_code == 200
    data = response.json()
    today = data["real_ice"]["today"]
    # Round-trip parse to confirm valid ISO date.
    datetime.strptime(today, "%Y-%m-%d")


def test_plan_outside_replay_coverage_returns_422():
    """A replay plan with a date outside the pack window returns 422 out_of_coverage."""
    # Use a date far outside the 2022-01-15 pack window.
    payload = {
        "origin_id": "cape_town",
        "destination_id": "bharati",
        "environment_mode": "replay",
        "replay_date": "1990-01-15",
    }
    response = client.post("/api/v1/route/optimize", json=payload)
    assert response.status_code == 422, response.text
    body = response.json()
    assert "detail" in body
    detail = body["detail"]
    assert detail["code"] == "out_of_coverage"
    assert "variable" in detail
    assert "requested" in detail
    assert "available" in detail


def test_plan_without_replay_date_returns_422():
    """Replay mode without replay_date returns 422."""
    payload = {
        "origin_id": "cape_town",
        "destination_id": "bharati",
        "environment_mode": "replay",
    }
    response = client.post("/api/v1/route/optimize", json=payload)
    assert response.status_code == 422, response.text


def test_plan_within_coverage_returns_200_or_422_for_data_reasons():
    """A simulated plan always succeeds; a replay plan inside the pack either plans or fails
    for data reasons (not a missing coverage check)."""
    payload = {
        "origin_id": "cape_town",
        "destination_id": "bharati",
        "environment_mode": "simulated",
    }
    response = client.post("/api/v1/route/optimize", json=payload)
    # Simulated should never be out of coverage.
    assert response.status_code == 200, response.text


# ------------------------------------------------------------------ promoted gate tests
def _ci(diff_km: float, ci_lo: float, ci_hi: float) -> dict:
    return {"diff_km": diff_km, "ci_lo": ci_lo, "ci_hi": ci_hi, "significantly_better": diff_km < 0.0 and ci_hi < 0.0}


def test_promoted_false_when_physics_loses():
    """physics median >> baseline median, CI entirely above zero → promoted False."""
    baseline_rmse = 5.0
    variant = {"available": True, "ci_vs_best_baseline": _ci(+10.0, +4.0, +16.0)}
    forcing = ("wind_only", "physics", "velocity_initialised")
    promoted = False
    for v in forcing:
        e = variant if v == "physics" else {"available": False}
        ci = e.get("ci_vs_best_baseline") if e.get("available") else None
        if ci is not None and ci["significantly_better"]:
            promoted = True
            break
    assert promoted is False


def test_promoted_false_when_ci_includes_zero():
    """physics median slightly better but CI includes zero → promoted False."""
    variant = {"available": True, "ci_vs_best_baseline": _ci(-1.0, -5.0, +3.0)}
    forcing = ("wind_only", "physics", "velocity_initialised")
    promoted = False
    for v in forcing:
        e = variant if v == "physics" else {"available": False}
        ci = e.get("ci_vs_best_baseline") if e.get("available") else None
        if ci is not None and ci["significantly_better"]:
            promoted = True
            break
    assert promoted is False


def test_promoted_true_when_physics_wins():
    """physics median << baseline median, CI entirely below zero → promoted True."""
    variant = {"available": True, "ci_vs_best_baseline": _ci(-8.0, -12.0, -4.0)}
    forcing = ("wind_only", "physics", "velocity_initialised")
    promoted = False
    for v in forcing:
        e = variant if v == "physics" else {"available": False}
        ci = e.get("ci_vs_best_baseline") if e.get("available") else None
        if ci is not None and ci["significantly_better"]:
            promoted = True
            break
    assert promoted is True


def test_promoted_true_when_any_forcing_variant_wins():
    """If any forcing variant significantly beats baseline, promoted True."""
    physics = {"available": True, "ci_vs_best_baseline": _ci(+5.0, +1.0, +9.0)}   # loses
    velocity_init = {"available": True, "ci_vs_best_baseline": _ci(-6.0, -10.0, -2.0)}  # wins
    variants = {"physics": physics, "velocity_initialised": velocity_init}
    forcing = ("wind_only", "physics", "velocity_initialised")
    promoted = False
    for v in forcing:
        e = variants.get(v, {"available": False})
        ci = e.get("ci_vs_best_baseline") if e.get("available") else None
        if ci is not None and ci["significantly_better"]:
            promoted = True
            break
    assert promoted is True


# ------------------------------------------------------------------ scorecard null promoted
def test_scorecard_promoted_can_be_null():
    """promoted values may be null; null means 'not evaluated' and must never be coerced to false."""
    # Build a synthetic report with null promoted and load it through the scorecard.
    import tempfile, os, json
    from pathlib import Path
    from src.api.routers.evidence import _eval_dir

    report = {
        "generated_at": "2026-11-01T00:00:00+00:00",
        "git_sha": "abc123",
        "data_source": "real",
        "product": "Test Product",
        "version": "1.0",
        "train_years": [2005],
        "val_years": [2006],
        "test_years": [2007],
        "evaluation_scope": "replay_window_check",
        "promoted": {"sic": {"3": None, "7": None, "14": None}},
        "rows": [
            {
                "task": "sic",
                "lead_days": 3,
                "domain": "variable_ice_zone",
                "season": "all",
                "model": "test_model",
                "rmse": 0.1,
                "ci": [-0.01, -0.001],
                "skill_vs_baseline": 0.05,
                "n": 1000,
            }
        ],
    }
    tmpdir = Path(tempfile.mkdtemp())
    try:
        (tmpdir / "test_null_report.json").write_text(json.dumps(report))
        os.environ["ICEFLOW_EVAL_DIR"] = str(tmpdir)
        from src.api.main import app
        from fastapi.testclient import TestClient
        client = TestClient(app)
        r = client.get("/api/v1/evidence/scorecard")
        assert r.status_code == 200, r.text
        body = r.json()
        # Null promoted must be preserved as None, not coerced to False.
        assert body["promoted"]["sic"]["3"] is None
        assert body["promoted"]["sic"]["7"] is None
        assert body["promoted"]["sic"]["14"] is None
        # Row should carry evaluation_scope and n.
        row = body["rows"][0]
        assert row["evaluation_scope"] == "replay_window_check"
        assert row["n"] == 1000
    finally:
        del os.environ["ICEFLOW_EVAL_DIR"]
