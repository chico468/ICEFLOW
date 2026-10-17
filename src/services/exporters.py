"""
Export a planned route into the formats a real bridge can consume.

This matters more than it looks. Maritime regulation does not allow arbitrary software to be
installed inside a type-approved ECDIS, so a decision-support system cannot draw on the official
chart directly. What it can do is hand the ECDIS standard data over the ship's LAN, which the
ECDIS loads as a read-only overlay. That is the difference between a demo and something a master
could actually use, so the export formats are part of the product rather than an afterthought.

  GeoJSON   the route and its per-waypoint model state, for any GIS or web client
  GPX 1.1   route and track for import into ECDIS and chart plotters; element order matters,
            because strict parsers reject a GPX whose children are out of sequence
  CSV       the voyage log, for the expedition report and for post-voyage analysis
  S-411-like  an ice-overlay document shaped after the IHO S-411 sea-ice product. It is
            explicitly labelled as a representative subset, not a certified S-411 encoding,
            because claiming conformance we have not tested would be dishonest.
"""
from __future__ import annotations

import csv
import io
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Sequence
from xml.etree import ElementTree as ET

from src.core.constants import SYSTEM_NAME, SYSTEM_VERSION
from src.core.route_optimizer import OptimizationSummary, Waypoint
from src.core.voyage import VoyageState


# --------------------------------------------------------------------------------------
# GeoJSON
# --------------------------------------------------------------------------------------
def route_to_geojson(
    waypoints: Sequence[Waypoint],
    name: str = "ICEFLOW optimised route",
    extra_properties: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """LineString of the track plus one Point per waypoint carrying its full model state."""
    features: List[Dict[str, Any]] = [
        {
            "type": "Feature",
            "geometry": {
                "type": "LineString",
                "coordinates": [[w.longitude, w.latitude] for w in waypoints],
            },
            "properties": {
                "name": name,
                "kind": "route",
                "waypoint_count": len(waypoints),
                "total_distance_nm": waypoints[-1].distance_from_start_nm if waypoints else 0.0,
                **(extra_properties or {}),
            },
        }
    ]
    for index, w in enumerate(waypoints):
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [w.longitude, w.latitude]},
                "properties": {
                    "kind": "waypoint",
                    "index": index,
                    "name": f"WP{index:03d}",
                    **w.model_dump(),
                },
            }
        )
    return {
        "type": "FeatureCollection",
        "generator": f"{SYSTEM_NAME} {SYSTEM_VERSION}",
        "generated_iso": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "crs_note": "WGS84 lon/lat (EPSG:4326). Render in EPSG:3031 for polar work.",
        "features": features,
    }


def voyage_to_geojson(state: VoyageState) -> Dict[str, Any]:
    """The planned route, the ice-blind baseline, the track actually sailed, and every alert."""
    doc = route_to_geojson(
        state.planned_route,
        name=f"{state.origin_name or 'origin'} to {state.destination_name or 'destination'}",
        extra_properties={"voyage_id": state.voyage_id, "vessel": state.vessel_name},
    )
    if state.baseline_route:
        doc["features"].append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[w.longitude, w.latitude] for w in state.baseline_route],
                },
                "properties": {"kind": "baseline_route", "name": "Ice-blind shortest navigable route"},
            }
        )
    if len(state.travelled_track) > 1:
        doc["features"].append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[lon, lat] for lat, lon in state.travelled_track],
                },
                "properties": {"kind": "travelled_track", "name": "Track made good"},
            }
        )
    for alert in state.alerts:
        doc["features"].append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [alert.longitude, alert.latitude]},
                "properties": {
                    "kind": "alert",
                    "code": alert.code,
                    "severity": alert.severity,
                    "message": alert.message,
                    "advisory": alert.advisory,
                    "sim_hours": alert.sim_hours,
                },
            }
        )
    return doc


# --------------------------------------------------------------------------------------
# GPX 1.1
# --------------------------------------------------------------------------------------
_GPX_NS = "http://www.topografix.com/GPX/1/1"


