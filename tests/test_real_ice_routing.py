"""Tests for BE-5 real-ice routing and the shared voyage-plan contract.

No network access is required: all tests use fixture NSIDC NetCDF files written to a
temporary cache directory.
"""
from __future__ import annotations

import json
import numpy as np
import pytest
import xarray as xr
from datetime import date
from fastapi.testclient import TestClient
from pyproj import Transformer

from src.api.main import app
from src.core.polaris_risk import IceClass
from src.core.route_optimizer import PolarRouteOptimizer, OptimizationSummary
from src.core.voyage import create_voyage
from src.core.lindqvist_model import VesselParameters
from src.data.nsidc_sea_ice import read_nsidc_file
from src.data.observed_sea_ice import ObservedIceField, get_observed_observation


client = TestClient(app)


def write_nsidc_file(path, values_2d, observation_date):
    """Write a minimal but valid NSIDC G02202 V6 NetCDF grid to *path*."""
    x0, y0 = Transformer.from_crs(
        "EPSG:4326", "EPSG:3412", always_xy=True
    ).transform(0.0, -70.0)
    ny, nx = values_2d.shape
    ds = xr.Dataset(
        {"cdr_seaice_conc": (("time", "y", "x"), values_2d[np.newaxis])},
        coords={
            "time": np.array([np.datetime64(observation_date, "D")]),
            "y": y0 + np.arange(ny) * 25_000.0,
            "x": x0 + np.arange(nx) * 25_000.0,
        },
    )
    ds["cdr_seaice_conc"].attrs["units"] = "1"
    ds["cdr_seaice_conc"].attrs["grid_mapping"] = "crs"
    ds["x"].attrs["units"] = "meters"
    ds["y"].attrs["units"] = "meters"
    ds["crs"] = xr.DataArray(0)
    ds["crs"].attrs.update({
        "grid_mapping_name": "polar_stereographic",
        "latitude_of_projection_origin": -90.0,
        "straight_vertical_longitude_from_pole": 0.0,
        "standard_parallel": -70.0,
        "false_easting": 0.0,
        "false_northing": 0.0,
        "semi_major_axis": 6378273.0,
        "inverse_flattening": 298.279411123064,
    })
    ds.to_netcdf(path, engine="netcdf4")
    ds.close()


def make_fixture_ice_grid(tmp_path, observation_date_str="2024-01-15", ny=20, nx=40):
    """Create a fixture NSIDC file with a gradient of concentration values."""
    values = np.linspace(0.05, 0.8, ny * nx).reshape(ny, nx)
    fname = tmp_path / f"sic_pss25_{observation_date_str.replace('-', '')}_F17_v06r00.nc"
    write_nsidc_file(fname, values, observation_date_str)
    return fname


# ---------------------------------------------------------------------------
# ObservedIceField tests
# ---------------------------------------------------------------------------

def test_observed_ice_field_samples_concentration(tmp_path):
    fname = make_fixture_ice_grid(tmp_path, ny=4, nx=4)
    obs = read_nsidc_file(fname, retrieved_from_cache=True)
    field = ObservedIceField(obs)

    lat = np.array([-70.0])
    lon = np.array([0.0])
    conc = field.sample(lat, lon)
    assert 0.0 <= conc[0] <= 1.0
    assert np.isfinite(conc[0])


def test_observed_ice_field_returns_nan_filled_zero(tmp_path):
    fname = make_fixture_ice_grid(tmp_path, ny=4, nx=4)
    obs = read_nsidc_file(fname, retrieved_from_cache=True)
    field = ObservedIceField(obs)

    # Point far outside the Antarctic grid coverage should return 0 (fill)
    lat = np.array([0.0])
    lon = np.array([0.0])
    conc = field.sample(lat, lon)
    assert conc[0] == 0.0


