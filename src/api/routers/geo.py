"""Geography: coastline, stations, ports and the canonical voyage legs."""
from __future__ import annotations

from typing import Any, Dict

from fastapi import APIRouter, HTTPException, Query

from src.core.constants import DATA_PROVENANCE
from src.core.geo import from_epsg3031, haversine_nm, to_epsg3031
from src.data.expedition import programme_context
from src.data.icebergs import get_iceberg_catalogue
from src.data.landmask import coast_clearance_nm, get_land_mask, is_land
from src.data.stations import default_voyage_legs, get_ports, get_stations, get_waypoint

router = APIRouter(prefix="/api/v1/geo", tags=["geography"])


@router.get("/coastline")
def coastline() -> Dict[str, Any]:
    """
    Antarctic land polygons as GeoJSON.

    This is the same geometry the route planner uses as its hard land mask, served to the map so
    that what a user sees and what the optimiser respects cannot drift apart.
    """
    mask = get_land_mask()
    doc = dict(mask.geojson())
    doc["stats"] = mask.stats()
    doc["provenance"] = DATA_PROVENANCE["coastline"]
    return doc


@router.get("/stations")
def stations(indian_only: bool = Query(default=False)) -> Dict[str, Any]:
    """Research stations with their navigable anchorages, plus the departure ports."""
    return {
        "stations": get_stations(indian_only=indian_only),
        "ports": get_ports(),
        "legs": default_voyage_legs(),
        "provenance": DATA_PROVENANCE["stations"],
        "note": (
            "Station coordinates are the published positions. Some stations, Maitri among them, "
            "are inland; the anchorage is the position a ship can actually reach, and it is "
            "validated against the coastline at start-up."
        ),
    }


@router.get("/waypoint/{identifier}")
def waypoint(identifier: str) -> Dict[str, Any]:
    entry = get_waypoint(identifier)
    if entry is None:
        raise HTTPException(status_code=404, detail=f"Unknown station or port: {identifier}")
    return entry


@router.get("/point")
def point_info(lat: float = Query(...), lon: float = Query(...)) -> Dict[str, Any]:
    """Land test, coastal clearance and the polar stereographic coordinate for one position."""
    x, y = to_epsg3031(lat, lon)
    return {
        "lat": lat,
        "lon": lon,
        "is_land": is_land(lat, lon),
        "coast_clearance_nm": round(coast_clearance_nm(lat, lon), 2),
        "epsg3031": {"x_m": round(x, 1), "y_m": round(y, 1)},
        "roundtrip_wgs84": [round(v, 6) for v in from_epsg3031(x, y)],
    }


@router.get("/distance")
def distance(
    from_lat: float = Query(...), from_lon: float = Query(...),
    to_lat: float = Query(...), to_lon: float = Query(...),
) -> Dict[str, float]:
    nm = haversine_nm(from_lat, from_lon, to_lat, to_lon)
    return {"distance_nm": round(nm, 2), "distance_km": round(nm * 1.852, 2)}


@router.get("/icebergs-catalogue")
def catalogue() -> Dict[str, Any]:
    """The seed catalogue, before any drift is applied."""
    return {
        "icebergs": get_iceberg_catalogue(),
        "provenance": DATA_PROVENANCE["iceberg_catalogue"],
    }


@router.get("/programme")
def programme() -> Dict[str, Any]:
    """
    The Indian Antarctic programme: fleet, season, resupply method and legal framework.

    This is programme context rather than model output, and it is what turns a generic polar
    router into one that answers the actual problem statement. The season window in particular
    is a hard operational constraint: the sailing window is about 90 days, so a day saved in
    January is worth far more than the same day saved in principle.
    """
    return programme_context()