def route_to_gpx(
    waypoints: Sequence[Waypoint],
    route_name: str = "ICEFLOW route",
    departure: Optional[datetime] = None,
) -> str:
    """
    GPX 1.1 with a <rte> for the plan and a <trk> for the same geometry.

    Chart plotters differ in which of the two they will import, so both are emitted. GPX 1.1
    enforces child element order inside <metadata> and <wpt>/<rtept>, and strict parsers reject
    a document that gets it wrong, so the order below is deliberate: name then desc then time.
    """
    departure = departure or datetime.now(timezone.utc)
    ET.register_namespace("", _GPX_NS)
    gpx = ET.Element(
        f"{{{_GPX_NS}}}gpx",
        {"version": "1.1", "creator": f"{SYSTEM_NAME} {SYSTEM_VERSION}"},
    )

    metadata = ET.SubElement(gpx, f"{{{_GPX_NS}}}metadata")
    ET.SubElement(metadata, f"{{{_GPX_NS}}}name").text = route_name
    ET.SubElement(metadata, f"{{{_GPX_NS}}}desc").text = (
        "POLARIS-constrained route. Ice fields are model output, not an official ice chart; "
        "use alongside, not instead of, the certified ECDIS and current ice bulletins."
    )
    ET.SubElement(metadata, f"{{{_GPX_NS}}}time").text = departure.strftime("%Y-%m-%dT%H:%M:%SZ")

    rte = ET.SubElement(gpx, f"{{{_GPX_NS}}}rte")
    ET.SubElement(rte, f"{{{_GPX_NS}}}name").text = route_name
    for index, w in enumerate(waypoints):
        pt = ET.SubElement(
            rte, f"{{{_GPX_NS}}}rtept", {"lat": f"{w.latitude:.6f}", "lon": f"{w.longitude:.6f}"}
        )
        ET.SubElement(pt, f"{{{_GPX_NS}}}name").text = f"WP{index:03d}"
        ET.SubElement(pt, f"{{{_GPX_NS}}}desc").text = (
            f"speed {w.speed_knots:.1f} kn, ice {w.ice_concentration * 10:.0f}/10 "
            f"{w.ice_thickness_m:.2f} m, RIO {w.rio_score}"
        )

    trk = ET.SubElement(gpx, f"{{{_GPX_NS}}}trk")
    ET.SubElement(trk, f"{{{_GPX_NS}}}name").text = f"{route_name} (track)"
    seg = ET.SubElement(trk, f"{{{_GPX_NS}}}trkseg")
    for w in waypoints:
        pt = ET.SubElement(
            seg, f"{{{_GPX_NS}}}trkpt", {"lat": f"{w.latitude:.6f}", "lon": f"{w.longitude:.6f}"}
        )
        ET.SubElement(pt, f"{{{_GPX_NS}}}time").text = (
            departure + timedelta(hours=w.cumulative_hours)
        ).strftime("%Y-%m-%dT%H:%M:%SZ")

    return '<?xml version="1.0" encoding="UTF-8"?>\n' + ET.tostring(gpx, encoding="unicode")


# --------------------------------------------------------------------------------------
# CSV
# --------------------------------------------------------------------------------------
def voyage_to_csv(state: VoyageState) -> str:
    """The tick-by-tick voyage log, one row per simulated hour."""
    buffer = io.StringIO()
    if not state.ticks:
        writer = csv.writer(buffer)
        writer.writerow(["no ticks recorded"])
        return buffer.getvalue()

    fields = list(state.ticks[0].model_dump().keys())
    writer = csv.DictWriter(buffer, fieldnames=fields, extrasaction="ignore", lineterminator="\n")
    writer.writeheader()
    for tick in state.ticks:
        row = tick.model_dump()
        row["active_alerts"] = "|".join(row.get("active_alerts") or [])
        writer.writerow(row)
    return buffer.getvalue()


def route_to_csv(waypoints: Sequence[Waypoint]) -> str:
    buffer = io.StringIO()
    if not waypoints:
        return "no waypoints\n"
    fields = list(waypoints[0].model_dump().keys())
    writer = csv.DictWriter(buffer, fieldnames=fields, lineterminator="\n")
    writer.writeheader()
    for w in waypoints:
        writer.writerow(w.model_dump())
    return buffer.getvalue()