def test_observed_ice_field_valid_date_and_source(tmp_path):
    fname = make_fixture_ice_grid(tmp_path, ny=3, nx=3)
    obs = read_nsidc_file(fname, retrieved_from_cache=True)
    field = ObservedIceField(obs)
    assert field.valid_date == date(2024, 1, 15)
    assert "NSIDC" in field.source


# ---------------------------------------------------------------------------
# get_observed_observation tests
# ---------------------------------------------------------------------------

def test_get_observed_observation_for_date(tmp_path, monkeypatch):
    fname = make_fixture_ice_grid(tmp_path, ny=4, nx=4)
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    from src.data.observed_sea_ice import get_observed_observation
    obs = get_observed_observation(date(2024, 1, 15))
    assert obs.observation_date == date(2024, 1, 15)


def test_get_observed_observation_missing_raises(tmp_path, monkeypatch):
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    from src.data.observed_sea_ice import get_observed_observation
    from src.data.nsidc_sea_ice import NSIDCUnavailableError
    with pytest.raises(NSIDCUnavailableError):
        get_observed_observation(date(2024, 1, 15))


# ---------------------------------------------------------------------------
# Route optimizer with environment_mode tests
# ---------------------------------------------------------------------------

def test_optimize_route_simulated_has_provenance_and_arrival_iso():
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    summary = optimizer.optimize_route(
        -58.0, 70.0, -69.0, 76.0,
        departure_iso="2024-01-15T00:00:00+00:00",
    )
    assert summary.environment_mode == "simulated"
    assert summary.is_synthetic_environment is True
    assert summary.departure_iso == "2024-01-15T00:00:00+00:00"
    assert summary.arrival_iso is not None
    assert len(summary.waypoint_etas) == summary.waypoints_count
    assert len(summary.provenance) > 0
    assert all(p.kind == "simulated" for p in summary.provenance if p.layer == "sea_ice_field")
    # arrival = departure + total_transit_hours
    from datetime import datetime, timedelta
    dep = datetime.fromisoformat("2024-01-15T00:00:00+00:00")
    expected_arrival = (dep + timedelta(hours=summary.total_transit_hours)).isoformat(timespec="seconds")
    assert summary.arrival_iso == expected_arrival
    # waypoint_etas: first waypoint at departure, last at arrival
    assert summary.waypoint_etas[0].index == 0
    assert summary.waypoint_etas[-1].index == summary.waypoints_count - 1


def test_optimize_route_without_departure_iso_has_no_eta():
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    summary = optimizer.optimize_route(-58.0, 70.0, -69.0, 76.0)
    assert summary.arrival_iso is None
    assert summary.waypoint_etas == []


def test_optimize_route_real_ice_no_observation_raises(tmp_path, monkeypatch):
    """real_ice with no cached observation raises NSIDCUnavailableError, never silently falls back."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    from src.data.nsidc_sea_ice import NSIDCUnavailableError
    with pytest.raises(NSIDCUnavailableError):
        PolarRouteOptimizer(
            ice_class=IceClass.PC5,
            environment_mode="real_ice",
        )


def test_replay_missing_date_raises(tmp_path, monkeypatch):
    """replay without a replay_date is a hard error, not a synthetic fallback."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    from src.data.nsidc_sea_ice import NSIDCUnavailableError
    with pytest.raises(NSIDCUnavailableError):
        PolarRouteOptimizer(ice_class=IceClass.PC5, environment_mode="replay")


