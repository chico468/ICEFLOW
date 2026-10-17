"""
Satellite bandwidth budget: measuring the under-50-KB-per-day claim instead of asserting it.

South of 60 S there is no geostationary coverage. Ships work over Iridium Certus, and on an
expedition vessel the science, welfare and operational traffic all share that link. A routing
system that expects to pull raster ice charts over it is a system that will be switched off.

The architecture answer is that the heavy computation stays ashore and only a compressed
description of the ice field crosses the link, with the shipboard console reconstructing what it
needs locally. This module quantifies that claim by actually building both payloads and
measuring them:

  full raster        every grid cell, as the API would serve it to a shore client
  contour payload    the ice edge and a few concentration contours as polylines, quantised to
                     the precision that navigation actually needs, then gzipped
  delta payload      only what changed since the last transmission

Everything here is a measurement of real serialised bytes. Nothing is estimated.
"""
from __future__ import annotations

import gzip
import json
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.core.sea_ice import SeaIceModel, get_sea_ice_model

#: Coordinates are quantised before transmission. Two decimal degrees is about 1.1 km of
#: latitude, which is finer than the ice model resolves and far finer than a ship can steer.
COORD_DECIMALS = 2
CONCENTRATION_LEVELS = (0.15, 0.4, 0.7, 0.9)
IRIDIUM_CERTUS_DAILY_BUDGET_KB = 50.0


def _gzip_size(payload: object) -> int:
    raw = json.dumps(payload, separators=(",", ":")).encode("utf-8")
    return len(gzip.compress(raw, compresslevel=9))


def _raw_size(payload: object) -> int:
    return len(json.dumps(payload, separators=(",", ":")).encode("utf-8"))


def _marching_squares_contour(
    grid: np.ndarray, lats: Sequence[float], lons: Sequence[float], level: float
) -> List[List[Tuple[float, float]]]:
    """
    Extract iso-concentration contours as polylines.

    A deliberately simple cell-edge crossing walk rather than a full marching-squares
    implementation with topology stitching: the payload only needs the geometry, and the
    segments are transmitted as an unordered soup that the shipboard client re-renders. Keeping
    it simple also keeps the measurement honest, because a cleverer contour would only make the
    payload smaller.
    """
    segments: List[List[Tuple[float, float]]] = []
    n_lat, n_lon = grid.shape
    for i in range(n_lat - 1):
        for j in range(n_lon - 1):
            cell = grid[i:i + 2, j:j + 2]
            if np.isnan(cell).any():
                continue
            above = cell >= level
            if above.all() or not above.any():
                continue
            points: List[Tuple[float, float]] = []
            # Interpolate the crossing along each of the four cell edges.
            corners = [
                (grid[i, j], grid[i, j + 1], lats[i], lons[j], lats[i], lons[j + 1]),
                (grid[i + 1, j], grid[i + 1, j + 1], lats[i + 1], lons[j], lats[i + 1], lons[j + 1]),
                (grid[i, j], grid[i + 1, j], lats[i], lons[j], lats[i + 1], lons[j]),
                (grid[i, j + 1], grid[i + 1, j + 1], lats[i], lons[j + 1], lats[i + 1], lons[j + 1]),
            ]
            for v0, v1, la0, lo0, la1, lo1 in corners:
                if (v0 - level) * (v1 - level) < 0:
                    f = (level - v0) / (v1 - v0)
                    points.append(
                        (round(la0 + (la1 - la0) * f, COORD_DECIMALS),
                         round(lo0 + (lo1 - lo0) * f, COORD_DECIMALS))
                    )
            if len(points) >= 2:
                segments.append(points[:2])
    return segments