# --------------------------------------------------------------------------------------
# S-411-shaped ice overlay
# --------------------------------------------------------------------------------------
def ice_overlay_s411(
    ice_field: Dict[str, Any],
    issued: Optional[datetime] = None,
) -> Dict[str, Any]:
    """
    An ice overlay document shaped after the IHO S-411 sea-ice product specification.

    This is a representative subset in JSON, carrying the concentration, stage of development and
    drift attributes an S-411 consumer expects, with WMO egg-code style attribution. It is NOT a
    certified S-411 encoding and does not claim conformance; producing one requires an S-100
    exchange set and validation against the IHO feature catalogue, which is a licensing and
    conformance exercise rather than a modelling one.
    """
    issued = issued or datetime.now(timezone.utc)
    lats = ice_field.get("lats", [])
    lons = ice_field.get("lons", [])
    conc = ice_field.get("concentration", [])
    thick = ice_field.get("thickness_m", [])

    features: List[Dict[str, Any]] = []
    for i, lat in enumerate(lats):
        for j, lon in enumerate(lons):
            try:
                c = conc[i][j]
                h = thick[i][j]
            except (IndexError, TypeError):
                continue
            if c < 0.1:
                continue
            features.append(
                {
                    "type": "Feature",
                    "geometry": {"type": "Point", "coordinates": [lon, lat]},
                    "properties": {
                        "featureName": "SeaIceArea",
                        "concentrationTenths": int(round(c * 10)),
                        "iceThicknessMetres": round(float(h), 2),
                        "stageOfDevelopment": _wmo_stage(h),
                        "informationOrigin": "model",
                    },
                }
            )

    return {
        "productSpecification": "S-411-like subset (not a certified S-411 encoding)",
        "conformanceClaim": "none; representative attribute subset only",
        "producerAgency": "MoES / NCPOR (prototype)",
        "generator": f"{SYSTEM_NAME} {SYSTEM_VERSION}",
        "issueDate": issued.isoformat(timespec="seconds"),
        "validTimeHours": ice_field.get("valid_time_hours", 0.0),
        "horizontalDatum": "EPSG:4326",
        "isSynthetic": ice_field.get("is_synthetic", True),
        "source": ice_field.get("source", "model output"),
        "featureCount": len(features),
        "features": features,
    }


def _wmo_stage(thickness_m: float) -> str:
    for label, bound in (
        ("New ice", 0.10),
        ("Grey ice", 0.15),
        ("Grey-white ice", 0.30),
        ("Thin first-year, 1st stage", 0.50),
        ("Thin first-year, 2nd stage", 0.70),
        ("Medium first-year", 1.20),
        ("Thick first-year", 2.00),
        ("Second-year", 2.80),
    ):
        if thickness_m <= bound:
            return label
    return "Multi-year"


def plan_to_geojson(summary: OptimizationSummary) -> Dict[str, Any]:
    """Both routes from a planning result, so the comparison is visible in any GIS."""
    doc = route_to_geojson(
        summary.optimized.waypoints if summary.optimized else summary.waypoints,
        name="POLARIS-constrained optimised route",
        extra_properties={
            "fuel_saved_percentage": summary.fuel_saved_percentage,
            "time_saved_hours": summary.time_saved_hours,
            "minimum_rio": summary.minimum_rio,
            "savings_method": summary.savings_method,
        },
    )
    if summary.baseline:
        doc["features"].append(
            {
                "type": "Feature",
                "geometry": {
                    "type": "LineString",
                    "coordinates": [[w.longitude, w.latitude] for w in summary.baseline.waypoints],
                },
                "properties": {
                    "kind": "baseline_route",
                    "name": summary.baseline.label,
                    "total_fuel_burn_tonnes": summary.baseline.total_fuel_burn_tonnes,
                    "minimum_rio": summary.baseline.minimum_rio,
                },
            }
        )
    return doc