def test_replay_date_not_in_cache_raises(tmp_path, monkeypatch):
    """replay with a replay_date that has no cached observation is a hard error."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    from src.data.nsidc_sea_ice import NSIDCUnavailableError
    with pytest.raises(NSIDCUnavailableError):
        PolarRouteOptimizer(
            ice_class=IceClass.PC5,
            environment_mode="replay",
            replay_date="2024-01-15",
        )


def test_optimize_route_replay_uses_observed_ice(tmp_path, monkeypatch):
    """replay mode with a cached NSIDC file for the date uses observed concentration."""
    make_fixture_ice_grid(tmp_path, ny=40, nx=80, observation_date_str="2024-01-15")
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))

    optimizer = PolarRouteOptimizer(
        ice_class=IceClass.PC5,
        environment_mode="replay",
        replay_date="2024-01-15",
    )
    assert optimizer._observed_ice is not None
    assert optimizer.is_synthetic is False

    summary = optimizer.optimize_route(
        -58.0, 70.0, -69.0, 76.0,
        departure_iso="2024-01-15T00:00:00+00:00",
    )
    assert summary.environment_mode == "replay"
    assert summary.is_synthetic_environment is False
    assert summary.arrival_iso is not None
    assert len(summary.provenance) > 0
    # At least one provenance entry should be "observed"
    kinds = [p.kind for p in summary.provenance]
    assert "observed" in kinds
    # Wind/waves should still be labelled simulated
    atm = [p for p in summary.provenance if p.layer == "atmosphere_ocean"]
    assert len(atm) == 1 and atm[0].kind == "simulated"


def test_optimize_route_replay_cape_town_to_bharati_within_60s(tmp_path, monkeypatch):
    """BE-5 acceptance: Cape Town to Bharati with replay_date returns arrival_iso in <60s."""
    make_fixture_ice_grid(tmp_path, ny=40, nx=80, observation_date_str="2024-01-15")
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))

    from src.data.stations import resolve_endpoint
    origin = resolve_endpoint("cape_town")
    dest = resolve_endpoint("bharati")
    assert origin is not None and dest is not None

    optimizer = PolarRouteOptimizer(
        ice_class=IceClass.PC5,
        environment_mode="replay",
        replay_date="2024-01-15",
    )
    import time
    start = time.perf_counter()
    summary = optimizer.optimize_route(
        origin[0], origin[1], dest[0], dest[1],
        departure_iso="2024-01-15T00:00:00+00:00",
    )
    elapsed = time.perf_counter() - start
    assert elapsed < 60.0, f"route took {elapsed:.1f}s, expected <60s"
    assert summary.arrival_iso is not None
    assert len(summary.provenance) > 0


# ---------------------------------------------------------------------------
# Voyage creation with environment_mode tests
# ---------------------------------------------------------------------------

def test_create_voyage_simulated_has_provenance():
    from src.data.stations import resolve_endpoint
    origin = resolve_endpoint("cape_town")
    dest = resolve_endpoint("bharati")
    vessel = VesselParameters()

    engine = create_voyage(
        origin=origin,
        destination=dest,
        vessel=vessel,
        ice_class=IceClass.PC5,
        departure_time_hours=0.0,
    )
    state = engine.state
    assert state.environment_mode == "simulated"
    assert state.is_synthetic_environment is True
    assert state.arrival_iso is not None
    assert len(state.provenance) > 0
    assert len(state.waypoint_etas) > 0


def test_create_voyage_replay_with_observed_ice(tmp_path, monkeypatch):
    make_fixture_ice_grid(tmp_path, ny=40, nx=80, observation_date_str="2024-01-15")
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))

    from src.data.stations import resolve_endpoint
    origin = resolve_endpoint("cape_town")
    dest = resolve_endpoint("bharati")
    vessel = VesselParameters()

    engine = create_voyage(
        origin=origin,
        destination=dest,
        vessel=vessel,
        ice_class=IceClass.PC5,
        environment_mode="replay",
        replay_date="2024-01-15",
    )
    state = engine.state
    assert state.environment_mode == "replay"
    # When observed ice loads successfully, is_synthetic should be False
    assert state.provenance is not None
    assert len(state.provenance) > 0


# ---------------------------------------------------------------------------
# Scorecard endpoint tests
# ---------------------------------------------------------------------------

def test_scorecard_returns_real_data():
    r = client.get("/api/v1/evidence/scorecard")
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "real"
    assert body["product"] is not None
    assert body["version"] is not None
    assert isinstance(body["train_years"], list) and len(body["train_years"]) > 0
    assert isinstance(body["test_years"], list) and len(body["test_years"]) > 0
    assert isinstance(body["rows"], list) and len(body["rows"]) > 0
    row = body["rows"][0]
    assert row["task"] == "sic"
    assert isinstance(row["lead_days"], int)
    assert isinstance(row["rmse"], (int, float))
    assert len(row["ci"]) == 2
    assert row["skill_vs_baseline"] is not None
    assert row["n"] > 0
    assert isinstance(body["promoted"], dict)
    assert "sic" in body["promoted"]
    assert isinstance(body["coverage"], dict)
    assert isinstance(body["caveats"], list) and len(body["caveats"]) > 0


def test_scorecard_empty_when_no_real_reports(tmp_path, monkeypatch):
    monkeypatch.setenv("ICEFLOW_EVAL_DIR", str(tmp_path))
    r = client.get("/api/v1/evidence/scorecard")
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "none"
    assert body["rows"] == []
    assert body["promoted"] == {"sic": {}, "iceberg": {}}
    assert len(body["caveats"]) == 1


def test_scorecard_with_fixture_report(tmp_path, monkeypatch):
    monkeypatch.setenv("ICEFLOW_EVAL_DIR", str(tmp_path))
    fixture = {
        "data_source": "real",
        "product": "NOAA/NSIDC CDR G02202 Version 6",
        "version": "v06r00",
        "train_years": [2005, 2006],
        "test_years": [2024],
        "leads": [3, 7, 14],
        "disclaimer": "Baselines only.",
        "sensor_caveat": "Sensor changes in 2025.",
        "results": [
            {"lead": 3, "domain": "variable_ice_zone_5_95", "season": "all",
             "sector": "Weddell Sea", "baseline": "damped",
             "rmse": 0.08, "rmse_ci": [0.07, 0.09], "n": 1000},
            {"lead": 3, "domain": "variable_ice_zone_5_95", "season": "all",
             "sector": "Weddell Sea", "baseline": "persistence",
             "rmse": 0.10, "rmse_ci": [0.09, 0.11], "n": 1000},
        ],
    }
    (tmp_path / "fixture_report.json").write_text(json.dumps(fixture))

    r = client.get("/api/v1/evidence/scorecard")
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "real"
    assert len(body["rows"]) == 1
    assert body["rows"][0]["model"] == "damped_anomaly_persistence"
    assert body["rows"][0]["skill_vs_baseline"] == round(1.0 - 0.08 / 0.10, 4)
    assert body["promoted"]["sic"]["3"]["promoted"] is True
    assert body["promoted"]["sic"]["3"]["model"] == "gbm_residual"
    assert body["coverage"]["3"]["target"] == 0.9


def test_scorecard_skips_non_real_reports(tmp_path, monkeypatch):
    """Reports whose data_source != "real" (e.g. simulated forcing) are skipped entirely."""
    monkeypatch.setenv("ICEFLOW_EVAL_DIR", str(tmp_path))
    non_real = {
        "data_source": "simulated_forcing",
        "product": "synthetic sanity run",
        "leads": [1, 3, 7],
        "results": [
            {"lead": 1, "domain": "x", "season": "all", "sector": "s",
             "baseline": "damped", "rmse": 0.05, "rmse_ci": [0.04, 0.06], "n": 10},
        ],
    }
    (tmp_path / "simulated_report.json").write_text(json.dumps(non_real))

    r = client.get("/api/v1/evidence/scorecard")
    assert r.status_code == 200
    body = r.json()
    assert body["data_source"] == "none"
    assert body["rows"] == []
    assert body["promoted"] == {"sic": {}, "iceberg": {}}


# ---------------------------------------------------------------------------
# API endpoint contract tests
# ---------------------------------------------------------------------------

def test_route_optimize_response_includes_contract_fields():
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    summary = optimizer.optimize_route(
        -58.0, 70.0, -69.0, 76.0,
        departure_iso="2024-01-15T00:00:00+00:00",
    )
    data = summary.model_dump()
    assert "departure_iso" in data
    assert "arrival_iso" in data
    assert "waypoint_etas" in data
    assert "environment_mode" in data
    assert "provenance" in data


def test_route_optimize_api_returns_contract_fields():
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "ice_class": "PC5",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["environment_mode"] == "simulated"
    assert body["departure_iso"] == "2024-01-15T00:00:00+00:00"
    assert body["arrival_iso"] is not None
    assert len(body["waypoint_etas"]) == body["waypoints_count"]
    assert len(body["provenance"]) > 0


def test_route_optimize_api_accepts_replay_request(tmp_path, monkeypatch):
    make_fixture_ice_grid(tmp_path, ny=40, nx=80, observation_date_str="2024-01-15")
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "ice_class": "PC5",
            "environment_mode": "replay",
            "replay_date": "2024-01-15",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["environment_mode"] == "replay"
    assert body["is_synthetic_environment"] is False
    assert any(p["kind"] == "observed" for p in body["provenance"])


def test_voyage_api_accepts_environment_mode():
    r = client.post(
        "/api/v1/voyage",
        json={
            "origin_id": "cape_town",
            "destination_id": "bharati",
            "vessel_key": "vasiliy_golovnin",
            "environment_mode": "simulated",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert r.status_code == 200
    body = r.json()
    assert body["environment_mode"] == "simulated"
    assert body["is_synthetic_environment"] is True
    assert body["arrival_iso"] is not None
    assert len(body["waypoint_etas"]) > 0
    assert len(body["provenance"]) > 0
    assert body["departure_iso"] == "2024-01-15T00:00:00+00:00"
    voyage_id = body["voyage_id"]
    assert voyage_id
    client.delete(f"/api/v1/voyage/{voyage_id}")


def test_route_optimize_rejects_invalid_environment_mode():
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "environment_mode": "bogus",
        },
    )
    assert r.status_code == 422


def test_route_optimize_rejects_invalid_replay_date():
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "environment_mode": "replay",
            "replay_date": "not-a-date",
        },
    )
    assert r.status_code == 422


def test_route_optimize_replay_missing_date_returns_4xx(tmp_path, monkeypatch):
    """replay without a replay_date returns a clear 4xx error, never a synthetic plan."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "ice_class": "PC5",
            "environment_mode": "replay",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert 400 <= r.status_code < 500
    detail = r.json()["detail"]
    if isinstance(detail, list):
        text = " ".join(json.dumps(d, default=str) for d in detail)
    else:
        text = str(detail)
    assert "replay_date" in text.lower()


