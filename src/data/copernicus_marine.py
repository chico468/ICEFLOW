"""Metadata-driven resolver for the public Copernicus Marine WMTS."""
from __future__ import annotations

import io
import math
import re
import threading
import time
import xml.etree.ElementTree as ET
from collections import OrderedDict
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from urllib.parse import quote, urlsplit

import httpx

from src.core.environment_time import parse_utc_datetime

WMTS_CAPABILITIES_URL = (
    "https://wmts.marine.copernicus.eu/teroWmts"
    "?service=WMTS&request=GetCapabilities"
)
WMTS_ATTRIBUTION = "Copernicus Marine Service (CMEMS)"
MAX_CAPABILITIES_BYTES = 90 * 1024 * 1024
METADATA_TTL_SECONDS = 30 * 60
METADATA_CACHE_SIZE = 4
_MAX_AXIS_TIMES = 50_000

_NS = {
    "wmts": "http://www.opengis.net/wmts/1.0",
    "ows": "http://www.opengis.net/ows/1.1",
    "xlink": "http://www.w3.org/1999/xlink",
}


@dataclass(frozen=True)
class WmtsLayer:
    identifier: str
    title: str
    formats: tuple[str, ...]
    styles: tuple[str, ...]
    tile_matrix_sets: tuple[str, ...]
    dimensions: dict[str, tuple[str, ...]]
    dimension_defaults: dict[str, str]
    wgs84_bounds: tuple[float, float, float, float] | None
    wgs84_bounds_reason: str | None
    units: str | None
    standard_name: str | None
    data_updated_at_utc: datetime | None
    metadata_updated_at_utc: datetime | None
    released_at_utc: datetime | None


@dataclass(frozen=True)
class TileMatrixSet:
    identifier: str
    supported_crs: str
    matrix_ids: tuple[str, ...]
    top_left_corner: tuple[float, float] | None
    tile_width: int | None
    tile_height: int | None
    matrix_dimensions: dict[str, tuple[int, int]]
    scale_denominators: dict[str, float]


@dataclass(frozen=True)
class WmtsCapabilities:
    service_title: str
    get_tile_url: str | None
    get_tile_encodings: tuple[str, ...]
    layers: dict[str, WmtsLayer]
    tile_matrix_sets: dict[str, TileMatrixSet]
    retrieved_at_utc: datetime


@dataclass(frozen=True)
class LayerSpec:
    key: str
    product: str
    dataset_fragment: str
    variable: str
    temporal_kind: str
    pair: str | None
    max_offset_hours: float
    preferred_dataset_fragment: str | None = None


LAYER_SPECS = (
    LayerSpec(
        "sea_ice_edge",
        "SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001",
        "osisaf_obs-si_glo_phy-siedge_nrt_sh-P1D",
        "ice_edge",
        "observation",
        None,
        72,
    ),
    LayerSpec(
        "sea_ice_concentration",
        "SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001",
        "osisaf_obs-si_glo_phy-sic-south_nrt_amsr2_l4_P1D-m",
        "ice_conc",
        "observation",
        None,
        72,
    ),
    LayerSpec(
        "antarctic_high_resolution_concentration",
        "SEAICE_ANT_PHY_AUTO_L3_NRT_011_012",
        "cmems_obs-si_ant_phy_nrt_l3-1km_P1D",
        "ice_concentration",
        "observation",
        None,
        72,
    ),
    LayerSpec(
        "sea_ice_concentration_forecast",
        "GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "cmems_mod_glo_phy_anfc_0.083deg_P1D-m",
        "siconc",
        "analysis_forecast",
        None,
        30,
    ),
    LayerSpec(
        "ocean_current_eastward",
        "GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "cmems_mod_glo_phy-cur_anfc_0.083deg",
        "uo",
        "analysis_forecast",
        "surface_currents",
        9,
        "PT6H-i",
    ),
    LayerSpec(
        "ocean_current_northward",
        "GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "cmems_mod_glo_phy-cur_anfc_0.083deg",
        "vo",
        "analysis_forecast",
        "surface_currents",
        9,
        "PT6H-i",
    ),
    LayerSpec(
        "sea_surface_temperature_anomaly",
        "GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "cmems_mod_glo_phy_anfc_0.083deg-sst-anomaly_P1D-m",
        "sea_surface_temperature_anomaly",
        "analysis_forecast",
        None,
        30,
    ),
)

_metadata_cache: OrderedDict[str, tuple[float, WmtsCapabilities]] = OrderedDict()
_cache_lock = threading.Lock()


class CopernicusMarineError(RuntimeError):
    """Raised when WMTS metadata cannot be retrieved or parsed safely."""


