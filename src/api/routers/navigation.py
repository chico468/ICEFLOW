"""Icebergs, route planning and route comparison."""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator

from src.core.constants import DATA_PROVENANCE, ICEBERG_EXCLUSION_RADIUS_NM
from src.core.environment_time import parse_utc_datetime, resolve_iceberg_target_time
from src.core.geo import great_circle_path
from src.core.iceberg_tracker import (
    ClosestApproach,
    IcebergForecastResult,
    IcebergProfile,
    closest_approach,
    predict_iceberg_drift,
)
from src.core.lindqvist_model import VESSEL_PRESETS, VesselParameters, get_vessel_preset
from src.core.polaris_risk import IceClass
from src.core.route_optimizer import (
    OptimizationSummary,
    PolarRouteOptimizer,
    RouteAlternativesResult,
    RouteWeights,
)
from src.data.icebergs import get_iceberg_profiles, get_profile
from src.data.observed_icebergs import load_snapshot as load_observed_icebergs
from src.data.stations import resolve_endpoint

router = APIRouter(prefix="/api/v1", tags=["navigation"])


# -------------------------------------------------------------------------- icebergs
@router.get("/icebergs")
def icebergs(
    lead_hours: int = Query(default=0, ge=0, le=240),
    t_hours: float = Query(default=0.0),
    target_t_hours: Optional[float] = Query(default=None),
) -> Dict[str, Any]:
    """
    The tracked catalogue, optionally propagated forward by the drift model.

    With `lead_hours` above zero every berg is integrated forward, so the positions returned are
    computed rather than looked up.
    """
    target_alignment: Optional[Dict[str, Any]] = None
    step_hours_override: Optional[int] = None
    if target_t_hours is not None:
        alignment = resolve_iceberg_target_time(target_t_hours)
        target_alignment = alignment.model_dump()
        if alignment.status != "resolved":
            return {
                "icebergs": [],
                "count": 0,
                "exclusion_radius_nm": ICEBERG_EXCLUSION_RADIUS_NM,
                "provenance": DATA_PROVENANCE["iceberg_catalogue"],
                "time_alignment": target_alignment,
            }
        lead_hours = alignment.forecast_lead_hours or 0
        t_hours = alignment.forcing_start_hours or 0.0
        step_hours_override = 1

    profiles = get_iceberg_profiles()
    out: List[Dict[str, Any]] = []
    for berg in profiles:
        entry: Dict[str, Any] = berg.model_dump() | {"size_class": berg.size_class()}
        if lead_hours > 0:
            step_hours = step_hours_override if step_hours_override is not None else max(6, lead_hours // 8)
            fc = predict_iceberg_drift(
                berg, forecast_hours=lead_hours, time_step_hours=step_hours,
                t0_hours=t_hours, ensemble_members=1,
            )
            last = fc.trajectory[-1]
            entry |= {
                "forecast_latitude": last.latitude,
                "forecast_longitude": last.longitude,
                "forecast_lead_hours": lead_hours,
                "drift_km": fc.net_displacement_km,
                "mass_lost_percent": fc.mass_lost_percent,
            }
        out.append(entry)
    res: Dict[str, Any] = {
        "icebergs": out,
        "count": len(out),
        "exclusion_radius_nm": ICEBERG_EXCLUSION_RADIUS_NM,
        "provenance": DATA_PROVENANCE["iceberg_catalogue"],
    }
    if target_alignment is not None:
        res["time_alignment"] = target_alignment
    return res


class IcebergDriftRequest(BaseModel):
    """v0.1 fields are all preserved. Leaving wind and current unset uses the environment fields."""

    iceberg: IcebergProfile
    wind_speed_ms: Optional[float] = None
    wind_direction_from_deg: Optional[float] = None
    current_speed_ms: Optional[float] = None
    current_direction_to_deg: Optional[float] = None
    forecast_hours: int = Field(default=72, ge=6, le=240)
    time_step_hours: int = Field(default=6, ge=1, le=48)
    ensemble_members: int = Field(default=1, ge=1, le=32)
    t0_hours: float = 0.0
    ice_concentration: float = Field(default=0.0, ge=0.0, le=1.0)
    apply_melt: bool = True


@router.post("/icebergs/predict-drift", response_model=IcebergForecastResult)
def predict_drift(req: IcebergDriftRequest) -> IcebergForecastResult:
    """RK4 Lagrangian drift with deterioration, optionally as a perturbed ensemble."""
    return predict_iceberg_drift(
        berg=req.iceberg,
        wind_speed_ms=req.wind_speed_ms,
        wind_direction_from_deg=req.wind_direction_from_deg,
        current_speed_ms=req.current_speed_ms,
        current_direction_to_deg=req.current_direction_to_deg,
        forecast_hours=req.forecast_hours,
        time_step_hours=req.time_step_hours,
        ensemble_members=req.ensemble_members,
        t0_hours=req.t0_hours,
        ice_concentration=req.ice_concentration,
        apply_melt=req.apply_melt,
    )


@router.get("/icebergs/observed")
def observed_icebergs() -> Dict[str, Any]:
    """
    The observed USNIC-format iceberg snapshot, exactly as dated in the file.

    This is an observation, not a live feed and not a forecast: the response carries the
    observation date, its age and a `stale` flag. It is not merged with the simulated catalogue
    and is not used by routing or alerts (`used_for_routing` is false).
    """
    return load_observed_icebergs()


@router.get("/icebergs/{berg_id}/drift", response_model=IcebergForecastResult)
def catalogue_drift(
    berg_id: str,
    forecast_hours: int = Query(default=72, ge=6, le=240),
    ensemble_members: int = Query(default=12, ge=1, le=32),
) -> IcebergForecastResult:
    berg = get_profile(berg_id)
    if berg is None:
        raise HTTPException(status_code=404, detail=f"Unknown iceberg: {berg_id}")
    return predict_iceberg_drift(
        berg, forecast_hours=forecast_hours, time_step_hours=max(6, forecast_hours // 12),
        ensemble_members=ensemble_members,
    )


# ---------------------------------------------------------------------------- routing
class RouteRequest(BaseModel):
    """v0.1 defaults preserved; every new field is optional."""

    start_lat: float = -55.0
    start_lon: float = 20.0
    dest_lat: float = -69.41
    dest_lon: float = 76.19
    ice_class: IceClass = IceClass.PC5
    # v1.0 additions
    origin_id: Optional[str] = Field(default=None, description="Station or port id, overrides start_lat/lon")
    destination_id: Optional[str] = Field(default=None, description="Station or port id, overrides dest_lat/lon")
    vessel_key: Optional[str] = None
    vessel: Optional[VesselParameters] = None
    weights: Optional[RouteWeights] = None
    departure_time_hours: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    planning_reference_iso: Optional[str] = None
    lead_hours: float = 0.0
    grid_resolution_deg: float = Field(default=0.5, ge=0.25, le=2.0)
    avoid_icebergs: bool = True
    departure_iso: Optional[str] = Field(default=None, description="Actual UTC departure time (ISO-8601 with offset).")
    environment_mode: Literal["simulated", "real_ice", "replay"] = Field(
        default="simulated",
        description="simulated: synthetic ice field; real_ice: latest cached NSIDC observation; replay: observed V6 field for replay_date.",
    )
    replay_date: Optional[str] = Field(default=None, description="ISO date (YYYY-MM-DD) for replay mode.")

    @field_validator("planning_reference_iso")
    @classmethod
    def _validate_planning_reference(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            parse_utc_datetime(value, "planning_reference_iso")
        return value

    @field_validator("departure_iso")
    @classmethod
    def _validate_departure_iso(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            parse_utc_datetime(value, "departure_iso")
        return value

    @field_validator("replay_date")
    @classmethod
    def _validate_replay_date(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            from datetime import datetime
            datetime.strptime(value, "%Y-%m-%d")
        return value


def _resolve_request(req: RouteRequest):
    start = (req.start_lat, req.start_lon)
    dest = (req.dest_lat, req.dest_lon)
    if req.origin_id:
        resolved = resolve_endpoint(req.origin_id)
        if resolved is None:
            raise HTTPException(status_code=400, detail=f"Unknown origin: {req.origin_id}")
        start = resolved
    if req.destination_id:
        resolved = resolve_endpoint(req.destination_id)
        if resolved is None:
            raise HTTPException(status_code=400, detail=f"Unknown destination: {req.destination_id}")
        dest = resolved

    vessel = req.vessel or (get_vessel_preset(req.vessel_key) if req.vessel_key else VesselParameters())
    return start, dest, vessel


@router.post("/route/optimize", response_model=OptimizationSummary)
def optimize(req: RouteRequest) -> OptimizationSummary:
    """
    Plan a passage, and measure it against the route a ship would sail with no ice information.

    Both routes are then sailed through identical physics; the saving is the difference. No fixed
    multiplier is applied anywhere in this endpoint.
    """
    start, dest, vessel = _resolve_request(req)
    optimizer = PolarRouteOptimizer(
        vessel=vessel,
        ice_class=req.ice_class,
        weights=req.weights,
        installed_power_kw=vessel.installed_power_kw,
        environment_mode=req.environment_mode,
        replay_date=req.replay_date,
    )
    return optimizer.optimize_route(
        start[0], start[1], dest[0], dest[1],
        grid_resolution_deg=req.grid_resolution_deg,
        departure_time_hours=req.departure_time_hours,
        avoid_icebergs=req.avoid_icebergs,
        departure_iso=req.departure_iso,
    )


@router.post("/route/alternatives", response_model=RouteAlternativesResult)
def alternatives(req: RouteRequest) -> RouteAlternativesResult:
    """Compare distinct objective profiles using one shared environmental cache and iceberg forecast."""
    start, dest, vessel = _resolve_request(req)
    optimizer = PolarRouteOptimizer(
        vessel=vessel,
        ice_class=req.ice_class,
        weights=req.weights,
        installed_power_kw=vessel.installed_power_kw,
        environment_mode=req.environment_mode,
        replay_date=req.replay_date,
    )
    return optimizer.optimize_alternatives(
        start[0], start[1], dest[0], dest[1],
        grid_resolution_deg=req.grid_resolution_deg,
        departure_time_hours=req.departure_time_hours,
        avoid_icebergs=req.avoid_icebergs,
        departure_iso=req.departure_iso,
    )


@router.post("/route/compare")
def compare(req: RouteRequest) -> Dict[str, Any]:
    """
    The optimised route, the ice-blind baseline and the raw great circle, side by side.

    The great circle is included because it is what a naive distance calculation would suggest,
    and it is usually not navigable at all - which is itself worth showing.
    """
    start, dest, vessel = _resolve_request(req)
    optimizer = PolarRouteOptimizer(
        vessel=vessel, ice_class=req.ice_class, weights=req.weights,
        installed_power_kw=vessel.installed_power_kw,
        environment_mode=req.environment_mode,
        replay_date=req.replay_date,
    )
    summary = optimizer.optimize_route(
        start[0], start[1], dest[0], dest[1],
        grid_resolution_deg=req.grid_resolution_deg,
        departure_time_hours=req.departure_time_hours,
        avoid_icebergs=req.avoid_icebergs,
        departure_iso=req.departure_iso,
    )

    cache, _ = optimizer._build_cache(start, dest, req.departure_time_hours,
                                      req.grid_resolution_deg, req.grid_resolution_deg * 2.0)
    gc_points = great_circle_path(start[0], start[1], dest[0], dest[1], 60)
    great_circle = optimizer.evaluate(cache, gc_points, "Great circle (ignores land and ice)",
                                      req.departure_time_hours)

    from src.data.landmask import is_land

    gc_crosses_land = any(is_land(lat, lon) for lat, lon in gc_points)

    return {
        "optimized": summary.optimized,
        "baseline": summary.baseline,
        "great_circle": great_circle,
        "great_circle_crosses_land": gc_crosses_land,
        "fuel_saved_percentage": summary.fuel_saved_percentage,
        "time_saved_hours": summary.time_saved_hours,
        "co2_saved_tonnes": summary.co2_saved_tonnes,
        "distance_delta_nm": summary.distance_delta_nm,
        "baseline_would_be_prohibited": summary.baseline_would_be_prohibited,
        "warnings": summary.warnings,
        "savings_method": summary.savings_method,
    }


@router.post("/route/iceberg-risk")
def route_iceberg_risk(req: RouteRequest) -> Dict[str, Any]:
    """Closest approach of every catalogued berg against a freshly planned route."""
    summary = optimize(req)
    waypoints = summary.optimized.waypoints if summary.optimized else summary.waypoints
    route_pts = [(w.latitude, w.longitude, w.cumulative_hours) for w in waypoints]

    approaches: List[ClosestApproach] = []
    for berg in get_iceberg_profiles():
        horizon = int(min(240, max(24, waypoints[-1].cumulative_hours))) if waypoints else 72
        forecast = predict_iceberg_drift(
            berg, forecast_hours=horizon, time_step_hours=max(6, horizon // 10), ensemble_members=1
        )
        approaches.append(closest_approach(forecast, route_pts))

    approaches.sort(key=lambda a: a.distance_nm)
    return {
        "route_waypoints": len(waypoints),
        "approaches": approaches,
        "highest_threat": approaches[0] if approaches else None,
    }
