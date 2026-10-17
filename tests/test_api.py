"""Unit tests for FastAPI endpoints."""
from fastapi.testclient import TestClient
from src.api.main import app

client = TestClient(app)

def test_api_root():
    response = client.get("/")
    assert response.status_code == 200
    assert response.json()["problem_statement_id"] == "26059"

def test_api_polaris():
    payload = {
        "ice_class": "PC5",
        "components": [
            {"ice_type": "Thin_First_Year_Stage_1", "concentration_tenths": 5}
        ]
    }
    response = client.post("/api/v1/risk/polaris", json=payload)
    assert response.status_code == 200
    data = response.json()
    assert "rio" in data
    assert data["is_operation_permitted"] is True

def test_api_polar_grid():
    response = client.get("/api/v1/visualize/antarctica-grid")
    assert response.status_code == 200
    data = response.json()
    assert data["type"] == "FeatureCollection"
