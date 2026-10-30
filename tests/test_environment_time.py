"""Tests for shared environmental time contract and target alignment."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError

from src.api.main import app
from src.api.routers.navigation import RouteRequest
from src.api.routers.voyages import CreateVoyageRequest
from src.core.environment_time import (
    EnvironmentTimeError,
    resolve_active_voyage_time,
    resolve_iceberg_target_time,
    resolve_planning_time,
)
from src.core.iceberg_tracker import IcebergProfile
from src.core.lindqvist_model import get_vessel_preset
from src.core.polaris_risk import IceClass, IceType
from src.core.route_optimizer import OptimizationSummary, Waypoint
from src.core.voyage import VoyageEngine

client = TestClient(app)


def test_active_voyage_target_matches_timestamp_from_simulation_tick():
    departure = datetime.fromisoformat("2026-10-24T07:00:00+05:30")
    sim_hours = 12.0
    tick_timestamp = (departure.astimezone(timezone.utc) + timedelta(hours=sim_hours)).isoformat()

    resolved = resolve_active_voyage_time(
        departure,
        sim_hours,
        tick_timestamp,
        model_departure_time_hours=36.0,
    )

    assert resolved.target_time_utc == datetime.fromisoformat("2026-10-24T13:30:00+00:00")
    assert resolved.tick_time_utc == resolved.target_time_utc
    assert resolved.elapsed_sim_hours == sim_hours
    assert resolved.model_departure_time_hours == 36.0


def test_active_voyage_rejects_missing_naive_invalid_and_inconsistent_time():
    with pytest.raises(EnvironmentTimeError, match="timezone offset"):
        resolve_active_voyage_time("2026-10-24T12:00:00", 1.0)
    with pytest.raises(EnvironmentTimeError, match="inconsistent"):
        resolve_active_voyage_time("2026-10-24T12:00:00Z", 1.0, "2026-10-24T12:02:00Z")
    with pytest.raises(EnvironmentTimeError, match="cannot be negative"):
        resolve_active_voyage_time("2026-10-24T12:00:00Z", -1.0)
    with pytest.raises(EnvironmentTimeError, match="finite"):
        resolve_active_voyage_time("2026-10-24T12:00:00Z", float("nan"))
    with pytest.raises(EnvironmentTimeError, match="datetime range"):
        resolve_active_voyage_time("2026-10-24T12:00:00Z", 1e300)


def test_planning_time_resolves_reference_and_forecast_lead_in_utc():
    resolved = resolve_planning_time(
        "2026-10-24T07:00:00+05:30",
        lead_hours=18.0,
        departure_time_hours=42.0,
    )

    assert resolved.status == "resolved"
    assert resolved.reference_time_utc == datetime.fromisoformat("2026-10-24T01:30:00+00:00")
    assert resolved.target_time_utc == datetime.fromisoformat("2026-10-24T19:30:00+00:00")
    assert resolved.lead_hours == 18.0
    assert resolved.model_departure_time_hours == 42.0


def test_missing_planning_reference_is_explicit_and_keeps_model_clock_separate():
    resolved = resolve_planning_time(
        None,
        lead_hours=12.0,
        departure_time_hours=36.0,
    )

    assert resolved.status == "unavailable"
    assert resolved.target_time_utc is None
    assert resolved.model_departure_time_hours == 36.0
    assert "planning_reference_iso" in (resolved.reason or "")


def test_model_time_offsets_must_be_finite_and_non_negative():
    with pytest.raises(EnvironmentTimeError, match="departure_time_hours cannot be negative"):
        resolve_active_voyage_time("2026-10-24T12:00:00Z", 0.0, model_departure_time_hours=-1.0)
    with pytest.raises(EnvironmentTimeError, match="departure_time_hours must be a finite number"):
        resolve_planning_time("2026-10-24T12:00:00Z", departure_time_hours=float("inf"))
    with pytest.raises(EnvironmentTimeError, match="departure_time_hours cannot be negative"):
        resolve_planning_time("2026-10-24T12:00:00Z", departure_time_hours=-1.0)


def test_legacy_planning_and_voyage_requests_remain_valid_without_calendar_time():
    planning = RouteRequest()
    voyage = CreateVoyageRequest()

    assert planning.departure_time_hours == 0.0
    assert planning.planning_reference_iso is None
    assert planning.lead_hours == 0.0
    assert voyage.departure_time_hours == 0.0
    assert voyage.departure_iso is None
    assert (
        resolve_planning_time(
            planning.planning_reference_iso,
            planning.lead_hours,
            planning.departure_time_hours,
        ).status
        == "unavailable"
    )


def test_created_voyage_persists_the_resolved_plan_time_and_model_clock_separately():
    waypoint = Waypoint(
        latitude=-60.0,
        longitude=20.0,
        speed_knots=8.0,
        ice_concentration=0.0,
        ice_thickness_m=0.0,
        rio_score=100,
        is_safe=True,
        segment_fuel_tonnes=0.0,
        cumulative_fuel_tonnes=0.0,
        cumulative_hours=0.0,
    )
    plan = OptimizationSummary(
        origin=(-60.0, 20.0),
        destination=(-60.0, 20.0),
        total_distance_nm=0.0,
        total_transit_hours=0.0,
        total_fuel_burn_tonnes=0.0,
        baseline_direct_fuel_tonnes=0.0,
        fuel_saved_percentage=0.0,
        minimum_rio=100,
        waypoints_count=1,
        waypoints=[waypoint],
    )

    planning_time = resolve_planning_time(
        "2026-10-24T07:00:00+05:30",
        lead_hours=18.0,
        departure_time_hours=42.0,
    )
    requested_departure = planning_time.target_time_utc
    assert requested_departure == datetime.fromisoformat("2026-10-24T19:30:00+00:00")

    engine = VoyageEngine(
        vessel=get_vessel_preset("vasiliy_golovnin"),
        ice_class=IceClass.PC5,
        plan=plan,
        departure=requested_departure,
        departure_time_hours=42.0,
    )

    assert engine.state.departure_iso == "2026-10-24T19:30:00+00:00"
    assert engine.state.environment_time.target_time_utc == requested_departure
    assert engine.state.model_departure_time_hours == 42.0


def test_emitted_voyage_tick_carries_its_authoritative_utc_target(monkeypatch):
    from src.core import voyage as voyage_module

    waypoint = Waypoint(
        latitude=-60.0,
        longitude=20.0,
        speed_knots=8.0,
        ice_concentration=0.0,
        ice_thickness_m=0.0,
        rio_score=100,
        is_safe=True,
        segment_fuel_tonnes=0.0,
        cumulative_fuel_tonnes=0.0,
        cumulative_hours=0.0,
    )
    plan = OptimizationSummary(
        origin=(-60.0, 20.0),
        destination=(-59.0, 21.0),
        total_distance_nm=100.0,
        total_transit_hours=12.0,
        total_fuel_burn_tonnes=1.0,
        baseline_direct_fuel_tonnes=1.0,
        fuel_saved_percentage=0.0,
        minimum_rio=100,
        waypoints_count=1,
        waypoints=[waypoint],
    )
    ice = SimpleNamespace(
        concentration=0.0,
        thickness_m=0.0,
        ice_type=IceType.OPEN_WATER,
        concentration_tenths=0,
        compression_index=0.0,
        besetting_risk="LOW",
    )
    env = SimpleNamespace(
        wind_speed_ms=0.0,
        wind_dir_from_deg=0.0,
        sig_wave_height_m=0.0,
        t2m_c=0.0,
        sst_c=0.0,
        visibility_km=20.0,
    )

    monkeypatch.setattr(
        voyage_module,
        "calculate_rio",
        lambda *args, **kwargs: SimpleNamespace(max_recommended_speed_knots=12.0),
    )
    monkeypatch.setattr(voyage_module, "attainable_speed", lambda *args, **kwargs: 12.0)
    monkeypatch.setattr(
        voyage_module,
        "calculate_ice_resistance",
        lambda *args, **kwargs: SimpleNamespace(
            required_power_kw=1000.0, fuel_burn_rate_kg_per_hour=100.0
        ),
    )

    engine = VoyageEngine(
        vessel=get_vessel_preset("vasiliy_golovnin"),
        ice_class=IceClass.PC5,
        plan=plan,
        departure=datetime.fromisoformat("2026-10-24T19:30:00+00:00"),
        sea_ice=SimpleNamespace(state=lambda *args, **kwargs: ice),
        environment=SimpleNamespace(sample=lambda *args, **kwargs: env),
    )
    engine._advance_along_route = lambda *args, **kwargs: (-59.5, 20.5, 45.0)
    engine._distance_remaining = lambda *args, **kwargs: 50.0
    engine._evaluate_alerts = lambda *args, **kwargs: None

    tick = engine.step(hours=6.0, run_radar=False)

    assert tick.timestamp_iso == "2026-10-25T01:30:00+00:00"
    assert tick.environment_time.target_time_utc.isoformat() == tick.timestamp_iso
    assert tick.environment_time.elapsed_sim_hours == tick.sim_hours == 6.0


@pytest.mark.parametrize(
    "model,field",
    [
        (RouteRequest, "planning_reference_iso"),
        (CreateVoyageRequest, "departure_iso"),
    ],
)
def test_request_models_reject_timezone_naive_calendar_timestamps(model, field):
    with pytest.raises(ValidationError, match="timezone offset"):
        model(**{field: "2026-10-24T12:00:00"})


@pytest.mark.parametrize("model", [RouteRequest, CreateVoyageRequest])
@pytest.mark.parametrize("value", [-1.0, float("nan"), float("inf")])
def test_request_models_reject_invalid_model_time_offsets(model, value):
    with pytest.raises(ValidationError):
        model(departure_time_hours=value)


def test_iceberg_target_hours_map_to_forecast_lead_from_seed_epoch():
    resolved = resolve_iceberg_target_time(18.0)
    assert resolved.status == "resolved"
    assert resolved.target_model_hours == 18.0
    assert resolved.forecast_lead_hours == 18
    assert resolved.forcing_start_hours == 0.0


@pytest.mark.parametrize("hours", [18.5, 241.0, -1.0, float("nan")])
def test_iceberg_time_limitations_are_explicit(hours):
    resolved = resolve_iceberg_target_time(hours)
    assert resolved.status == "unavailable"
    assert resolved.reason


def test_iceberg_api_reports_active_target_alignment(monkeypatch):
    from src.api.routers import navigation

    monkeypatch.setattr(navigation, "get_iceberg_profiles", lambda: [])
    response = client.get("/api/v1/icebergs", params={"mode": "simulated", "target_t_hours": 18})

    assert response.status_code == 200
    assert response.json()["time_alignment"]["forecast_lead_hours"] == 18
    assert response.json()["time_alignment"]["forcing_start_hours"] == 0.0


def test_iceberg_api_uses_elapsed_time_as_lead_from_seed_not_forcing_start(monkeypatch):
    from src.api.routers import navigation

    berg = IcebergProfile(berg_id="TEST", latitude=-68, longitude=75)
    call = {}

    def predict(*args, **kwargs):
        call.update(kwargs)
        return SimpleNamespace(
            trajectory=[SimpleNamespace(latitude=-67.9, longitude=75.1)],
            net_displacement_km=10.0,
            mass_lost_percent=0.1,
        )

    monkeypatch.setattr(navigation, "get_iceberg_profiles", lambda: [berg])
    monkeypatch.setattr(navigation, "predict_iceberg_drift", predict)

    response = client.get("/api/v1/icebergs", params={"mode": "simulated", "target_t_hours": 4})

    assert response.status_code == 200
    assert call["forecast_hours"] == 4
    assert call["time_step_hours"] == 1
    assert call["t0_hours"] == 0.0
    assert response.json()["icebergs"][0]["forecast_lead_hours"] == 4


def test_iceberg_api_reports_unrepresentable_active_time(monkeypatch):
    from src.api.routers import navigation

    monkeypatch.setattr(navigation, "get_iceberg_profiles", lambda: [])
    response = client.get("/api/v1/icebergs", params={"mode": "simulated", "target_t_hours": 18.5})

    assert response.status_code == 200
    assert response.json()["icebergs"] == []
    assert response.json()["time_alignment"]["status"] == "unavailable"
