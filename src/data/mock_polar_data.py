"""
Antarctic Polar Geospatial Data Generator & Ingestion Layer.
Simulates realistic sea-ice, weather, and iceberg observations around Maitri and Bharati stations.
"""
from typing import List, Dict, Any

def get_antarctic_stations() -> List[Dict[str, Any]]:
    return [
        {
            "name": "Maitri Station",
            "country": "India",
            "region": "Schirmacher Oasis, Queen Maud Land",
            "latitude": -70.7667,
            "longitude": 11.7333,
            "port_approach": "India Bay / Crown Bay"
        },
        {
            "name": "Bharati Station",
            "country": "India",
            "region": "Larsemann Hills, Prydz Bay",
            "latitude": -69.4075,
            "longitude": 76.1908,
            "port_approach": "Thala Fjord / Quilty Bay"
        }
    ]

def get_known_active_icebergs() -> List[Dict[str, Any]]:
    return [
        {
            "berg_id": "D-28-A",
            "origin": "Amery Ice Shelf",
            "latitude": -67.45,
            "longitude": 74.20,
            "length_m": 1200.0,
            "width_m": 650.0,
            "sail_height_m": 42.0,
            "keel_depth_m": 210.0,
            "mass_metric_tonnes": 8.5e7
        },
        {
            "berg_id": "A-74-C",
            "origin": "Brunt Ice Shelf",
            "latitude": -69.10,
            "longitude": 14.80,
            "length_m": 950.0,
            "width_m": 500.0,
            "sail_height_m": 38.0,
            "keel_depth_m": 190.0,
            "mass_metric_tonnes": 6.2e7
        }
    ]

def generate_polar_grid_geojson() -> Dict[str, Any]:
    """Generates GeoJSON feature collection representing polar sea ice zones."""
    features = []
    # Add stations
    for st in get_antarctic_stations():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [st["longitude"], st["latitude"]]
            },
            "properties": {
                "type": "Research_Station",
                "name": st["name"],
                "region": st["region"]
            }
        })
    # Add icebergs
    for bg in get_known_active_icebergs():
        features.append({
            "type": "Feature",
            "geometry": {
                "type": "Point",
                "coordinates": [bg["longitude"], bg["latitude"]]
            },
            "properties": {
                "type": "Tracked_Iceberg",
                "berg_id": bg["berg_id"],
                "length_m": bg["length_m"]
            }
        })
    return {
        "type": "FeatureCollection",
        "features": features
    }
