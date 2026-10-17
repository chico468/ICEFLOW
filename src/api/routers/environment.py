"""Atmosphere, ocean and sea-ice fields.

Every response from this router carries `is_synthetic` and `source`, because these are the
layers that are simulated. The build specification makes that labelling a hard requirement: a
judge or an operator must never have to guess which numbers came from a model of the world and
which came from the world.
"""
from __future__ import annotations

from typing import Any, Dict, List

from fastapi import APIRouter, HTTPException, Query

from src.core.constants import DATA_PROVENANCE
from src.core.environment import EnvSample, get_environment
from src.core.sea_ice import IceState, get_sea_ice_model

router = APIRouter(prefix="/api/v1", tags=["environment"])

MAX_GRID_CELLS = 40_000


def _check_extent(lat_min: float, lat_max: float, lon_min: float, lon_max: float, res: float) -> None:
    if lat_max <= lat_min or lon_max <= lon_min:
        raise HTTPException(status_code=400, detail="Bounding box is empty or inverted.")
    cells = ((lat_max - lat_min) / res) * ((lon_max - lon_min) / (res * 2.0))
    if cells > MAX_GRID_CELLS:
        raise HTTPException(
            status_code=400,
            detail=f"Requested grid is {int(cells)} cells, above the {MAX_GRID_CELLS} limit. "
                   "Increase the resolution value or shrink the bounding box.",
        )


@router.get("/env/sample", response_model=EnvSample)
def env_sample(
    lat: float = Query(...), lon: float = Query(...),
    t_hours: float = Query(default=0.0),
    ice_concentration: float = Query(default=0.0, ge=0.0, le=1.0),
) -> EnvSample:
    """Wind, current, temperature, pressure and sea state at one point and time."""
    return get_environment().sample(lat, lon, t_hours, ice_concentration)


@router.get("/env/field")
def env_field(
    lat_min: float = Query(default=-75.0), lat_max: float = Query(default=-50.0),
    lon_min: float = Query(default=0.0), lon_max: float = Query(default=100.0),
    resolution_deg: float = Query(default=1.0, ge=0.25, le=5.0),
    t_hours: float = Query(default=0.0),
) -> Dict[str, Any]:
    """Gridded wind, current and sea state for the map layers."""
    _check_extent(lat_min, lat_max, lon_min, lon_max, resolution_deg)
    return get_environment().field(lat_min, lat_max, lon_min, lon_max, resolution_deg, t_hours)


@router.get("/ice/point", response_model=IceState)
def ice_point(
    lat: float = Query(...), lon: float = Query(...),
    t_hours: float = Query(default=0.0),
    lead_hours: float = Query(default=0.0, ge=0.0, le=240.0),
) -> IceState:
    """Full ice state at one point: concentration, thickness, WMO stage, drift and compression."""
    return get_sea_ice_model().state(lat, lon, t_hours, lead_hours)


@router.get("/ice/field")
def ice_field(
    lat_min: float = Query(default=-75.0), lat_max: float = Query(default=-55.0),
    lon_min: float = Query(default=0.0), lon_max: float = Query(default=100.0),
    resolution_deg: float = Query(default=0.5, ge=0.25, le=5.0),
    t_hours: float = Query(default=0.0),
    lead_hours: float = Query(default=0.0, ge=0.0, le=240.0),
) -> Dict[str, Any]:
    """Gridded ice concentration, thickness, drift, compression and polynya mask."""
    _check_extent(lat_min, lat_max, lon_min, lon_max, resolution_deg)
    return get_sea_ice_model().field(
        lat_min, lat_max, lon_min, lon_max, resolution_deg, t_hours, lead_hours
    )


@router.get("/ice/forecast-skill")
def forecast_skill(
    leads: str = Query(default="24,48,72,120,168", description="Comma-separated lead times in hours"),
) -> Dict[str, Any]:
    """
    Forecast verification against the analysis valid at the same time.

    The forecast never sees the verifying analysis, and a persistence baseline is reported
    alongside, because persistence is the bar any ice forecast has to clear. These figures are
    measured inside the synthetic environment and are labelled as such.
    """
    try:
        lead_list: List[float] = [float(x) for x in leads.split(",") if x.strip()]
    except ValueError:
        raise HTTPException(status_code=400, detail="`leads` must be comma-separated numbers.")
    if not lead_list or len(lead_list) > 12:
        raise HTTPException(status_code=400, detail="Provide between 1 and 12 lead times.")

    rows = get_sea_ice_model().skill_table(lead_list)
    return {
        "rows": rows,
        "is_synthetic": True,
        "provenance": DATA_PROVENANCE["sea_ice_field"],
        "metrics_note": (
            "RMSE and MAE are in concentration units (0 to 1). IIEE is the fraction of sample "
            "points where forecast and analysis disagree about the 15 percent ice-edge threshold. "
            "A positive skill score means the forecast beat persistence."
        ),
    }


@router.get("/ice/edge")
def ice_edge(
    lon_min: float = Query(default=-180.0), lon_max: float = Query(default=180.0),
    step_deg: float = Query(default=2.0, ge=0.5, le=10.0),
    t_hours: float = Query(default=0.0),
) -> Dict[str, Any]:
    """The modelled ice-edge latitude around the continent, for a quick situational overview."""
    import numpy as np

    model = get_sea_ice_model()
    lons = np.arange(lon_min, lon_max + 1e-9, step_deg)
    edge = model.ice_edge_lat(lons, t_hours)
    return {
        "lons": lons.round(3).tolist(),
        "edge_lat": np.round(edge, 3).tolist(),
        "valid_time_hours": t_hours,
        "is_synthetic": True,
        "source": "synthetic; stands in for OSI-SAF OSI-401-b ice-edge product",
    }
