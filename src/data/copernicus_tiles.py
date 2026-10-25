"""Small, cached WMTS tile adapters for transparent sea-ice overlays."""
from __future__ import annotations

import io
import json
import math
import threading
import time
from collections import OrderedDict
from datetime import datetime
from urllib.parse import parse_qs, urlencode, urlsplit

import httpx
from PIL import Image, UnidentifiedImageError

from ..core.environment_time import EnvironmentTimeError, parse_utc_datetime

EDGE_CLASS_COLORS = {
    (33, 145, 140): (45, 212, 191, 255),  # open ice (class 2)
    (253, 231, 37): (250, 204, 21, 255),  # close/very close/fast ice (class 3)
}
MAX_TILE_BYTES = 2 * 1024 * 1024
MAX_LEGEND_BYTES = 1024 * 1024
TILE_CACHE_TTL_SECONDS = 15 * 60
TILE_CACHE_SIZE = 256
LEGEND_CACHE_TTL_SECONDS = 30 * 60
LEGEND_CACHE_SIZE = 8
RENDER_PROBE_CACHE_TTL_SECONDS = 5 * 60
RENDER_PROBE_CACHE_SIZE = 64
_tile_cache: OrderedDict[str, tuple[float, bytes]] = OrderedDict()
_legend_cache: OrderedDict[str, tuple[float, tuple[int, int, int]]] = OrderedDict()
_render_probe_cache: OrderedDict[tuple[str, str, str], tuple[float, str | None]] = OrderedDict()
_cache_lock = threading.Lock()


class CopernicusTileError(RuntimeError):
    """Raised when an official Copernicus tile cannot safely be rendered."""


def clear_tile_cache() -> None:
    with _cache_lock:
        _tile_cache.clear()
        _legend_cache.clear()
        _render_probe_cache.clear()


