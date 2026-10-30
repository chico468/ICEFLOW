"""Stage A endpoints: observed icebergs, regional geography, and the environment grid the flow layers read.

Needs the web stack (fastapi, httpx). Run on a machine where `pip install -r requirements.txt` has been done.
"""
from fastapi.testclient import TestClient

from src.api.main import app

client = TestClient(app)


def test_observed_icebergs_are_labelled_observed_dated_and_kept_out_of_routing():
    r = client.get("/api/v1/icebergs/observed")
    assert r.status_code == 200
    body = r.json()
    assert body["available"] is True and body["kind"] == "observed"
    assert body["observed_date"] == "2026-08-20"
    assert body["used_for_routing"] is False
    assert isinstance(body["stale"], bool) and body["age_days"] >= 0
    assert body["count"] == len(body["icebergs"]) == 33


def test_observed_route_does_not_shadow_the_drift_route():
    # /icebergs/{berg_id}/drift must still resolve for a catalogue berg.
    # The default /icebergs path is now observed; catalogue bergs are behind mode="simulated".
    first = client.get("/api/v1/icebergs?mode=simulated").json()["icebergs"][0]["berg_id"]
    assert client.get(f"/api/v1/icebergs/{first}/drift", params={"forecast_hours": 24}).status_code == 200


def test_regional_endpoint_is_honest_whether_or_not_the_file_is_built():
    r = client.get("/api/v1/geo/regional")
    assert r.status_code == 200
    body = r.json()
    assert body["region"]["lat_min"] == -75.0
    if body["available"]:
        assert "Natural Earth" in body["attribution"] and len(body["land"]) > 0
    else:
        assert body["land"] == [] and any("build_regional_context" in s for s in body["setup"])


def test_env_field_carries_the_vectors_the_particles_need():
    r = client.get(
        "/api/v1/env/field",
        params={"lat_min": -60, "lat_max": -40, "lon_min": 20, "lon_max": 40, "resolution_deg": 2},
    )
    assert r.status_code == 200
    f = r.json()
    rows, cols = len(f["lats"]), len(f["lons"])
    for key in ("u10", "v10", "current_u", "current_v", "sig_wave_height_m"):
        assert len(f[key]) == rows and len(f[key][0]) == cols, key
    assert f.get("is_synthetic") is True, "the flow layers label themselves simulated from this flag"