def _local_name(tag: str) -> str:
    return tag.rsplit("}", 1)[-1]


def _text(element: ET.Element | None, path: str) -> str | None:
    if element is None:
        return None
    child = element.find(path, _NS)
    if child is None or child.text is None:
        return None
    return child.text.strip()


def _child_text(element: ET.Element | None, name: str) -> str | None:
    if element is None:
        return None
    for child in element:
        if _local_name(child.tag) == name and child.text:
            return child.text.strip()
    return None


def _metadata_value(element: ET.Element, key: str) -> str | None:
    metadata = element.find("ows:Metadata", _NS)
    if metadata is None:
        return None
    for child in metadata.iter():
        if _local_name(child.tag) == key and child.text and child.text.strip():
            return child.text.strip()
    return None


def _metadata_datetime(element: ET.Element, key: str) -> datetime | None:
    value = _metadata_value(element, key)
    if not value:
        return None
    try:
        return parse_utc_datetime(value, f"WMTS metadata {key}")
    except ValueError:
        return None


def _parse_layer(element: ET.Element) -> WmtsLayer | None:
    identifier = _text(element, "ows:Identifier")
    if not identifier:
        return None
    title = _text(element, "ows:Title") or identifier
    styles = tuple(
        value
        for style in element.findall("wmts:Style", _NS)
        if (value := _text(style, "ows:Identifier"))
    )
    dimensions: dict[str, tuple[str, ...]] = {}
    dimension_defaults: dict[str, str] = {}
    for dimension in element.findall("wmts:Dimension", _NS):
        name = _text(dimension, "ows:Identifier")
        if name:
            default = _text(dimension, "wmts:Default")
            if default:
                dimension_defaults[name.lower()] = default
            dimensions[name.lower()] = tuple(
                value.strip()
                for item in dimension.findall("wmts:Value", _NS)
                if item.text and (value := item.text.strip())
            )
    bounds: tuple[float, float, float, float] | None = None
    bounds_reason: str | None = None
    bounding_box = next(
        (child for child in element if _local_name(child.tag) == "WGS84BoundingBox"),
        None,
    )
    lower_corner = _child_text(bounding_box, "LowerCorner")
    upper_corner = _child_text(bounding_box, "UpperCorner")
    if bounding_box is not None:
        if not lower_corner or not upper_corner:
            bounds_reason = "WMTS layer advertises incomplete WGS84 coverage bounds."
        else:
            try:
                lower = tuple(float(value) for value in lower_corner.split())
                upper = tuple(float(value) for value in upper_corner.split())
            except ValueError:
                bounds_reason = "WMTS layer advertises malformed WGS84 coverage bounds."
            else:
                labels = bounding_box.attrib.get("axisLabels", "").lower().split()
                axis_order = (
                    "lat_lon"
                    if labels in (["lat", "long"], ["latitude", "longitude"])
                    else "lon_lat"
                    if labels in (["long", "lat"], ["longitude", "latitude"])
                    else None
                )

                def valid_box(west: float, south: float, east: float, north: float) -> bool:
                    return (
                        all(math.isfinite(value) for value in (west, south, east, north))
                        and -180 <= west < east <= 180
                        and -90 <= south < north <= 90
                    )

                if len(lower) == 2 and len(upper) == 2:
                    lon_lat_valid = valid_box(lower[0], lower[1], upper[0], upper[1])
                    lat_lon_valid = valid_box(lower[1], lower[0], upper[1], upper[0])
                    if axis_order == "lat_lon" and lat_lon_valid:
                        bounds = (lower[1], lower[0], upper[1], upper[0])
                    elif axis_order == "lon_lat" and lon_lat_valid:
                        bounds = (lower[0], lower[1], upper[0], upper[1])
                    elif axis_order is None and lon_lat_valid:
                        bounds = (lower[0], lower[1], upper[0], upper[1])
                    elif axis_order is None and lat_lon_valid:
                        bounds = (lower[1], lower[0], upper[1], upper[0])
                if bounds is None:
                    bounds_reason = "WMTS layer advertises invalid WGS84 coverage bounds."
    return WmtsLayer(
        identifier=identifier,
        title=title,
        formats=tuple(
            value.text.strip()
            for value in element.findall("wmts:Format", _NS)
            if value.text and value.text.strip()
        ),
        styles=styles,
        tile_matrix_sets=tuple(
            value.text.strip()
            for value in element.findall("wmts:TileMatrixSetLink/wmts:TileMatrixSet", _NS)
            if value.text and value.text.strip()
        ),
        dimensions=dimensions,
        dimension_defaults=dimension_defaults,
        wgs84_bounds=bounds,
        wgs84_bounds_reason=bounds_reason,
        units=_metadata_value(element, "Unit"),
        standard_name=_metadata_value(element, "StandardName"),
        data_updated_at_utc=_metadata_datetime(element, "admp_updated_data"),
        metadata_updated_at_utc=_metadata_datetime(element, "admp_updated"),
        released_at_utc=_metadata_datetime(element, "admp_released_date"),
    )


