"""Tests for the observed icebergs API (BE-3 / R2 Part 4).

No network is used: the BYU fixture zip and NIC fixture CSV live under
tests/fixtures/observed_bergs/.
"""

from __future__ import annotations

import zipfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.main import app
from src.ml.iceberg_dataset import IcebergTrack, load_database, nearest_at_or_before

client = TestClient(app)

FIXTURE_DIR = Path("tests/fixtures/observed_bergs")


def _load_fixture_tracks() -> list[IcebergTrack]:
    return load_database(FIXTURE_DIR / "byu_small.zip")


# ---------------------------------------------------------------------------
# nearest_at_or_before: exact YYYYDDD matching, no approximation
# ---------------------------------------------------------------------------


def test_nearest_at_or_before_exact_match():
    tracks = _load_fixture_tracks()
    ids = {t.berg_id for t in tracks}
    assert ids == {"B01", "B02"}

    # 2021-01-07: B01 has an exact observation; B02's last on-or-before is 2021-01-05.
    out = nearest_at_or_before(tracks, date(2021, 1, 7))
    assert set(out) == {"B01", "B02"}
    assert out["B01"]["last_obs"] == date(2021, 1, 7)
    assert out["B02"]["last_obs"] == date(2021, 1, 5)
    assert out["B01"]["latitude"] == pytest.approx(-65.0 - 6 * 0.8)
    assert out["B01"]["longitude"] == pytest.approx(-50.0 - 6 * 1.2)


def test_nearest_at_or_before_first_day():
    tracks = _load_fixture_tracks()
    out = nearest_at_or_before(tracks, date(2021, 1, 1))
    assert out["B01"]["last_obs"] == date(2021, 1, 1)
    assert out["B02"]["last_obs"] == date(2021, 1, 1)


def test_nearest_at_or_before_omits_when_none_on_or_before():
    """Before the first observation the berg is omitted - never invented."""
    tracks = _load_fixture_tracks()
    out = nearest_at_or_before(tracks, date(2020, 12, 31))
    assert out == {}


def test_nearest_at_or_before_sizes_are_nautical_miles():
    tracks = _load_fixture_tracks()
    out = nearest_at_or_before(tracks, date(2021, 1, 3))
    # B01 on 2021-01-03: size_1 = 20 + 2 = 22, size_2 = 15 + 2 = 17
    assert out["B01"]["size_major_nm"] == 22.0
    assert out["B01"]["size_minor_nm"] == 17.0


# ---------------------------------------------------------------------------
# API: observed mode (default) returns observed bergs
# ---------------------------------------------------------------------------


def test_api_observed_mode_default():
    r = client.get("/api/v1/icebergs")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "observed"
    assert body["provenance"] == "observed"
    assert body["count"] == len(body["icebergs"]) == 33
    for b in body["icebergs"]:
        assert b["provenance"] == "observed"
        assert "last_obs" in b and b["last_obs"]
        assert "age_days" in b and isinstance(b["age_days"], int)
        assert "length_nm" in b and "width_nm" in b
        # No forecast unless lead_hours requested.
        assert "forecast_latitude" not in b


def test_api_observed_berg_has_expected_shape():
    r = client.get("/api/v1/icebergs")
    body = r.json()
    a76c = next(b for b in body["icebergs"] if b["id"] == "A76C")
    assert a76c["last_obs"] == "2026-08-20"
    assert a76c["latitude"] == pytest.approx(-52.99)
    assert a76c["longitude"] == pytest.approx(-30.2)
    assert a76c["length_nm"] == pytest.approx(16.0)
    assert a76c["width_nm"] == pytest.approx(7.0)
    assert a76c["age_days"] >= 0


# ---------------------------------------------------------------------------
# API: observed mode with `at` uses BYU nearest-at-or-before-t0
# ---------------------------------------------------------------------------


def test_api_observed_at_uses_byu_nearest_at_or_before(monkeypatch):
    """`at` selects the nearest BYU observation at or before t0 (exact, no approximation)."""
    import src.api.routers.navigation as nav

    monkeypatch.setattr(nav, "load_database", lambda: _load_fixture_tracks())

    # 2021-01-08: B01 has an exact obs on 01-08; B02's last on-or-before is 01-05.
    r = client.get("/api/v1/icebergs?mode=observed&at=2021-01-08T00:00:00Z")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "observed"
    by_id = {b["berg_id"]: b for b in body["icebergs"]}

    assert "B01" in by_id and "B02" in by_id
    assert by_id["B01"]["last_obs"] == "2021-01-08"
    assert by_id["B02"]["last_obs"] == "2021-01-05"  # fell back to the last on-or-before obs
    assert by_id["B01"]["age_days"] == 0
    assert by_id["B02"]["age_days"] == 3


def test_api_observed_at_never_invents_a_berg(monkeypatch):
    """BYU bergs with no observation on or before ``at`` are never fabricated."""
    import src.api.routers.navigation as nav

    monkeypatch.setattr(nav, "load_database", lambda: _load_fixture_tracks())

    r = client.get("/api/v1/icebergs?mode=observed&at=2020-12-31T00:00:00Z")
    assert r.status_code == 200
    body = r.json()
    by_id = {b["berg_id"]: b for b in body["icebergs"]}
    # B01 and B02 have no observation on or before 2020-12-31, so they must not appear.
    assert "B01" not in by_id
    assert "B02" not in by_id
    # NIC snapshot bergs still appear (they are real observed bergs).
    assert any(b["id"] == "A76C" for b in body["icebergs"])


# ---------------------------------------------------------------------------
# API: simulated mode preserves the catalogue (no seeds in default path)
# ---------------------------------------------------------------------------


def test_api_simulated_mode_returns_catalogue_seeds():
    r = client.get("/api/v1/icebergs?mode=simulated")
    assert r.status_code == 200
    body = r.json()
    assert body["mode"] == "simulated"
    assert body["count"] == len(body["icebergs"]) == 7
    first = body["icebergs"][0]
    assert "berg_id" in first and first["berg_id"]
    # Simulated entries are not labelled observed.
    assert first.get("provenance") != "observed"


def test_api_drift_route_still_resolves_for_catalogue_berg():
    first = client.get("/api/v1/icebergs?mode=simulated").json()["icebergs"][0]["berg_id"]
    r = client.get(f"/api/v1/icebergs/{first}/drift", params={"forecast_hours": 24})
    assert r.status_code == 200


def test_api_observed_lead_hours_forecast_is_real_forecast(monkeypatch):
    import src.api.routers.navigation as nav

    monkeypatch.setattr(nav, "load_database", lambda: _load_fixture_tracks())

    r = client.get("/api/v1/icebergs?mode=observed&at=2021-01-05T00:00:00Z&lead_hours=24")
    assert r.status_code == 200
    body = r.json()
    assert body["icebergs"], "expected at least one observed berg"
    for b in body["icebergs"]:
        assert b.get("kind") == "real_forecast"
        assert "forecast_latitude" in b and "forecast_longitude" in b
        assert b.get("forecast_lead_hours") == 24
        assert "radii_nm" in b
