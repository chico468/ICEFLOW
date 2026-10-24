"""Opt-in real velocity fields read from the local cache; requests never fetch remote data."""
from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal

from fastapi import APIRouter, Query

from src.data.real_flow import FlowDataError, grid_subset, read_cached_flow

router = APIRouter(prefix="/api/v1/flow-data", tags=["real flow data"])

MAX_GRID_CELLS = 40_000
STALE_AFTER_HOURS = {"wind": 36, "current": 48}
ACQUISITION = {
    "wind": "python -m src.data.fetch_gfs_wind --date YYYY-MM-DD --cycle HH --lead-hours N",
    "current": "python -m src.data.fetch_copernicus_current --date YYYY-MM-DD",
}


@router.get("/{kind}")
def real_flow(
    kind: Literal["wind", "current"],
    date_: date | None = Query(default=None, alias="date", description="UTC valid date; latest cached field when omitted"),
    lat_min: float = Query(default=-80.0, ge=-90.0, le=90.0),
    lat_max: float = Query(default=-25.0, ge=-90.0, le=90.0),
    lon_min: float = Query(default=-180.0, ge=-180.0, le=180.0),
    lon_max: float = Query(default=180.0, ge=-180.0, le=180.0),
    resolution_deg: float = Query(default=1.0, ge=0.25, le=5.0),
) -> dict[str, Any]:
    """Return cached, validated geographic east/north velocity components or an explicit unavailable result."""
    if lat_max <= lat_min or lon_max <= lon_min:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail="Bounding box must be increasing and non-empty; longitude must use -180..180 degrees.")
    rows = int((lat_max - lat_min) / resolution_deg) + 1
    cols = int((lon_max - lon_min) / (2 * resolution_deg)) + 1
    if rows * cols > MAX_GRID_CELLS:
        from fastapi import HTTPException
        raise HTTPException(status_code=422, detail=f"Requested grid exceeds {MAX_GRID_CELLS} cells; increase resolution or reduce the bounds.")

    base: dict[str, Any] = {
        "kind": kind,
        "is_observed": kind == "current",
        "classification": "forecast" if kind == "wind" else "observation_based_analysis",
        "units": "m/s",
        "crs": "EPSG:4326",
        "coordinate_units": "degrees_north, degrees_east",
        "valid_date_requested": date_.isoformat() if date_ else None,
        "acquisition_command": ACQUISITION[kind],
    }
    try:
        field = read_cached_flow(kind, valid_date=date_)
        if field is None:
            return {"available": False, "reason": "No matching validated local flow file is cached.", "provenance": base}
        valid_time = datetime.fromisoformat(field.metadata["valid_time"].replace("Z", "+00:00"))
        age_hours = max(0.0, (datetime.now(timezone.utc) - valid_time.astimezone(timezone.utc)).total_seconds() / 3600)
        stale = age_hours > STALE_AFTER_HOURS[kind]
        lats, lons, u, v = grid_subset(field, lat_min, lat_max, lon_min, lon_max, resolution_deg)
        base.update(field.metadata)
        base.update({
            "kind": kind,
            "is_observed": kind == "current",
            "classification": field.metadata.get("classification", base["classification"]),
            "units": "m/s",
            "crs": "EPSG:4326",
            "coordinate_units": "degrees_north, degrees_east",
            "age_hours": round(age_hours, 1),
            "stale": stale,
            "stale_after_hours": STALE_AFTER_HOURS[kind],
            "cache_file": field.path.name,
            "requested_date_is_historical": date_ is not None,
        })
        return {"available": True, "reason": None, "provenance": base, "lats": lats, "lons": lons, "u": u, "v": v}
    except FlowDataError as exc:
        return {"available": False, "reason": f"Cached flow data are malformed or incompatible: {exc}", "provenance": base}