def _parse_tile_matrix_set(element: ET.Element) -> TileMatrixSet | None:
    identifier = _text(element, "ows:Identifier")
    supported_crs = _text(element, "ows:SupportedCRS")
    if not identifier or not supported_crs:
        return None
    matrix_elements = element.findall("wmts:TileMatrix", _NS)
    matrix_dimensions: dict[str, tuple[int, int]] = {}
    scale_denominators: dict[str, float] = {}
    for matrix in matrix_elements:
        matrix_id = _text(matrix, "ows:Identifier")
        width = _text(matrix, "wmts:MatrixWidth")
        height = _text(matrix, "wmts:MatrixHeight")
        if matrix_id and width and height:
            try:
                matrix_dimensions[matrix_id] = (int(width), int(height))
            except ValueError:
                pass
        scale = _text(matrix, "wmts:ScaleDenominator")
        if matrix_id and scale:
            try:
                scale_denominators[matrix_id] = float(scale)
            except ValueError:
                pass
    top_left = _text(matrix_elements[0], "wmts:TopLeftCorner") if matrix_elements else None
    try:
        top_left_corner = (
            tuple(float(value) for value in top_left.split())
            if top_left and len(top_left.split()) == 2
            else None
        )
    except ValueError:
        top_left_corner = None
    try:
        tile_width = int(_text(matrix_elements[0], "wmts:TileWidth")) if matrix_elements else None
        tile_height = int(_text(matrix_elements[0], "wmts:TileHeight")) if matrix_elements else None
    except (TypeError, ValueError):
        tile_width = tile_height = None
    return TileMatrixSet(
        identifier=identifier,
        supported_crs=supported_crs,
        matrix_ids=tuple(
            value.text.strip()
            for value in element.findall("wmts:TileMatrix/ows:Identifier", _NS)
            if value.text and value.text.strip()
        ),
        top_left_corner=top_left_corner,
        tile_width=tile_width,
        tile_height=tile_height,
        matrix_dimensions=matrix_dimensions,
        scale_denominators=scale_denominators,
    )


def parse_capabilities(
    document: bytes | str,
    *,
    retrieved_at_utc: datetime | None = None,
) -> WmtsCapabilities:
    """Parse WMTS layers and KVP operations while releasing the large XML tree."""
    payload = document.encode("utf-8") if isinstance(document, str) else document
    if len(payload) > MAX_CAPABILITIES_BYTES:
        raise CopernicusMarineError("WMTS capabilities document exceeds the configured size limit.")

    layers: dict[str, WmtsLayer] = {}
    matrix_sets: dict[str, TileMatrixSet] = {}
    service_title = "Copernicus Marine WMTS"
    get_tile_url: str | None = None
    encodings: set[str] = set()
    stack: list[ET.Element] = []
    try:
        for event, element in ET.iterparse(io.BytesIO(payload), events=("start", "end")):
            if event == "start":
                stack.append(element)
                continue

            parent = stack[-2] if len(stack) > 1 else None
            name = _local_name(element.tag)
            if name == "Layer":
                layer = _parse_layer(element)
                if layer:
                    layers[layer.identifier] = layer
                if parent is not None:
                    parent.remove(element)
                element.clear()
            elif name == "TileMatrixSet" and _text(element, "ows:SupportedCRS"):
                matrix_set = _parse_tile_matrix_set(element)
                if matrix_set:
                    matrix_sets[matrix_set.identifier] = matrix_set
                if parent is not None:
                    parent.remove(element)
                element.clear()
            elif name == "Operation" and element.attrib.get("name") == "GetTile":
                for get in element.iter():
                    if _local_name(get.tag) == "Get":
                        candidate = get.attrib.get(f"{{{_NS['xlink']}}}href")
                        if candidate:
                            parsed_url = urlsplit(candidate)
                            if (
                                parsed_url.scheme == "https"
                                and parsed_url.hostname
                                and parsed_url.username is None
                                and parsed_url.password is None
                                and not parsed_url.query
                                and not parsed_url.fragment
                            ):
                                get_tile_url = candidate
                    elif _local_name(get.tag) == "Value" and get.text:
                        encodings.add(get.text.strip().upper())
                if parent is not None:
                    parent.remove(element)
                element.clear()
            elif name == "ServiceIdentification":
                service_title = _text(element, "ows:Title") or service_title
                if parent is not None:
                    parent.remove(element)
                element.clear()
            stack.pop()
    except (ET.ParseError, ValueError) as exc:
        raise CopernicusMarineError("WMTS capabilities response is malformed XML.") from exc

    if not layers:
        raise CopernicusMarineError("WMTS capabilities response contains no discoverable layers.")
    return WmtsCapabilities(
        service_title=service_title,
        get_tile_url=get_tile_url,
        get_tile_encodings=tuple(sorted(encodings)),
        layers=layers,
        tile_matrix_sets=matrix_sets,
        retrieved_at_utc=(
            parse_utc_datetime(retrieved_at_utc or datetime.now(timezone.utc))
        ),
    )


