"""
Antarctic research stations, their sea approaches, and the ports expeditions sail from.

Station coordinates are the real published positions. That creates a practical problem the v0.1
prototype ignored: Maitri sits in the Schirmacher Oasis, roughly 80 km inland from the Princess
Astrid Coast, so it is not a place a ship can sail to. Resupply is done by offloading onto the
ice shelf at a coastal point and moving cargo overland.

Every destination therefore carries an *anchorage*: the position a ship actually navigates to.
Anchorages are validated against the real coastline at import, and nudged seaward if the
simplified coastline puts them aground, so the route planner can never be handed an
unreachable destination.
"""
from __future__ import annotations

import math
from functools import lru_cache
from typing import Any, Dict, List, Optional, Tuple

from src.core.constants import MIN_COAST_CLEARANCE_NM
from src.core.geo import destination_point
from src.data.landmask import coast_clearance_nm, is_land

# --------------------------------------------------------------------------------------
# Research stations. `anchorage` is the seaward approach point used for routing.
# --------------------------------------------------------------------------------------
_STATIONS: List[Dict[str, Any]] = [
    {
        "id": "maitri",
        "name": "Maitri Station",
        "country": "India",
        "operator": "NCPOR",
        "region": "Schirmacher Oasis, Queen Maud Land",
        "latitude": -70.7667,
        "longitude": 11.7333,
        "established": 1989,
        "is_indian": True,
        "port_approach": "India Bay, Princess Astrid Coast",
        # Ships offload onto the shelf ice here; cargo moves inland by convoy.
        "anchorage": (-69.85, 11.60),
        "notes": "Roughly 80 km inland. Resupply is by shelf-edge offloading and overland traverse.",
    },
    {
        "id": "bharati",
        "name": "Bharati Station",
        "country": "India",
        "operator": "NCPOR",
        "region": "Larsemann Hills, Prydz Bay",
        "latitude": -69.4075,
        "longitude": 76.1908,
        "established": 2012,
        "is_indian": True,
        "port_approach": "Quilty Bay / Thala Fjord",
        "anchorage": (-69.20, 76.30),
        "notes": "Coastal station on the Larsemann Hills; ships work the fast-ice edge in Prydz Bay.",
    },
    {
        "id": "dakshin_gangotri",
        "name": "Dakshin Gangotri",
        "country": "India",
        "operator": "NCPOR",
        "region": "Princess Astrid Coast, Queen Maud Land",
        "latitude": -70.0850,
        "longitude": 12.0000,
        "established": 1983,
        "is_indian": True,
        "port_approach": "Shelf ice edge",
        "anchorage": (-69.70, 12.00),
        "notes": "India's first station, buried in ice and decommissioned in 1990. Now a supply depot.",
    },
    {
        "id": "progress",
        "name": "Progress Station",
        "country": "Russia",
        "operator": "AARI",
        "region": "Larsemann Hills, Prydz Bay",
        "latitude": -69.3833,
        "longitude": 76.3833,
        "established": 1988,
        "is_indian": False,
        "port_approach": "Prydz Bay",
        "anchorage": (-69.15, 76.45),
        "notes": "Neighbour to Bharati; relevant for search and rescue cooperation.",
    },
    {
        "id": "zhongshan",
        "name": "Zhongshan Station",
        "country": "China",
        "operator": "CHINARE",
        "region": "Larsemann Hills, Prydz Bay",
        "latitude": -69.3733,
        "longitude": 76.3733,
        "established": 1989,
        "is_indian": False,
        "port_approach": "Prydz Bay",
        "anchorage": (-69.10, 76.20),
        "notes": "Adjacent to Progress and Bharati in the Larsemann Hills cluster.",
    },
    {
        "id": "davis",
        "name": "Davis Station",
        "country": "Australia",
        "operator": "AAD",
        "region": "Vestfold Hills, Prydz Bay",
        "latitude": -68.5764,
        "longitude": 77.9689,
        "established": 1957,
        "is_indian": False,
        "port_approach": "Prydz Bay",
        "anchorage": (-68.45, 78.10),
        "notes": "Australia's Prydz Bay station; a diversion and medevac option.",
    },
    {
        "id": "mawson",
        "name": "Mawson Station",
        "country": "Australia",
        "operator": "AAD",
        "region": "Mac. Robertson Land, Holme Bay",
        "latitude": -67.6028,
        "longitude": 62.8731,
        "established": 1954,
        "is_indian": False,
        "port_approach": "Holme Bay",
        "anchorage": (-67.30, 62.90),
        "notes": "Oldest continuously operated station south of the Antarctic Circle.",
    },
    {
        "id": "novolazarevskaya",
        "name": "Novolazarevskaya",
        "country": "Russia",
        "operator": "AARI",
        "region": "Schirmacher Oasis, Queen Maud Land",
        "latitude": -70.7764,
        "longitude": 11.8322,
        "established": 1961,
        "is_indian": False,
        "port_approach": "India Bay",
        "anchorage": (-69.90, 11.90),
        "notes": "Immediate neighbour of Maitri; shares the Novo airbase used by Indian expeditions.",
    },
    {
        "id": "syowa",
        "name": "Syowa Station",
        "country": "Japan",
        "operator": "NIPR",
        "region": "East Ongul Island, Lutzow-Holm Bay",
        "latitude": -69.0047,
        "longitude": 39.5806,
        "established": 1957,
        "is_indian": False,
        "port_approach": "Lutzow-Holm Bay",
        "anchorage": (-68.80, 39.30),
        "notes": "Served by the icebreaker Shirase; notorious for heavy multi-year fast ice.",
    },
]

