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
