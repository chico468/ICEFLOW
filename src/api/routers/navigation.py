"""Icebergs, route planning and route comparison."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Dict, List, Literal, Optional, Tuple

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.constants import DATA_PROVENANCE, ICEBERG_EXCLUSION_RADIUS_NM, KM_PER_NM
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
from src.data.nsidc_sea_ice import NSIDCUnavailableError
from src.data.observed_icebergs import load_snapshot as load_observed_icebergs
from src.data.stations import resolve_endpoint
from src.ml.iceberg_dataset import load_database, nearest_at_or_before

router = APIRouter(prefix="/api/v1", tags=["navigation"])


def _build_optimizer(req: RouteRequest) -> Tuple[PolarRouteOptimizer, Tuple[float, float], Tuple[float, float]]:
    """Resolve endpoints and construct the planner, turning observational data failures into 4xx.

    Returns (optimizer, start, dest).
    """
    start, dest, vessel = _resolve_request(req)
    try:
        optimizer = PolarRouteOptimizer(
            vessel=vessel,
            ice_class=req.ice_class,
            weights=req.weights,
            installed_power_kw=vessel.installed_power_kw,
            environment_mode=req.environment_mode,
            replay_date=req.replay_date,
        )
    except NSIDCUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"environment_mode='{req.environment_mode}' could not be honoured: {exc}",
        ) from exc
    return optimizer, start, dest


# -------------------------------------------------------------------------- icebergs
@router.get("/icebergs")
def icebergs(
    mode: str = Query(default="observed", pattern="^(observed|simulated)$"),
    at: Optional[str] = Query(
        default=None,
        description="Target time (ISO-8601). In observed mode, each berg is the nearest "
        "observation at or before this time (source dates are YYYYDDD, parsed exactly; "
        "no approximate or interpolated matching).",
    ),
    lead_hours: int = Query(default=0, ge=0, le=240),
    t_hours: float = Query(default=0.0),
    target_t_hours: Optional[float] = Query(default=None),
) -> Dict[str, Any]:
    """
    Iceberg positions.

    Default ``mode="observed"`` returns real observed icebergs (USNIC/NIC snapshot, overlaid with
    the BYU/NIC track nearest at or before ``at`` when ``at`` is given). Every entry carries
    ``last_obs``, ``age_days``, size in nautical miles and provenance ``observed``. Seeded /
    simulated catalogue positions are only returned with ``mode="simulated"``; the old catalogue
    is no longer the default path.

    With ``lead_hours`` above zero every berg is integrated forward by the drift model and the
    returned positions are computed forecasts (kind ``real_forecast``) rather than look-ups.
    """
    if mode == "simulated":
        return _icebergs_simulated(lead_hours, t_hours, target_t_hours)
    return _icebergs_observed(at, lead_hours)


def _icebergs_simulated(
    lead_hours: int, t_hours: float, target_t_hours: Optional[float]
) -> Dict[str, Any]:
    target_alignment: Optional[Dict[str, Any]] = None
    step_hours_override: Optional[int] = None
    if target_t_hours is not None:
        alignment = resolve_iceberg_target_time(target_t_hours)
        target_alignment = alignment.model_dump()
        if alignment.status != "resolved":
            return {
                "icebergs": [],
                "count": 0,
                "mode": "simulated",
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
        "mode": "simulated",
        "exclusion_radius_nm": ICEBERG_EXCLUSION_RADIUS_NM,
        "provenance": DATA_PROVENANCE["iceberg_catalogue"],
    }
    if target_alignment is not None:
        res["time_alignment"] = target_alignment
    return res


def _icebergs_observed(at: Optional[str], lead_hours: int) -> Dict[str, Any]:
    snapshot = load_observed_icebergs()
    available = bool(snapshot.get("available"))
    bergs: List[Dict[str, Any]] = [dict(b) for b in snapshot.get("icebergs", [])] if available else []

    at_dt: Optional[datetime] = None
    at_date: Optional[date] = None
    if at is not None:
        at_dt = parse_utc_datetime(at)
        at_date = at_dt.date()

    # BYU/NIC track: nearest observation at or before ``at``. Dates match exactly (YYYYDDD),
    # never approximate; bergs with no on-or-before observation are omitted (never invented).
    byu_positions: Dict[str, Dict[str, Any]] = {}
    if at_date is not None:
        tracks = load_database()
        byu_positions = nearest_at_or_before(tracks, at_date)

    # Key the NIC snapshot bergs by id, then overlay BYU positions (BYU takes precedence for
    # position/date/size; NIC fills any size BYU lacks). BYU-only bergs are added.
    by_id: Dict[str, Dict[str, Any]] = {b["id"]: b for b in bergs}
    for berg_id, pos in byu_positions.items():
        entry: Dict[str, Any] = {
            "berg_id": berg_id,
            "id": berg_id,
            "latitude": pos["latitude"],
            "longitude": pos["longitude"],
            "last_obs": pos["last_obs"].isoformat(),
            "observed_date": pos["last_obs"].isoformat(),
            "length_nm": pos.get("size_major_nm"),
            "width_nm": pos.get("size_minor_nm"),
            "provenance": "observed",
            "source": "BYU/NIC v6 track - nearest observation at or before t0",
        }
        if berg_id in by_id:
            existing = by_id[berg_id]
            existing.update(entry)
            if existing.get("length_nm") is None and pos.get("size_major_nm") is not None:
                existing["length_nm"] = pos["size_major_nm"]
            if existing.get("width_nm") is None and pos.get("size_minor_nm") is not None:
                existing["width_nm"] = pos["size_minor_nm"]
        else:
            by_id[berg_id] = entry

    observed_bergs = list(by_id.values())

    # Normalize every entry: berg_id (alias for id), last_obs (from observed_date when BYU did
    # not supply it), provenance, and age relative to ``at`` (or the server clock).
    clock = at_date or datetime.now(timezone.utc).date()
    for b in observed_bergs:
        b.setdefault("provenance", "observed")
        b.setdefault("berg_id", b.get("id"))
        if "last_obs" not in b and "observed_date" in b:
            b["last_obs"] = b["observed_date"]
        last = date.fromisoformat(b["last_obs"])
        b["age_days"] = max(0, (clock - last).days)

    # Optional forward drift forecast (computed positions, not look-ups).
    if lead_hours > 0:
        step_hours = max(6, lead_hours // 8)
        for b in observed_bergs:
            berg = IcebergProfile(
                berg_id=b["berg_id"],
                latitude=b["latitude"],
                longitude=b["longitude"],
                length_m=((b.get("length_nm") or 0.0) * KM_PER_NM * 1000.0),
                width_m=((b.get("width_nm") or 0.0) * KM_PER_NM * 1000.0),
            )
            fc = predict_iceberg_drift(
                berg, forecast_hours=lead_hours, time_step_hours=step_hours, ensemble_members=1,
            )
            last = fc.trajectory[-1]
            b["forecast_latitude"] = last.latitude
            b["forecast_longitude"] = last.longitude
            b["forecast_lead_hours"] = lead_hours
            b["kind"] = "real_forecast"
            b["radii_nm"] = ICEBERG_EXCLUSION_RADIUS_NM

    return {
        "icebergs": observed_bergs,
        "count": len(observed_bergs),
        "mode": "observed",
        "provenance": "observed",
        "exclusion_radius_nm": ICEBERG_EXCLUSION_RADIUS_NM,
        "snapshot_available": available,
        "snapshot_date": snapshot.get("observed_date") if available else None,
        "snapshot_stale": snapshot.get("stale") if available else None,
    }


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

    @model_validator(mode="after")
    def _require_replay_date(self) -> "RouteRequest":
        if self.environment_mode == "replay" and not self.replay_date:
            raise ValueError("replay_date is required when environment_mode is 'replay'.")
        return self


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
    optimizer, (start_lat, start_lon), (dest_lat, dest_lon) = _build_optimizer(req)
    return optimizer.optimize_route(
        start_lat, start_lon, dest_lat, dest_lon,
        grid_resolution_deg=req.grid_resolution_deg,
        departure_time_hours=req.departure_time_hours,
        avoid_icebergs=req.avoid_icebergs,
        departure_iso=req.departure_iso,
    )


@router.post("/route/alternatives", response_model=RouteAlternativesResult)
def alternatives(req: RouteRequest) -> RouteAlternativesResult:
    """Compare distinct objective profiles using one shared environmental cache and iceberg forecast."""
    optimizer, (start_lat, start_lon), (dest_lat, dest_lon) = _build_optimizer(req)
    return optimizer.optimize_alternatives(
        start_lat, start_lon, dest_lat, dest_lon,
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
    optimizer, (start_lat, start_lon), (dest_lat, dest_lon) = _build_optimizer(req)
    summary = optimizer.optimize_route(
        start_lat, start_lon, dest_lat, dest_lon,
        grid_resolution_deg=req.grid_resolution_deg,
        departure_time_hours=req.departure_time_hours,
        avoid_icebergs=req.avoid_icebergs,
        departure_iso=req.departure_iso,
    )

    cache, _ = optimizer._build_cache((start_lat, start_lon), (dest_lat, dest_lon),
                                      req.departure_time_hours,
                                      req.grid_resolution_deg, req.grid_resolution_deg * 2.0)
    gc_points = great_circle_path(start_lat, start_lon, dest_lat, dest_lon, 60)
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