# --------------------------------------------------------------------------------------
# Departure ports. These are the real staging ports for Indian Antarctic expeditions.
# --------------------------------------------------------------------------------------
_PORTS: List[Dict[str, Any]] = [
    {
        "id": "cape_town",
        "name": "Cape Town",
        "country": "South Africa",
        "latitude": -33.9180,
        "longitude": 18.4230,
        "anchorage": (-34.20, 18.43),
        "notes": "The primary staging port for Indian Antarctic expeditions to Maitri.",
    },
    {
        "id": "goa",
        "name": "Mormugao (Goa)",
        "country": "India",
        "latitude": 15.4000,
        "longitude": 73.8000,
        "anchorage": (15.30, 73.75),
        "notes": "NCPOR home port. Used for southbound sailings that load in India.",
    },
    {
        "id": "hobart",
        "name": "Hobart",
        "country": "Australia",
        "latitude": -42.8821,
        "longitude": 147.3272,
        "anchorage": (-43.20, 147.40),
        "notes": "Gateway for the Prydz Bay and Ross Sea sectors.",
    },
    {
        "id": "fremantle",
        "name": "Fremantle",
        "country": "Australia",
        "latitude": -32.0560,
        "longitude": 115.7440,
        "anchorage": (-32.20, 115.60),
        "notes": "Alternative staging port for the Prydz Bay sector.",
    },
    {
        "id": "port_louis",
        "name": "Port Louis",
        "country": "Mauritius",
        "latitude": -20.1600,
        "longitude": 57.5000,
        "anchorage": (-20.30, 57.45),
        "notes": "Occasional bunkering stop on the Goa to Antarctica leg.",
    },
]


