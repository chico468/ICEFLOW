"""Time-aware metadata and public tile references for Copernicus Marine layers."""
from __future__ import annotations

from datetime import datetime
from typing import Literal

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.environment_time import (
    EnvironmentTimeError,
    EnvironmentTimeResolution,
    parse_utc_datetime,
    resolve_active_voyage_time,
    resolve_planning_time,
)
from src.data.copernicus_marine import resolve_environment_layers

router = APIRouter(prefix="/api/v1/environment", tags=["Copernicus Marine layers"])


class EnvironmentLayerMetadata(BaseModel):
    key: str
    status: Literal[
        "ready",
        "stale",
        "unavailable",
        "outside_coverage",
        "unsupported_time",
        "error",
    ]
    target_time_utc: datetime
    source_valid_time_utc: datetime | None = None
    source_valid_interval_start_utc: datetime | None = None
    source_valid_interval_end_utc: datetime | None = None
    observation_time_utc: datetime | None = None
    retrieved_at_utc: datetime | None = None
    classification: Literal["observation", "analysis", "forecast"] | None = None
    forecast_lead_hours: float | None = None
    age_hours: float | None = None
    offset_hours: float | None = None
    product: str
    dataset: str | None = None
    layer: str | None = None
    variable: str
    units: str | None = None
    standard_name: str | None = None
    data_updated_at_utc: datetime | None = None
    metadata_updated_at_utc: datetime | None = None
    product_released_at_utc: datetime | None = None
    source_crs: str | None = None
    tile_matrix_set: str | None = None
    style: str | None = None
    tile_max_zoom: int | None = None
    tile_template: str | None = None
    tile_dimensions: dict[str, str] = Field(default_factory=dict)
    attribution: str
    provenance: str
    reason: str | None = None


class EnvironmentLayersResponse(BaseModel):
    target_time_utc: datetime
    mode: Literal["active_voyage", "planning_forecast"]
    time_resolution: EnvironmentTimeResolution
    layers: dict[str, EnvironmentLayerMetadata]


@router.get("/layers", response_model=EnvironmentLayersResponse)
def environment_layers(
    target_time_utc: str = Query(..., description="Resolved environmental target time in UTC."),
    mode: Literal["active_voyage", "planning_forecast"] = Query(...),
    departure_iso: str | None = Query(
        default=None,
        description="Required in active-voyage mode; voyage start with timezone.",
    ),
    sim_hours: float | None = Query(
        default=None,
        ge=0,
        description="Required in active-voyage mode; elapsed voyage hours.",
    ),
    timestamp_iso: str | None = Query(
        default=None,
        description="Optional WebSocket tick timestamp checked against departure plus sim_hours.",
    ),
    planning_reference_iso: str | None = Query(
        default=None,
        description="Required in planning mode; timezone-aware forecast reference.",
    ),
    lead_hours: float = Query(default=0.0, ge=0),
    departure_time_hours: float = Query(
        default=0.0,
        ge=0,
        description="Model-relative offset; not interpreted as a UTC timestamp.",
    ),
) -> EnvironmentLayersResponse:
    """Resolve Copernicus layer times against the shared Phase 1 UTC time contract."""
    try:
        requested_target = parse_utc_datetime(target_time_utc, "target_time_utc")
        if mode == "active_voyage":
            if departure_iso is None or sim_hours is None:
                raise HTTPException(
                    status_code=422,
                    detail="active_voyage mode requires departure_iso and sim_hours.",
                )
            resolution = resolve_active_voyage_time(
                departure_iso,
                sim_hours,
                tick_timestamp_iso=timestamp_iso,
                model_departure_time_hours=departure_time_hours,
            )
        else:
            if planning_reference_iso is None:
                raise HTTPException(
                    status_code=422,
                    detail="planning_forecast mode requires planning_reference_iso.",
                )
            resolution = resolve_planning_time(
                planning_reference_iso,
                lead_hours=lead_hours,
                departure_time_hours=departure_time_hours,
            )
        resolved_target = resolution.target_time_utc
        if resolved_target is None:
            raise HTTPException(status_code=422, detail=resolution.reason)
        if abs((resolved_target - requested_target).total_seconds()) > 1.1:
            raise HTTPException(
                status_code=422,
                detail="target_time_utc is inconsistent with the supplied Phase 1 time inputs.",
            )
    except EnvironmentTimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    return EnvironmentLayersResponse(
        target_time_utc=resolved_target,
        mode=mode,
        time_resolution=resolution,
        layers=resolve_environment_layers(resolved_target),
    )