def clear_metadata_cache() -> None:
    """Clear cached capabilities; exposed for deterministic tests and operations."""
    with _cache_lock:
        _metadata_cache.clear()


def get_capabilities(
    url: str = WMTS_CAPABILITIES_URL,
    *,
    now_monotonic: float | None = None,
) -> WmtsCapabilities:
    """Fetch public WMTS metadata with bounded TTL and entry count."""
    now = time.monotonic() if now_monotonic is None else now_monotonic
    with _cache_lock:
        cached = _metadata_cache.get(url)
        if cached and now - cached[0] < METADATA_TTL_SECONDS:
            _metadata_cache.move_to_end(url)
            return cached[1]
        if cached:
            del _metadata_cache[url]

    try:
        response = httpx.get(url, timeout=30.0, follow_redirects=True)
        response.raise_for_status()
        if len(response.content) > MAX_CAPABILITIES_BYTES:
            raise CopernicusMarineError(
                "WMTS capabilities document exceeds the configured size limit."
            )
        capabilities = parse_capabilities(
            response.content,
            retrieved_at_utc=datetime.now(timezone.utc),
        )
    except CopernicusMarineError:
        raise
    except httpx.HTTPStatusError as exc:
        raise CopernicusMarineError(
            f"WMTS capabilities service returned HTTP {exc.response.status_code}."
        ) from exc
    except (httpx.HTTPError, OSError) as exc:
        raise CopernicusMarineError(
            f"WMTS capabilities service could not be reached ({type(exc).__name__})."
        ) from exc

    with _cache_lock:
        _metadata_cache[url] = (now, capabilities)
        _metadata_cache.move_to_end(url)
        while len(_metadata_cache) > METADATA_CACHE_SIZE:
            _metadata_cache.popitem(last=False)
    return capabilities


def _find_layer(capabilities: WmtsCapabilities, spec: LayerSpec) -> WmtsLayer | None:
    candidates = [
        layer
        for layer in capabilities.layers.values()
        if layer.identifier.startswith(f"{spec.product}/")
        and spec.dataset_fragment in layer.identifier
        and layer.identifier.endswith(f"/{spec.variable}")
    ]
    if spec.preferred_dataset_fragment:
        preferred = [
            layer
            for layer in candidates
            if spec.preferred_dataset_fragment in layer.identifier
        ]
        if preferred:
            candidates = preferred
    return sorted(candidates, key=lambda layer: layer.identifier)[-1] if candidates else None


_DURATION = re.compile(
    r"^P(?:(?P<days>\d+)D)?(?:T(?:(?P<hours>\d+)H)?"
    r"(?:(?P<minutes>\d+)M)?(?:(?P<seconds>\d+(?:\.\d+)?)S)?)?$"
)


def _duration(value: str) -> timedelta:
    match = _DURATION.fullmatch(value)
    if not match:
        raise ValueError("Unsupported ISO-8601 WMTS time interval.")
    seconds = (
        float(match.group("days") or 0) * 86400
        + float(match.group("hours") or 0) * 3600
        + float(match.group("minutes") or 0) * 60
        + float(match.group("seconds") or 0)
    )
    if not math.isfinite(seconds) or seconds <= 0:
        raise ValueError("WMTS time interval must be a positive fixed duration.")
    return timedelta(seconds=seconds)