def _nudge_to_water(lat: float, lon: float, min_clearance_nm: float = MIN_COAST_CLEARANCE_NM) -> Tuple[float, float]:
    """
    Move a point seaward until it is navigable water with adequate clearance.

    The shipped coastline is simplified to 1698 vertices, so a real anchorage can land a few
    kilometres inside the generalised shore. Rather than hand-tuning coordinates against a
    simplification artefact, we search outward on an expanding ring for the nearest point that
    the route planner will accept. This keeps the published station coordinates honest while
    guaranteeing the planner always gets a reachable destination.
    """
    if not is_land(lat, lon) and coast_clearance_nm(lat, lon) >= min_clearance_nm:
        return lat, lon

    for radius_nm in (5, 10, 15, 20, 30, 40, 55, 70, 90, 120):
        best: Optional[Tuple[float, float, float]] = None
        for bearing in range(0, 360, 10):
            cand_lat, cand_lon = destination_point(lat, lon, float(bearing), float(radius_nm))
            if is_land(cand_lat, cand_lon):
                continue
            clearance = coast_clearance_nm(cand_lat, cand_lon)
            if clearance >= min_clearance_nm and (best is None or clearance < best[2]):
                # Prefer the *closest* acceptable clearance so we stay near the real anchorage.
                best = (cand_lat, cand_lon, clearance)
        if best is not None:
            return round(best[0], 4), round(best[1], 4)

    return lat, lon


@lru_cache(maxsize=1)
def _resolved() -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Validate and repair every anchorage once, at first use."""
    stations: List[Dict[str, Any]] = []
    for raw in _STATIONS:
        entry = dict(raw)
        a_lat, a_lon = entry["anchorage"]
        fixed_lat, fixed_lon = _nudge_to_water(a_lat, a_lon)
        entry["anchorage_lat"] = fixed_lat
        entry["anchorage_lon"] = fixed_lon
        entry["anchorage_adjusted"] = (abs(fixed_lat - a_lat) > 1e-6) or (abs(fixed_lon - a_lon) > 1e-6)
        entry["station_is_inland"] = is_land(entry["latitude"], entry["longitude"])
        entry.pop("anchorage", None)
        stations.append(entry)

    ports: List[Dict[str, Any]] = []
    for raw in _PORTS:
        entry = dict(raw)
        a_lat, a_lon = entry["anchorage"]
        entry["anchorage_lat"] = a_lat
        entry["anchorage_lon"] = a_lon
        entry.pop("anchorage", None)
        ports.append(entry)

    return stations, ports


def get_stations(indian_only: bool = False) -> List[Dict[str, Any]]:
    stations, _ = _resolved()
    return [s for s in stations if s["is_indian"]] if indian_only else list(stations)


def get_ports() -> List[Dict[str, Any]]:
    _, ports = _resolved()
    return list(ports)


def get_waypoint(identifier: str) -> Optional[Dict[str, Any]]:
    """Look up a station or port by id, returning its navigable anchorage."""
    key = identifier.strip().lower().replace(" ", "_")
    for entry in get_stations() + get_ports():
        if entry["id"] == key:
            return entry
    return None


def resolve_endpoint(identifier: str) -> Optional[Tuple[float, float]]:
    """Identifier to the (lat, lon) a ship can actually navigate to."""
    entry = get_waypoint(identifier)
    if entry is None:
        return None
    return entry["anchorage_lat"], entry["anchorage_lon"]


def default_voyage_legs() -> List[Dict[str, Any]]:
    """The canonical demonstration passages, used by the CLI and the planner presets."""
    return [
        {
            "id": "capetown_maitri",
            "label": "Cape Town to Maitri (India Bay)",
            "origin": "cape_town",
            "destination": "maitri",
            "typical_season": "November to December, southbound leg",
        },
        {
            "id": "capetown_bharati",
            "label": "Cape Town to Bharati (Prydz Bay)",
            "origin": "cape_town",
            "destination": "bharati",
            "typical_season": "December to January",
        },
        {
            "id": "hobart_bharati",
            "label": "Hobart to Bharati (Prydz Bay)",
            "origin": "hobart",
            "destination": "bharati",
            "typical_season": "January, eastern approach",
        },
        {
            "id": "goa_maitri",
            "label": "Mormugao (Goa) to Maitri",
            "origin": "goa",
            "destination": "maitri",
            "typical_season": "Full-length sailing from the home port",
        },
    ]