def test_route_optimize_replay_date_not_in_cache_returns_4xx(tmp_path, monkeypatch):
    """replay with a replay_date that has no cached observation returns a 4xx error."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "ice_class": "PC5",
            "environment_mode": "replay",
            "replay_date": "2024-01-15",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert 400 <= r.status_code < 500


def test_route_optimize_real_ice_no_observation_raises_4xx(tmp_path, monkeypatch):
    """real_ice with no observation returns a 4xx error, never a silent synthetic plan."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/route/optimize",
        json={
            "start_lat": -58.0,
            "start_lon": 70.0,
            "dest_lat": -69.0,
            "dest_lon": 76.0,
            "ice_class": "PC5",
            "environment_mode": "real_ice",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert 400 <= r.status_code < 500


def test_create_voyage_replay_missing_date_returns_4xx(tmp_path, monkeypatch):
    """The voyage endpoint also surfaces a missing replay date as 4xx."""
    monkeypatch.setenv("ICEFLOW_NSIDC_CACHE_DIR", str(tmp_path))
    r = client.post(
        "/api/v1/voyage",
        json={
            "origin_id": "cape_town",
            "destination_id": "bharati",
            "vessel_key": "vasiliy_golovnin",
            "ice_class": "PC5",
            "environment_mode": "replay",
            "departure_iso": "2024-01-15T00:00:00+00:00",
        },
    )
    assert 400 <= r.status_code < 500