def build_contour_payload(ice_field: Dict[str, Any]) -> Dict[str, Any]:
    """The compressed description that would actually cross the satellite link."""
    lats = ice_field["lats"]
    lons = ice_field["lons"]
    conc = np.asarray(ice_field["concentration"], dtype=np.float64)

    contours: Dict[str, List[List[Tuple[float, float]]]] = {}
    for level in CONCENTRATION_LEVELS:
        contours[f"{level:.2f}"] = _marching_squares_contour(conc, lats, lons, level)

    return {
        "v": 1,
        "t": ice_field.get("valid_time_hours", 0.0),
        "lead": ice_field.get("lead_hours", 0.0),
        "edge": [round(float(x), COORD_DECIMALS) for x in ice_field.get("ice_edge_lat", [])],
        "lon0": round(float(lons[0]), COORD_DECIMALS) if lons else 0.0,
        "dlon": round(float(lons[1] - lons[0]), COORD_DECIMALS) if len(lons) > 1 else 0.0,
        "contours": contours,
    }


def build_delta_payload(previous: Dict[str, Any], current: Dict[str, Any]) -> Dict[str, Any]:
    """Only the contour levels whose geometry actually changed since the last transmission."""
    changed: Dict[str, Any] = {}
    for level, segments in current.get("contours", {}).items():
        if previous.get("contours", {}).get(level) != segments:
            changed[level] = segments
    edge_changed = previous.get("edge") != current.get("edge")
    return {
        "v": 1,
        "t": current.get("t", 0.0),
        "base_t": previous.get("t", 0.0),
        "edge": current.get("edge") if edge_changed else None,
        "contours": changed,
    }


def bandwidth_report(
    lat_min: float = -72.0,
    lat_max: float = -55.0,
    lon_min: float = 40.0,
    lon_max: float = 95.0,
    resolution_deg: float = 0.5,
    updates_per_day: int = 4,
    sea_ice: Optional[SeaIceModel] = None,
) -> Dict[str, Any]:
    """
    Build the payloads and measure them.

    Returns real byte counts for the full raster, the gzipped contour payload and the gzipped
    delta, together with the resulting daily total and whether it fits the Iridium budget.
    """
    model = sea_ice or get_sea_ice_model()

    field_now = model.field(lat_min, lat_max, lon_min, lon_max, resolution_deg, 0.0, 0.0)
    field_next = model.field(lat_min, lat_max, lon_min, lon_max, resolution_deg, 0.0, 6.0)

    contour_now = build_contour_payload(field_now)
    contour_next = build_contour_payload(field_next)
    delta = build_delta_payload(contour_now, contour_next)

    raster_raw = _raw_size(field_now)
    raster_gz = _gzip_size(field_now)
    contour_raw = _raw_size(contour_now)
    contour_gz = _gzip_size(contour_now)
    delta_gz = _gzip_size(delta)

    # One full contour transmission per day, then deltas for the remaining update cycles.
    daily_bytes = contour_gz + delta_gz * max(0, updates_per_day - 1)
    daily_kb = daily_bytes / 1024.0

    return {
        "domain": {
            "lat_min": lat_min, "lat_max": lat_max,
            "lon_min": lon_min, "lon_max": lon_max,
            "resolution_deg": resolution_deg,
            "grid_cells": len(field_now["lats"]) * len(field_now["lons"]),
        },
        "full_raster_bytes": raster_raw,
        "full_raster_gzip_bytes": raster_gz,
        "contour_payload_bytes": contour_raw,
        "contour_payload_gzip_bytes": contour_gz,
        "delta_payload_gzip_bytes": delta_gz,
        "updates_per_day": updates_per_day,
        "daily_total_bytes": daily_bytes,
        "daily_total_kb": round(daily_kb, 2),
        "budget_kb": IRIDIUM_CERTUS_DAILY_BUDGET_KB,
        "within_budget": daily_kb <= IRIDIUM_CERTUS_DAILY_BUDGET_KB,
        "compression_ratio_vs_raster": round(raster_raw / max(daily_bytes, 1), 1),
        "contour_levels": list(CONCENTRATION_LEVELS),
        "coordinate_decimals": COORD_DECIMALS,
        "method": (
            "Measured, not estimated: both payloads are serialised and gzipped, and the byte "
            "counts above are the actual lengths. The daily total is one full contour "
            "transmission plus deltas for the remaining update cycles."
        ),
        "link": "Iridium Certus, the only practical option south of 60 S",
    }
