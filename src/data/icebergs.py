"""
Tracked iceberg catalogue.

Berg names, calving origins and approximate dimensions follow the US National Ice Center
Antarctic iceberg tracking database and the BYU Center for Remote Sensing archive, which name
and track every berg with a waterline length of at least 10 nautical miles. Seed positions are
placed in the sector each berg is known to occupy; from there the drift model propagates them,
so any position you see in the running system was computed, not looked up.

Smaller bergs and bergy bits below the naming threshold are generated from the ice field itself
rather than catalogued, because in reality nobody tracks them individually - which is precisely
what makes them dangerous.
"""
from __future__ import annotations

from typing import Any, Dict, List

from src.core.iceberg_tracker import IcebergProfile

#: Named tabular bergs relevant to the Indian Antarctic sectors (Queen Maud Land and Prydz Bay).
_CATALOGUE: List[Dict[str, Any]] = [
    {
        "berg_id": "D-28",
        "origin": "Amery Ice Shelf",
        "calved": "2019-09-26",
        "latitude": -66.90,
        "longitude": 73.40,
        "length_m": 54_000.0,
        "width_m": 28_000.0,
        "sail_height_m": 30.0,
        "keel_depth_m": 190.0,
        "notes": "The 'Molar Berg', roughly 1600 km2 at calving. Directly relevant to the Prydz Bay approach.",
    },
    {
        "berg_id": "D-30A",
        "origin": "Amery Ice Shelf",
        "calved": "2021-05-01",
        "latitude": -65.80,
        "longitude": 68.20,
        "length_m": 32_000.0,
        "width_m": 19_000.0,
        "sail_height_m": 28.0,
        "keel_depth_m": 175.0,
        "notes": "Fragment drifting west in the Antarctic Coastal Current toward Mawson.",
    },
    {
        "berg_id": "A-74",
        "origin": "Brunt Ice Shelf",
        "calved": "2021-02-26",
        "latitude": -70.20,
        "longitude": -22.50,
        "length_m": 42_000.0,
        "width_m": 28_000.0,
        "sail_height_m": 32.0,
        "keel_depth_m": 185.0,
        "notes": "Calved along Chasm-1; drifts the Weddell gyre past the Queen Maud Land approach.",
    },
    {
        "berg_id": "A-23A",
        "origin": "Filchner Ice Shelf",
        "calved": "1986-01-01",
        "latitude": -61.50,
        "longitude": -40.00,
        "length_m": 72_000.0,
        "width_m": 48_000.0,
        "sail_height_m": 40.0,
        "keel_depth_m": 280.0,
        "notes": "One of the largest bergs afloat; grounded for decades before moving north.",
    },
    {
        "berg_id": "C-38",
        "origin": "Ross Ice Shelf",
        "calved": "2022-03-15",
        "latitude": -64.20,
        "longitude": 118.00,
        "length_m": 25_000.0,
        "width_m": 14_000.0,
        "sail_height_m": 26.0,
        "keel_depth_m": 165.0,
        "notes": "Eastern sector berg, included to exercise the catalogue beyond the Indian approaches.",
    },
    {
        "berg_id": "B-15AB",
        "origin": "Ross Ice Shelf",
        "calved": "2000-03-17",
        "latitude": -63.10,
        "longitude": 95.50,
        "length_m": 18_000.0,
        "width_m": 11_000.0,
        "sail_height_m": 24.0,
        "keel_depth_m": 150.0,
        "notes": "Long-lived remnant of the record B-15 calving.",
    },
    {
        "berg_id": "D-21B",
        "origin": "Amery Ice Shelf",
        "calved": "2015-11-02",
        "latitude": -68.10,
        "longitude": 79.60,
        "length_m": 12_000.0,
        "width_m": 7_000.0,
        "sail_height_m": 22.0,
        "keel_depth_m": 140.0,
        "notes": "Sits close to the Davis and Bharati approach lanes in eastern Prydz Bay.",
    },
]


def get_iceberg_catalogue() -> List[Dict[str, Any]]:
    """Raw catalogue entries, including provenance metadata."""
    return [dict(entry) for entry in _CATALOGUE]


def get_iceberg_profiles() -> List[IcebergProfile]:
    """Catalogue as drift-model inputs."""
    profiles: List[IcebergProfile] = []
    for entry in _CATALOGUE:
        profiles.append(
            IcebergProfile(
                berg_id=entry["berg_id"],
                latitude=entry["latitude"],
                longitude=entry["longitude"],
                length_m=entry["length_m"],
                width_m=entry["width_m"],
                sail_height_m=entry["sail_height_m"],
                keel_depth_m=entry["keel_depth_m"],
                # Derived from geometry rather than quoted, so melt accounting stays consistent.
                mass_metric_tonnes=0.0,
                origin=entry["origin"],
            )
        )
    # Fill the tonnage from geometry.
    return [p.model_copy(update={"mass_metric_tonnes": p.consistent_mass_kg() / 1000.0}) for p in profiles]


def get_profile(berg_id: str) -> IcebergProfile | None:
    for profile in get_iceberg_profiles():
        if profile.berg_id.lower() == berg_id.strip().lower():
            return profile
    return None


def bergs_near(lat: float, lon: float, radius_nm: float = 400.0) -> List[IcebergProfile]:
    """Catalogue entries within a radius, used to build route exclusion zones."""
    from src.core.geo import haversine_nm

    return [
        p for p in get_iceberg_profiles()
        if haversine_nm(lat, lon, p.latitude, p.longitude) <= radius_nm
    ]