def _fetch_tile(url: str) -> bytes:
    parsed = urlsplit(url)
    if (
        parsed.scheme != "https"
        or parsed.hostname != "wmts.marine.copernicus.eu"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise CopernicusTileError("The WMTS tile URL is not from the verified public Copernicus service.")

    now = time.monotonic()
    with _cache_lock:
        cached = _tile_cache.get(url)
        if cached and now - cached[0] < TILE_CACHE_TTL_SECONDS:
            _tile_cache.move_to_end(url)
            return cached[1]
        if cached:
            del _tile_cache[url]

    try:
        response = httpx.get(url, timeout=20.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise CopernicusTileError(f"Copernicus WMTS tile request failed ({type(exc).__name__}).") from exc
    if response.status_code != 200:
        raise CopernicusTileError(f"Copernicus WMTS GetTile returned HTTP {response.status_code}.")
    if not response.headers.get("content-type", "").lower().startswith("image/png"):
        raise CopernicusTileError("Copernicus WMTS GetTile did not return a PNG image.")
    if len(response.content) > MAX_TILE_BYTES:
        raise CopernicusTileError("Copernicus WMTS tile exceeded the configured size limit.")

    with _cache_lock:
        _tile_cache[url] = (now, response.content)
        _tile_cache.move_to_end(url)
        while len(_tile_cache) > TILE_CACHE_SIZE:
            _tile_cache.popitem(last=False)
    return response.content


def _tile_image(content: bytes) -> Image.Image:
    try:
        with Image.open(io.BytesIO(content)) as image:
            if image.format != "PNG" or image.size != (256, 256):
                raise CopernicusTileError("Copernicus WMTS tile dimensions or image format are unsupported.")
            return image.convert("RGBA")
    except UnidentifiedImageError as exc:
        raise CopernicusTileError("Copernicus WMTS tile is not a decodable PNG image.") from exc


def _template_has_source_time(template: str, source_time: object) -> bool:
    values = parse_qs(urlsplit(template).query).get("time")
    if (
        not values
        or len(values) != 1
        or not isinstance(source_time, (str, datetime))
    ):
        return False
    try:
        return parse_utc_datetime(values[0], "WMTS time") == parse_utc_datetime(
            source_time,
            "source valid time",
        )
    except (EnvironmentTimeError, TypeError):
        return False


def _same_source_time(first: object, second: object) -> bool:
    if not isinstance(first, (str, datetime)) or not isinstance(second, (str, datetime)):
        return False
    try:
        return parse_utc_datetime(first) == parse_utc_datetime(second)
    except EnvironmentTimeError:
        return False


def _valid_quality_flag_color(tile_template: str) -> tuple[int, int, int]:
    parsed = urlsplit(tile_template)
    query = parse_qs(parsed.query)
    layer = query.get("layer", [None])[0]
    style = query.get("style", [None])[0]
    if (
        parsed.scheme != "https"
        or parsed.hostname != "wmts.marine.copernicus.eu"
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
        or not isinstance(layer, str)
        or not layer.endswith("/status_flag")
        or style != "cmap:rainbow"
    ):
        raise CopernicusTileError("The paired status_flag legend is not from the verified public WMTS style.")

    cache_key = f"{parsed.scheme}://{parsed.netloc}{parsed.path}?{layer}|{style}"
    now = time.monotonic()
    with _cache_lock:
        cached = _legend_cache.get(cache_key)
        if cached and now - cached[0] < LEGEND_CACHE_TTL_SECONDS:
            _legend_cache.move_to_end(cache_key)
            return cached[1]
        if cached:
            del _legend_cache[cache_key]

    legend_url = f"{parsed.scheme}://{parsed.netloc}{parsed.path}"
    params = {
        "SERVICE": "WMTS",
        "REQUEST": "GetLegend",
        "LAYER": layer,
        "STYLE": style,
        "FORMAT": "application/json",
    }
    try:
        response = httpx.get(legend_url, params=params, timeout=20.0, follow_redirects=False)
    except httpx.HTTPError as exc:
        raise CopernicusTileError(
            f"Copernicus status_flag legend request failed ({type(exc).__name__})."
        ) from exc
    if response.status_code != 200:
        raise CopernicusTileError(
            f"Copernicus status_flag legend returned HTTP {response.status_code}."
        )
    if not response.headers.get("content-type", "").lower().startswith("application/json"):
        raise CopernicusTileError("Copernicus status_flag legend did not return JSON.")
    if len(response.content) > MAX_LEGEND_BYTES:
        raise CopernicusTileError("Copernicus status_flag legend exceeded the configured size limit.")
    try:
        legend = response.json()
        continuous = legend["continuous"]
        color_map = continuous["cmap"]["colorMap"]
        minimum = float(continuous["valueMin"])
        rgb_values = color_map[0]
        color = tuple(int(value) for value in rgb_values)
    except (KeyError, IndexError, TypeError, ValueError, json.JSONDecodeError) as exc:
        raise CopernicusTileError("Copernicus status_flag legend is malformed.") from exc
    if minimum != 0 or len(color) != 3 or any(not 0 <= value <= 255 for value in color):
        raise CopernicusTileError("Copernicus status_flag legend does not define a valid zero-value color.")

    with _cache_lock:
        _legend_cache[cache_key] = (now, color)
        _legend_cache.move_to_end(cache_key)
        while len(_legend_cache) > LEGEND_CACHE_SIZE:
            _legend_cache.popitem(last=False)
    return color


def _encode_png(image: Image.Image) -> bytes:
    output = io.BytesIO()
    image.save(output, format="PNG", optimize=False)
    return output.getvalue()


def _tile_bounds_wgs84(z: int, x: int, y: int) -> tuple[float, float, float, float]:
    matrix_size = 2**z
    west = x / matrix_size * 360 - 180
    east = (x + 1) / matrix_size * 360 - 180

    def latitude(tile_y: int) -> float:
        mercator_y = math.pi * (1 - 2 * tile_y / matrix_size)
        return math.degrees(math.atan(math.sinh(mercator_y)))

    north = latitude(y)
    south = latitude(y + 1)
    return west, south, east, north


def _tile_intersects_coverage(
    z: int,
    x: int,
    y: int,
    coverage: object,
) -> bool:
    if not isinstance(coverage, dict):
        raise CopernicusTileError("The layer has no advertised WGS84 coverage bounds.")
    try:
        west, south, east, north = (
            float(coverage[key]) for key in ("west", "south", "east", "north")
        )
    except (KeyError, TypeError, ValueError) as exc:
        raise CopernicusTileError("The layer's WGS84 coverage bounds are malformed.") from exc
    if (
        not all(math.isfinite(value) for value in (west, south, east, north))
        or not (-180 <= west < east <= 180)
        or not (-90 <= south < north <= 90)
    ):
        raise CopernicusTileError("The layer's WGS84 coverage bounds are invalid.")
    tile_west, tile_south, tile_east, tile_north = _tile_bounds_wgs84(z, x, y)
    return (
        tile_east >= west
        and tile_west <= east
        and tile_north >= south
        and tile_south <= north
    )


def _edge_outline(image: Image.Image) -> Image.Image:
    source = image.load()
    result = Image.new("RGBA", image.size, (0, 0, 0, 0))
    pixels = result.load()
    for y in range(image.height):
        for x in range(image.width):
            red, green, blue, alpha = source[x, y]
            if alpha:
                pixels[x, y] = EDGE_CLASS_COLORS.get((red, green, blue), (0, 0, 0, 0))
    return result


def render_sea_ice_tile(
    layer: dict[str, object],
    mode: str,
    z: int,
    x: int,
    y: int,
) -> bytes:
    """Render official Copernicus sea-ice imagery with its source-time selection."""
    if not (0 <= z <= 10 and 0 <= x < 2**z and 0 <= y < 2**z):
        raise CopernicusTileError("Tile coordinates are outside the verified EPSG:3857 matrix.")
    if not _tile_intersects_coverage(z, x, y, layer.get("coverage_bounds_wgs84")):
        return _encode_png(Image.new("RGBA", (256, 256), (0, 0, 0, 0)))

    if layer.get("tile_matrix_set") != "EPSG:3857":
        raise CopernicusTileError("Copernicus tile matrix is not the verified EPSG:3857 matrix.")
    tile_template = layer.get("tile_template")
    if not isinstance(tile_template, str):
        raise CopernicusTileError("Copernicus did not advertise a usable tile template.")
    source_time = layer.get("source_valid_time_utc")
    if not _template_has_source_time(tile_template, source_time):
        raise CopernicusTileError("The WMTS template does not select its resolved source time.")
    max_zoom = layer.get("tile_max_zoom")
    if isinstance(max_zoom, int) and z > max_zoom:
        raise CopernicusTileError("Tile zoom is outside the advertised layer coverage.")
    tile_url = (
        tile_template
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
    )
    if mode == "edge":
        if layer.get("style") != "cmap:viridis":
            raise CopernicusTileError("The advertised Copernicus edge style is not supported.")
        quality_template = layer.get("render_quality_tile_template")
        if (
            not isinstance(quality_template, str)
            or layer.get("render_quality_tile_matrix_set") != "EPSG:3857"
            or layer.get("render_quality_style") != "cmap:rainbow"
            or not _template_has_source_time(quality_template, source_time)
            or not _same_source_time(layer.get("render_quality_valid_time_utc"), source_time)
        ):
            raise CopernicusTileError("The paired status_flag tile does not match the edge valid time.")
        quality_max_zoom = layer.get("render_quality_tile_max_zoom")
        if isinstance(quality_max_zoom, int) and z > quality_max_zoom:
            raise CopernicusTileError("Tile zoom is outside the advertised status_flag coverage.")
        valid_flag_color = _valid_quality_flag_color(quality_template)
        quality_url = quality_template.replace("{z}", str(z)).replace("{x}", str(x)).replace("{y}", str(y))
        source = _tile_image(_fetch_tile(tile_url))
        quality = _tile_image(_fetch_tile(quality_url))
        if quality.size != source.size:
            raise CopernicusTileError("Edge and status_flag tile dimensions do not match.")
        rendered = _edge_outline(source)
        rendered_pixels = rendered.load()
        quality_pixels = quality.load()
        for pixel_y in range(source.height):
            for pixel_x in range(source.width):
                flag = quality_pixels[pixel_x, pixel_y]
                if flag[3] == 0 or flag[:3] != valid_flag_color:
                    rendered_pixels[pixel_x, pixel_y] = (0, 0, 0, 0)
        return _encode_png(rendered)
    if mode != "concentration":
        raise CopernicusTileError("The requested Copernicus sea-ice renderer is unsupported.")

    if layer.get("style") != "cmap:ice" or layer.get("units") != "%":
        raise CopernicusTileError("The advertised Copernicus concentration style or units are unsupported.")
    quality_template = layer.get("render_quality_tile_template")
    if not isinstance(quality_template, str):
        raise CopernicusTileError(
            str(layer.get("render_quality_reason") or "No compatible paired status_flag renderer is available.")
        )
    if (
        layer.get("render_quality_tile_matrix_set") != "EPSG:3857"
        or layer.get("render_quality_style") != "cmap:rainbow"
        or not _template_has_source_time(quality_template, source_time)
        or not _same_source_time(
            layer.get("render_quality_valid_time_utc"),
            source_time,
        )
    ):
        raise CopernicusTileError("The paired status_flag tile does not match the concentration matrix or valid time.")
    quality_max_zoom = layer.get("render_quality_tile_max_zoom")
    if isinstance(quality_max_zoom, int) and z > quality_max_zoom:
        raise CopernicusTileError("Tile zoom is outside the advertised status_flag coverage.")
    valid_flag_color = _valid_quality_flag_color(quality_template)
    quality_url = (
        quality_template
        .replace("{z}", str(z))
        .replace("{x}", str(x))
        .replace("{y}", str(y))
    )
    source = _tile_image(_fetch_tile(tile_url))
    quality = _tile_image(_fetch_tile(quality_url))
    if quality.size != source.size:
        raise CopernicusTileError("Concentration and status_flag tile dimensions do not match.")

    concentration_pixels = source.load()
    quality_pixels = quality.load()
    for pixel_y in range(source.height):
        for pixel_x in range(source.width):
            flag = quality_pixels[pixel_x, pixel_y]
            if flag[3] == 0 or flag[:3] != valid_flag_color:
                concentration_pixels[pixel_x, pixel_y] = (0, 0, 0, 0)
    return _encode_png(source)


def probe_edge_tile_renderer(layer: dict[str, object]) -> str | None:
    """Return a cached WMTS failure reason if the selected edge renderer cannot serve a tile."""
    layer_id = layer.get("layer")
    source_time = layer.get("source_valid_time_utc")
    template = layer.get("tile_template")
    if (
        not isinstance(layer_id, str)
        or not layer_id
        or not isinstance(source_time, (str, datetime))
        or not isinstance(template, str)
        or not template
    ):
        return "The edge source is missing its layer, valid time, or WMTS tile template."
    cache_key = (layer_id, str(source_time), template)
    now = time.monotonic()
    with _cache_lock:
        cached = _render_probe_cache.get(cache_key)
        if cached and now - cached[0] < RENDER_PROBE_CACHE_TTL_SECONDS:
            _render_probe_cache.move_to_end(cache_key)
            return cached[1]
        if cached:
            del _render_probe_cache[cache_key]

    try:
        render_sea_ice_tile(layer, "edge", 3, 2, 6)
    except CopernicusTileError as exc:
        reason: str | None = str(exc)
    else:
        reason = None

    with _cache_lock:
        _render_probe_cache[cache_key] = (now, reason)
        _render_probe_cache.move_to_end(cache_key)
        while len(_render_probe_cache) > RENDER_PROBE_CACHE_SIZE:
            _render_probe_cache.popitem(last=False)
    return reason