def _axis_times(layer: WmtsLayer) -> list[datetime]:
    values = layer.dimensions.get("time")
    if not values:
        raise ValueError("Layer capabilities do not advertise a time dimension.")
    times: set[datetime] = set()
    for value in values:
        parts = value.split("/")
        if len(parts) == 1:
            times.add(parse_utc_datetime(parts[0], "WMTS time value"))
            continue
        if len(parts) != 3:
            raise ValueError("Malformed WMTS time interval.")
        start = parse_utc_datetime(parts[0], "WMTS time interval start")
        end = parse_utc_datetime(parts[1], "WMTS time interval end")
        step = _duration(parts[2])
        if end < start:
            raise ValueError("WMTS time interval end precedes its start.")
        count = int((end - start) // step) + 1
        if count > _MAX_AXIS_TIMES or len(times) + count > _MAX_AXIS_TIMES:
            raise ValueError("WMTS time axis exceeds the supported resolution limit.")
        current = start
        for _ in range(count):
            times.add(current)
            current += step
    return sorted(times)


def _tile_template(
    capabilities: WmtsCapabilities,
    layer: WmtsLayer,
    style: str,
    source_time: datetime,
) -> tuple[str | None, str | None, str | None, int | None]:
    matrix_id = "EPSG:3857"
    matrix_set = capabilities.tile_matrix_sets.get(matrix_id)
    numeric_matrix_ids = (
        sorted(
            (int(value) for value in matrix_set.matrix_ids if value.isdigit())
        )
        if matrix_set
        else []
    )
    matrix_ids_are_xyz = bool(
        matrix_set
        and matrix_set.matrix_ids == tuple(str(zoom) for zoom in numeric_matrix_ids)
        and numeric_matrix_ids == list(range(len(numeric_matrix_ids)))
    )
    matrix_compatible = bool(
        matrix_set
        and matrix_set.supported_crs.endswith("3857")
        and matrix_set.tile_width == 256
        and matrix_set.tile_height == 256
        and matrix_set.top_left_corner
        and abs(matrix_set.top_left_corner[0] + 20_037_508.3428) < 1
        and abs(matrix_set.top_left_corner[1] - 20_037_508.3428) < 1
        and all(
            matrix_set.matrix_dimensions.get(str(zoom)) == (2**zoom, 2**zoom)
            for zoom in numeric_matrix_ids
        )
        and all(
            (scale := matrix_set.scale_denominators.get(str(zoom))) is not None
            and math.isfinite(scale)
            and math.isclose(
                scale,
                559_082_264.0287178 / (2**zoom),
                rel_tol=1e-9,
                abs_tol=1e-6,
            )
            for zoom in numeric_matrix_ids
        )
    )
    if (
        not capabilities.get_tile_url
        or "KVP" not in capabilities.get_tile_encodings
        or not matrix_set
        or not matrix_set.matrix_ids
        or not matrix_compatible
        or not matrix_ids_are_xyz
        or matrix_id not in layer.tile_matrix_sets
        or "image/png" not in layer.formats
        or style not in layer.styles
        or "time" not in layer.dimensions
    ):
        return None, None, None, None

    time_value = source_time.isoformat(timespec="milliseconds").replace("+00:00", "Z")
    selected_dimensions = _selected_dimensions(layer, source_time)
    extra_dimensions = "".join(
        f"&{quote(name, safe='')}={quote(value, safe='')}"
        for name, value in sorted(selected_dimensions.items())
        if name != "time"
    )
    query = (
        "service=WMTS&request=GetTile&version=1.0.0"
        f"&layer={quote(layer.identifier, safe='/')}"
        f"&style={quote(style, safe='')}&format=image%2Fpng"
        "&tilematrixset=EPSG%3A3857&tilematrix={z}&tilerow={y}&tilecol={x}"
        f"&time={quote(time_value, safe='')}{extra_dimensions}"
    )
    max_zoom = max(numeric_matrix_ids, default=None)
    return (
        f"{capabilities.get_tile_url}?{query}",
        matrix_set.supported_crs,
        matrix_id,
        max_zoom,
    )


def _selected_dimensions(layer: WmtsLayer, source_time: datetime) -> dict[str, str]:
    return {
        "time": source_time.isoformat().replace("+00:00", "Z"),
        **{
            name: value
            for name, value in layer.dimension_defaults.items()
            if name != "time"
        },
    }


def _status_quality_reference(
    capabilities: WmtsCapabilities,
    observation: WmtsLayer,
    source_time: datetime,
) -> tuple[dict[str, object] | None, str | None]:
    dataset = observation.identifier.rsplit("/", 1)[0]
    quality = capabilities.layers.get(f"{dataset}/status_flag")
    if quality is None:
        return None, "The paired dataset does not advertise its status_flag quality layer."
    if (
        "image/png" not in quality.formats
        or "EPSG:3857" not in quality.tile_matrix_sets
        or "EPSG:3857" not in observation.tile_matrix_sets
        or "cmap:rainbow" not in quality.styles
        or observation.wgs84_bounds is None
        or quality.wgs84_bounds != observation.wgs84_bounds
    ):
        return None, "The status_flag layer lacks matching PNG, style, matrix, or coverage metadata."
    try:
        quality_times = _axis_times(quality)
    except (ValueError, OverflowError):
        return None, "The status_flag layer has an unsupported time dimension."
    if source_time not in quality_times:
        return None, "The status_flag layer does not advertise the paired observation valid time."
    tile, crs, matrix_set, max_zoom = _tile_template(
        capabilities,
        quality,
        "cmap:rainbow",
        source_time,
    )
    if tile is None or matrix_set != "EPSG:3857" or crs is None:
        return None, "The status_flag layer does not provide a compatible EPSG:3857 PNG tile matrix."
    return (
        {
            "render_quality_layer": quality.identifier,
            "render_quality_style": "cmap:rainbow",
            "render_quality_valid_time_utc": source_time,
            "render_quality_tile_matrix_set": matrix_set,
            "render_quality_tile_max_zoom": max_zoom,
            "render_quality_tile_template": tile,
            "render_quality_tile_dimensions": _selected_dimensions(quality, source_time),
        },
        None,
    )


def _base_result(spec: LayerSpec, target: datetime) -> dict:
    return {
        "key": spec.key,
        "status": "unavailable",
        "target_time_utc": target,
        "source_valid_time_utc": None,
        "observation_time_utc": None,
        "retrieved_at_utc": None,
        "forecast_lead_hours": None,
        "age_hours": None,
        "offset_hours": None,
        "classification": "observation" if spec.temporal_kind == "observation" else None,
        "product": spec.product,
        "dataset": None,
        "layer": None,
        "variable": spec.variable,
        "units": None,
        "standard_name": None,
        "data_updated_at_utc": None,
        "metadata_updated_at_utc": None,
        "product_released_at_utc": None,
        "source_crs": None,
        "tile_matrix_set": None,
        "style": None,
        "tile_max_zoom": None,
        "tile_template": None,
        "render_quality_layer": None,
        "render_quality_style": None,
        "render_quality_valid_time_utc": None,
        "render_quality_tile_matrix_set": None,
        "render_quality_tile_max_zoom": None,
        "render_quality_tile_template": None,
        "render_quality_tile_dimensions": {},
        "render_quality_reason": None,
        "coverage_bounds_wgs84": None,
        "coverage_bounds_reason": None,
        "tile_dimensions": {},
        "attribution": WMTS_ATTRIBUTION,
        "provenance": (
            "Copernicus Marine WMTS GetCapabilities; source valid times and tile metadata "
            "are read from the current service response."
        ),
        "reason": None,
    }


def _candidate_result(
    capabilities: WmtsCapabilities,
    spec: LayerSpec,
    layer: WmtsLayer | None,
    target: datetime,
    now: datetime,
    excluded_source_times: set[datetime] | None = None,
) -> tuple[dict, list[datetime]]:
    result = _base_result(spec, target)
    if layer is None:
        result["reason"] = "No matching product, dataset, and variable layer is advertised by WMTS."
        return result, []

    result.update(
        dataset=layer.identifier.split("/")[-2],
        layer=layer.identifier,
        coverage_bounds_wgs84=(
            {
                "west": layer.wgs84_bounds[0],
                "south": layer.wgs84_bounds[1],
                "east": layer.wgs84_bounds[2],
                "north": layer.wgs84_bounds[3],
            }
            if layer.wgs84_bounds
            else None
        ),
        coverage_bounds_reason=layer.wgs84_bounds_reason,
        units=layer.units,
        standard_name=layer.standard_name,
        data_updated_at_utc=layer.data_updated_at_utc,
        metadata_updated_at_utc=layer.metadata_updated_at_utc,
        product_released_at_utc=layer.released_at_utc,
        retrieved_at_utc=capabilities.retrieved_at_utc,
    )
    times: list[datetime]
    try:
        times = _axis_times(layer)
    except (ValueError, OverflowError):
        result.update(
            status="unsupported_time",
            reason="The layer time dimension is missing or uses an unsupported representation.",
        )
        return result, []

    if spec.temporal_kind == "observation" and target > now:
        result.update(
            status="unsupported_time",
            reason="Satellite observations cannot be used as a future forecast.",
        )
        return result, times
    if target < times[0]:
        result.update(
            status="outside_coverage",
            reason="Requested time precedes the valid-time coverage advertised by this layer.",
        )
        return result, times
    if target > times[-1] and target > now:
        result.update(
            status=(
                "unsupported_time"
                if spec.temporal_kind == "observation" and target > now
                else "outside_coverage"
            ),
            reason="Requested time is later than the valid-time coverage advertised by this layer.",
        )
        return result, times

    excluded = excluded_source_times or set()
    eligible = [value for value in times if value <= target and value not in excluded]
    if not eligible:
        if excluded and any(value <= target for value in times):
            result.update(
                status="unavailable",
                reason="All advertised source times failed their renderer availability checks.",
            )
            return result, times
        result.update(
            status="outside_coverage",
            reason="No valid source time is available at or before the requested time.",
        )
        return result, times
    source_time = eligible[-1]
    if (
        spec.temporal_kind == "analysis_forecast"
        and target > now
        and source_time <= now
    ):
        result.update(
            status="unsupported_time",
            reason=(
                "No advertised forecast valid time is available at or before the target; "
                "the latest eligible timestamp is analysis, not a future forecast."
            ),
        )
        return result, times
    offset_hours = (source_time - target).total_seconds() / 3600
    age_hours = max(0.0, -offset_hours)
    is_forecast = (
        spec.temporal_kind == "analysis_forecast"
        and source_time > now
    )
    style = next((value for value in layer.styles if value == "cmap:ice"), None)
    if style is None and layer.styles:
        style = layer.styles[0]
    tile, crs, matrix_set, max_zoom = _tile_template(
        capabilities, layer, style or "", source_time
    )
    result.update(
        status="stale" if age_hours > spec.max_offset_hours else "ready",
        source_valid_time_utc=source_time,
        observation_time_utc=source_time if spec.temporal_kind == "observation" else None,
        age_hours=round(age_hours, 3),
        offset_hours=round(offset_hours, 3),
        classification=(
            "observation"
            if spec.temporal_kind == "observation"
            else "forecast" if is_forecast else "analysis"
        ),
        source_crs=crs,
        tile_matrix_set=matrix_set,
        style=style,
        tile_max_zoom=max_zoom,
        tile_template=tile,
        tile_dimensions=_selected_dimensions(layer, source_time),
        reason=(
            f"Source valid time is {age_hours:.1f} hours before the target; "
            f"maximum accepted offset is {spec.max_offset_hours:.1f} hours."
            if age_hours > spec.max_offset_hours
            else None
        ),
    )
    if spec.temporal_kind == "analysis_forecast" and is_forecast:
        result["reason"] = (
            "Valid time is in the future and classified as forecast; the WMTS capabilities "
            "do not expose a forecast initialization time, so forecast lead is not asserted."
        )
    if tile is None:
        result["reason"] = (
            result["reason"]
            or "Layer lacks a verified public KVP tile template in EPSG:3857 with PNG format."
        )
    return result, times


def _resolve_pair(
    capabilities: WmtsCapabilities,
    specs: list[LayerSpec],
    layers: dict[str, dict],
    time_axes: dict[str, list[datetime]],
    target: datetime,
    now: datetime,
) -> None:
    keys = [spec.key for spec in specs]
    if any(layers[key]["status"] == "unsupported_time" for key in keys):
        for key in keys:
            if layers[key]["status"] != "unavailable":
                layers[key].update(
                    status="unsupported_time",
                    source_valid_time_utc=None,
                    tile_template=None,
                    reason=(
                        "A paired component has no supported valid time for this target; "
                        "the pair is withheld rather than mixing timestamps."
                    ),
                )
        return
    if any(not time_axes.get(key) for key in keys):
        for key in keys:
            if layers[key]["status"] == "unavailable":
                continue
            layers[key].update(
                status="unavailable",
                source_valid_time_utc=None,
                tile_template=None,
                reason="The paired environmental component is unavailable; valid times cannot be matched.",
            )
        return

    common_times = set(time_axes[keys[0]])
    for key in keys[1:]:
        common_times.intersection_update(time_axes[key])
    eligible = sorted(value for value in common_times if value <= target)
    if not eligible:
        before_coverage = bool(common_times) and target < min(common_times)
        for key in keys:
            layers[key].update(
                status="outside_coverage" if before_coverage else "stale",
                source_valid_time_utc=None,
                tile_template=None,
                reason=(
                    "Target precedes the paired layers' shared valid-time coverage."
                    if before_coverage
                    else "Paired components do not advertise a common valid time at or before the target."
                ),
            )
        return

    source_time = eligible[-1]
    if (
        target > now
        and any(spec.temporal_kind == "analysis_forecast" for spec in specs)
        and source_time <= now
    ):
        for key in keys:
            layers[key].update(
                status="unsupported_time",
                source_valid_time_utc=None,
                tile_template=None,
                reason=(
                    "The components share only an analysis timestamp, not a future "
                    "forecast valid time; the pair is withheld."
                ),
            )
        return

    for spec in specs:
        layer = _find_layer(capabilities, spec)
        result = layers[spec.key]
        if layer is None:
            continue
        age_hours = max(0.0, (target - source_time).total_seconds() / 3600)
        style = result["style"] or (layer.styles[0] if layer.styles else "")
        tile, crs, matrix_set, max_zoom = _tile_template(
            capabilities, layer, style, source_time
        )
        result.update(
            status="stale" if age_hours > spec.max_offset_hours else "ready",
            source_valid_time_utc=source_time,
            observation_time_utc=(
                source_time if spec.temporal_kind == "observation" else None
            ),
            age_hours=round(age_hours, 3),
            offset_hours=round(-age_hours, 3),
            classification=(
                "observation"
                if spec.temporal_kind == "observation"
                else "forecast" if source_time > now else "analysis"
            ),
            style=style or None,
            source_crs=crs,
            tile_matrix_set=matrix_set,
            tile_max_zoom=max_zoom,
            tile_template=tile,
            tile_dimensions=_selected_dimensions(layer, source_time),
            reason=(
                "Paired layers use the same advertised valid time."
                if age_hours <= spec.max_offset_hours
                else f"Matched pair is {age_hours:.1f} hours old; exceeds the "
                f"{spec.max_offset_hours:.1f}-hour freshness limit."
            ),
        )
        if tile is None:
            result["reason"] = (
                "Paired valid time resolved, but this layer has no verified public "
                "EPSG:3857 PNG KVP tile template."
            )


def resolve_environment_layers(
    target_time_utc: datetime,
    *,
    now: datetime | None = None,
    capabilities: WmtsCapabilities | None = None,
    excluded_source_times: Mapping[str, set[datetime]] | None = None,
) -> dict[str, dict]:
    """Resolve configured source layers against one timezone-aware UTC target."""
    target = parse_utc_datetime(target_time_utc, "target_time_utc")
    current = parse_utc_datetime(now or datetime.now(timezone.utc), "now")
    try:
        metadata = capabilities or get_capabilities()
    except CopernicusMarineError as exc:
        error = str(exc)
        return {
            spec.key: _base_result(spec, target)
            | {"status": "error", "reason": error}
            for spec in LAYER_SPECS
        }

    results: dict[str, dict] = {}
    time_axes: dict[str, list[datetime]] = {}
    for spec in LAYER_SPECS:
        source_layer = _find_layer(metadata, spec)
        result, available_times = _candidate_result(
            metadata,
            spec,
            source_layer,
            target,
            current,
            (excluded_source_times or {}).get(spec.key),
        )
        results[spec.key] = result
        time_axes[spec.key] = available_times

    for pair_name in {spec.pair for spec in LAYER_SPECS if spec.pair}:
        pair_specs = [spec for spec in LAYER_SPECS if spec.pair == pair_name]
        _resolve_pair(metadata, pair_specs, results, time_axes, target, current)
    for key in ("sea_ice_edge", "sea_ice_concentration"):
        observation = results[key]
        layer_id = observation.get("layer")
        source_time = observation.get("source_valid_time_utc")
        if (
            isinstance(layer_id, str)
            and isinstance(source_time, datetime)
            and observation.get("status") in {"ready", "stale"}
        ):
            source_layer = metadata.layers.get(layer_id)
            if source_layer is not None:
                quality_reference, quality_reason = _status_quality_reference(
                    metadata,
                    source_layer,
                    source_time,
                )
                if quality_reference:
                    observation.update(quality_reference)
                observation["render_quality_reason"] = quality_reason
    return results


def discover_layers(capabilities: WmtsCapabilities | None = None) -> list[dict[str, object]]:
    """Return the current discovered WMTS catalogue without service credentials."""
    metadata = capabilities or get_capabilities()
    return [
        {
            "identifier": layer.identifier,
            "title": layer.title,
            "formats": list(layer.formats),
            "styles": list(layer.styles),
            "tile_matrix_sets": list(layer.tile_matrix_sets),
            "coordinate_reference_systems": [
                metadata.tile_matrix_sets[matrix_id].supported_crs
                for matrix_id in layer.tile_matrix_sets
                if matrix_id in metadata.tile_matrix_sets
            ],
            "units": layer.units,
            "standard_name": layer.standard_name,
            "data_updated_at_utc": layer.data_updated_at_utc,
            "metadata_updated_at_utc": layer.metadata_updated_at_utc,
            "product_released_at_utc": layer.released_at_utc,
            "dimension_defaults": dict(layer.dimension_defaults),
            "dimensions": {key: list(values) for key, values in layer.dimensions.items()},
        }
        for layer in metadata.layers.values()
    ]
