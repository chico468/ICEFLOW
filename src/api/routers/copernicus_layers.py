"""Time-aware metadata and public tile references for Copernicus Marine layers."""
from __future__ import annotations

import json
import os
import re
from collections.abc import Mapping
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Literal
from urllib.parse import quote

from fastapi import APIRouter, HTTPException, Query, Request, Response
from fastapi import Path as FastAPIPath
from pydantic import BaseModel, Field

from src.core.environment_time import (
    EnvironmentTimeError,
    EnvironmentTimeResolution,
    parse_utc_datetime,
    resolve_active_voyage_time,
    resolve_planning_time,
)
from src.data import copernicus_tiles
from src.data.copernicus_marine import resolve_environment_layers
from src.data.nsidc_sea_ice import _FILENAME_RE_V6, default_cache_dir

router = APIRouter(prefix="/api/v1/environment", tags=["Copernicus Marine layers"])


class EnvironmentLayerMetadata(BaseModel):
    key: str
    status: Literal[
        "ready",
        "stale",
        "unavailable",
        "outside_coverage",
        "unsupported_time",
        "error",
    ]
    target_time_utc: datetime
    source_valid_time_utc: datetime | None = None
    source_valid_interval_start_utc: datetime | None = None
    source_valid_interval_end_utc: datetime | None = None
    observation_time_utc: datetime | None = None
    retrieved_at_utc: datetime | None = None
    classification: Literal["observation", "analysis", "forecast"] | None = None
    forecast_lead_hours: float | None = None
    age_hours: float | None = None
    offset_hours: float | None = None
    product: str
    dataset: str | None = None
    layer: str | None = None
    variable: str
    units: str | None = None
    standard_name: str | None = None
    data_updated_at_utc: datetime | None = None
    metadata_updated_at_utc: datetime | None = None
    product_released_at_utc: datetime | None = None
    source_crs: str | None = None
    tile_matrix_set: str | None = None
    coverage_bounds_wgs84: dict[str, float] | None = None
    coverage_bounds_reason: str | None = None
    style: str | None = None
    tile_max_zoom: int | None = None
    tile_template: str | None = None
    render_quality_layer: str | None = None
    render_quality_style: str | None = None
    render_quality_valid_time_utc: datetime | None = None
    render_quality_tile_matrix_set: str | None = None
    render_quality_tile_max_zoom: int | None = None
    render_quality_tile_template: str | None = None
    render_quality_tile_dimensions: dict[str, str] = Field(default_factory=dict)
    render_quality_reason: str | None = None
    render_tile_template: str | None = None
    render_status: Literal["ready", "unavailable"] | None = None
    render_reason: str | None = None
    tile_dimensions: dict[str, str] = Field(default_factory=dict)
    attribution: str
    provenance: str
    reason: str | None = None


class EnvironmentLayersResponse(BaseModel):
    target_time_utc: datetime
    mode: Literal["active_voyage", "planning_forecast"]
    time_resolution: EnvironmentTimeResolution
    layers: dict[str, EnvironmentLayerMetadata]


def _resolve_layers_with_renderable_edge(target: datetime) -> dict[str, dict]:
    excluded_times: set[datetime] = set()
    failed_times: list[tuple[datetime, str]] = []
    last_failure: str | None = None
    for _ in range(8):
        layers = (
            resolve_environment_layers(
                target,
                excluded_source_times={"sea_ice_edge": excluded_times},
            )
            if excluded_times
            else resolve_environment_layers(target)
        )
        edge = layers.get("sea_ice_edge", {})
        if (
            edge.get("status") not in {"ready", "stale"}
            or not edge.get("tile_template")
            or edge.get("tile_matrix_set") != "EPSG:3857"
            or edge.get("style") != "cmap:viridis"
            or not edge.get("render_quality_tile_template")
            or edge.get("render_quality_style") != "cmap:rainbow"
            or not _reported_time_matches_tile_dimension(edge)
            or not _times_match(
                edge.get("source_valid_time_utc"),
                edge.get("render_quality_valid_time_utc"),
            )
        ):
            if failed_times:
                edge["_render_probe_error"] = (
                    "No renderable Copernicus edge observation was found after the newest "
                    f"advertised time failed a WMTS tile check. Last WMTS error: "
                    f"{failed_times[-1][1]}"
                )
            return layers

        last_failure = copernicus_tiles.probe_edge_tile_renderer(edge)
        if last_failure is None:
            if failed_times:
                failed = ", ".join(
                    f"{value.isoformat().replace('+00:00', 'Z')} ({reason})"
                    for value, reason in failed_times
                )
                edge["reason"] = (
                    f"The newer advertised edge observation(s) at {failed} failed a live "
                    "WMTS tile check; "
                    "showing the newest observation that rendered successfully."
                )
            return layers

        source_time = edge.get("source_valid_time_utc")
        if not isinstance(source_time, (datetime, str)):
            edge["_render_probe_error"] = last_failure
            return layers
        try:
            parsed_source_time = parse_utc_datetime(source_time, "source valid time")
        except EnvironmentTimeError:
            edge["_render_probe_error"] = last_failure
            return layers
        if parsed_source_time in excluded_times:
            edge["_render_probe_error"] = last_failure
            return layers
        excluded_times.add(parsed_source_time)
        failed_times.append((parsed_source_time, last_failure))

    edge = layers.get("sea_ice_edge", {})
    edge["_render_probe_error"] = (
        "No renderable Copernicus edge observation was found among the latest "
        f"{len(failed_times)} advertised times. Last WMTS error: "
        f"{failed_times[-1][1] if failed_times else last_failure}"
    )
    return layers


def _render_tile_template(
    request: Request,
    mode: str,
    target: datetime,
    source_time: datetime,
) -> str:
    sample_url = str(
        request.url_for(
            "copernicus_sea_ice_tile",
            mode=mode,
            z=0,
            x=0,
            y=0,
        )
    )
    tile_path = sample_url.rsplit("/0/0/0.png", 1)[0] + "/{z}/{x}/{y}.png"
    target_parameter = quote(target.isoformat().replace("+00:00", "Z"), safe="")
    source_parameter = quote(source_time.isoformat().replace("+00:00", "Z"), safe="")
    return (
        f"{tile_path}?target_time_utc={target_parameter}"
        f"&source_valid_time_utc={source_parameter}"
    )


def _reported_time_matches_tile_dimension(layer: Mapping[str, object]) -> bool:
    source_time = layer.get("source_valid_time_utc")
    dimensions = layer.get("tile_dimensions")
    tile_time = dimensions.get("time") if isinstance(dimensions, dict) else None
    if not isinstance(source_time, (datetime, str)) or not isinstance(tile_time, str):
        return False
    try:
        return parse_utc_datetime(source_time) == parse_utc_datetime(tile_time, "WMTS time")
    except EnvironmentTimeError:
        return False


def _times_match(first: object, second: object) -> bool:
    if not isinstance(first, (datetime, str)) or not isinstance(second, (datetime, str)):
        return False
    try:
        return parse_utc_datetime(first) == parse_utc_datetime(second, "WMTS time")
    except EnvironmentTimeError:
        return False


@router.get("/layers", response_model=EnvironmentLayersResponse)
def environment_layers(
    request: Request,
    target_time_utc: str = Query(..., description="Resolved environmental target time in UTC."),
    mode: Literal["active_voyage", "planning_forecast"] = Query(...),
    departure_iso: str | None = Query(
        default=None,
        description="Required in active-voyage mode; voyage start with timezone.",
    ),
    sim_hours: float | None = Query(
        default=None,
        ge=0,
        description="Required in active-voyage mode; elapsed voyage hours.",
    ),
    timestamp_iso: str | None = Query(
        default=None,
        description="Optional WebSocket tick timestamp checked against departure plus sim_hours.",
    ),
    planning_reference_iso: str | None = Query(
        default=None,
        description="Required in planning mode; timezone-aware forecast reference.",
    ),
    lead_hours: float = Query(default=0.0, ge=0),
    departure_time_hours: float = Query(
        default=0.0,
        ge=0,
        description="Model-relative offset; not interpreted as a UTC timestamp.",
    ),
) -> EnvironmentLayersResponse:
    """Resolve Copernicus layer times against the shared Phase 1 UTC time contract."""
    try:
        requested_target = parse_utc_datetime(target_time_utc, "target_time_utc")
        if mode == "active_voyage":
            if departure_iso is None or sim_hours is None:
                raise HTTPException(
                    status_code=422,
                    detail="active_voyage mode requires departure_iso and sim_hours.",
                )
            resolution = resolve_active_voyage_time(
                departure_iso,
                sim_hours,
                tick_timestamp_iso=timestamp_iso,
                model_departure_time_hours=departure_time_hours,
            )
        else:
            if planning_reference_iso is None:
                raise HTTPException(
                    status_code=422,
                    detail="planning_forecast mode requires planning_reference_iso.",
                )
            resolution = resolve_planning_time(
                planning_reference_iso,
                lead_hours=lead_hours,
                departure_time_hours=departure_time_hours,
            )
        resolved_target = resolution.target_time_utc
        if resolved_target is None:
            raise HTTPException(status_code=422, detail=resolution.reason)
        if abs((resolved_target - requested_target).total_seconds()) > 1.1:
            raise HTTPException(
                status_code=422,
                detail="target_time_utc is inconsistent with the supplied Phase 1 time inputs.",
            )
    except EnvironmentTimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    layers = _resolve_layers_with_renderable_edge(resolved_target)
    edge = layers.get("sea_ice_edge", {})
    concentration = layers.get("sea_ice_concentration", {})
    concentration_time = concentration.get("source_valid_time_utc")
    for layer in (edge, concentration):
        layer["render_status"] = "unavailable"
        layer["render_reason"] = None

    edge_time = edge.get("source_valid_time_utc")
    if edge.get("_render_probe_error"):
        edge["render_reason"] = edge["_render_probe_error"]
    elif (
        edge.get("status") in {"ready", "stale"}
        and edge.get("tile_template")
        and edge.get("tile_matrix_set") == "EPSG:3857"
        and edge.get("style") == "cmap:viridis"
        and isinstance(edge.get("coverage_bounds_wgs84"), dict)
        and _reported_time_matches_tile_dimension(edge)
        and edge.get("render_quality_tile_template")
        and edge.get("render_quality_style") == "cmap:rainbow"
        and edge.get("render_quality_tile_matrix_set") == "EPSG:3857"
        and _times_match(edge_time, edge.get("render_quality_valid_time_utc"))
        and isinstance(edge.get("render_quality_tile_dimensions"), dict)
        and _times_match(
            edge_time,
            edge.get("render_quality_tile_dimensions", {}).get("time"),
        )
    ):
        edge["render_tile_template"] = _render_tile_template(
            request,
            "edge",
            resolved_target,
            edge_time,
        )
        edge["render_status"] = "ready"
    elif edge.get("status") not in {"ready", "stale"}:
        edge["render_reason"] = edge.get("reason") or "The edge observation is unavailable."
    elif edge.get("tile_matrix_set") != "EPSG:3857":
        edge["render_reason"] = "The edge WMTS matrix is not compatible with Mapbox Web Mercator XYZ."
    elif not edge.get("render_quality_tile_template") or not _times_match(
        edge_time,
        edge.get("render_quality_valid_time_utc"),
    ):
        edge["render_reason"] = edge.get("render_quality_reason") or (
            "No compatible same-time status_flag tile is available to mask invalid edge pixels."
        )
    elif not _reported_time_matches_tile_dimension(edge):
        edge["render_reason"] = "The edge WMTS time dimension does not match its reported valid time."
    else:
        edge["render_reason"] = (
            edge.get("coverage_bounds_reason")
            or "The edge layer has no verified public EPSG:3857 PNG tile template."
        )

    quality_dimensions = concentration.get("render_quality_tile_dimensions")
    quality_tile_time = (
        quality_dimensions.get("time")
        if isinstance(quality_dimensions, dict)
        else None
    )
    concentration_has_renderer = (
        concentration.get("status") in {"ready", "stale"}
        and concentration.get("tile_template")
        and concentration.get("style") == "cmap:ice"
        and concentration.get("units") == "%"
        and concentration.get("tile_matrix_set") == "EPSG:3857"
        and isinstance(concentration.get("coverage_bounds_wgs84"), dict)
        and _reported_time_matches_tile_dimension(concentration)
        and concentration.get("render_quality_tile_template")
        and concentration.get("render_quality_style") == "cmap:rainbow"
        and concentration.get("render_quality_tile_matrix_set") == "EPSG:3857"
        and _times_match(
            concentration.get("source_valid_time_utc"),
            concentration.get("render_quality_valid_time_utc"),
        )
        and _times_match(
            concentration.get("source_valid_time_utc"),
            quality_tile_time,
        )
    )
    if concentration_has_renderer:
        concentration["render_tile_template"] = _render_tile_template(
            request,
            "concentration",
            resolved_target,
            concentration_time,
        )
        concentration["render_status"] = "ready"
        concentration["render_reason"] = None
    elif concentration.get("status") not in {"ready", "stale"}:
        concentration["render_reason"] = concentration.get("reason") or "The concentration observation is unavailable."
    elif not _reported_time_matches_tile_dimension(concentration):
        concentration["render_reason"] = (
            "The concentration WMTS time dimension does not match its reported valid time."
        )
    else:
        concentration["render_reason"] = (
            concentration.get("render_quality_reason")
            or "No compatible, same-time status_flag tile is available to mask invalid concentration pixels."
        )

    return EnvironmentLayersResponse(
        target_time_utc=resolved_target,
        mode=mode,
        time_resolution=resolution,
        layers=layers,
    )


@router.get(
    "/layers/tiles/{mode}/{z}/{x}/{y}.png",
    name="copernicus_sea_ice_tile",
    response_class=Response,
    responses={200: {"content": {"image/png": {}}}, 424: {"description": "Paired observation unavailable"}},
)
def copernicus_sea_ice_tile(
    mode: Literal["edge", "concentration"],
    z: int = FastAPIPath(ge=0, le=10),
    x: int = FastAPIPath(ge=0),
    y: int = FastAPIPath(ge=0),
    target_time_utc: str = Query(..., description="Phase 1 environmental target time in UTC."),
    source_valid_time_utc: str = Query(
        ...,
        description="The exact resolved WMTS observation time; prevents source-time drift.",
    ),
) -> Response:
    """Serve a transparent thematic PNG made only from the resolved official WMTS tile."""
    try:
        target = parse_utc_datetime(target_time_utc, "target_time_utc")
        requested_source_time = parse_utc_datetime(
            source_valid_time_utc,
            "source_valid_time_utc",
        )
    except EnvironmentTimeError as exc:
        raise HTTPException(status_code=422, detail=str(exc)) from exc

    layers = (
        _resolve_layers_with_renderable_edge(target)
        if mode == "edge"
        else resolve_environment_layers(target)
    )
    edge = layers.get("sea_ice_edge", {})
    concentration = layers.get("sea_ice_concentration", {})
    if mode == "edge":
        selected = edge
        paired_time = edge.get("source_valid_time_utc")
        paired_layers = (edge,)
    else:
        selected = concentration
        paired_time = concentration.get("source_valid_time_utc")
        paired_layers = (concentration,)
    if not paired_time or any(not _reported_time_matches_tile_dimension(layer) for layer in paired_layers):
        raise HTTPException(
            status_code=424,
            detail="The selected Copernicus observation has no verified matching WMTS time dimension.",
        )
    if paired_time != requested_source_time:
        raise HTTPException(
            status_code=424,
            detail=(
                "The requested tile observation time is no longer the resolver's matched "
                "source time; reload layer metadata before rendering."
            ),
        )
    if any(layer.get("status") not in {"ready", "stale"} for layer in paired_layers):
        reason = selected.get("reason") or "No available paired Copernicus sea-ice observation."
        raise HTTPException(status_code=424, detail=reason)
    if selected.get("_render_probe_error"):
        raise HTTPException(status_code=424, detail=selected["_render_probe_error"])
    if (
        selected.get("render_quality_tile_template") is None
        or not _times_match(selected.get("render_quality_valid_time_utc"), paired_time)
        or not _reported_time_matches_tile_dimension(selected)
    ):
        raise HTTPException(
            status_code=424,
            detail=selected.get("render_quality_reason")
            or "No same-time status_flag tile is available to mask invalid sea-ice pixels.",
        )
    try:
        rendered = copernicus_tiles.render_sea_ice_tile(selected, mode, z, x, y)
    except copernicus_tiles.CopernicusTileError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc
    return Response(
        content=rendered,
        media_type="image/png",
        headers={"Cache-Control": "public, max-age=900"},
    )


# ------------------------------------------------------------------ coverage
class CoverageProduct(BaseModel):
    layer: str
    product: str
    version: str
    kind: str
    start: str | None = None
    end: str | None = None


class CoverageReplay(BaseModel):
    start: str | None = None
    end: str | None = None
    bbox: list[float] | None = None
    products: list[CoverageProduct] = []


class CoverageRealIce(BaseModel):
    latest_cached_date: str | None = None
    walkback_days: int = 14
    today: str
    available: bool = False


class CoverageResponse(BaseModel):
    replay: CoverageReplay
    real_ice: CoverageRealIce


def _replay_pack_dir() -> Path | None:
    configured = os.environ.get("ICEFLOW_REPLAY_PACK")
    if configured:
        p = Path(configured).expanduser()
        if p.is_dir():
            return p
    # Fallback: check common locations.
    for candidate in (Path.home() / "iceflow-data" / "replay-pack-2022-01", Path("/tmp/iceflow-full-pack")):
        if candidate.is_dir():
            return candidate
    return None


def _latest_nsidc_cached_date(cache_dir: Path | None = None) -> date | None:
    """Find the latest dated NSIDC V6 file in the cache directory."""
    cache = cache_dir or default_cache_dir()
    if not cache.is_dir():
        return None
    best: date | None = None
    for path in cache.glob("sic_pss25_*_*.nc"):
        m = _FILENAME_RE_V6.fullmatch(path.name) or re.fullmatch(r"sic_pss25_(\d{8})_.*", path.name)
        if m:
            try:
                d = datetime.strptime(m.group(1), "%Y%m%d").date()
                if best is None or d > best:
                    best = d
            except ValueError:
                continue
    return best


@router.get("/coverage", response_model=CoverageResponse)
def environment_coverage() -> CoverageResponse:
    """
    Data-coverage summary for the configured replay pack and the real-ice cache.

    Tells the client what dates and products are available so it can avoid
    requesting plan/route computations outside the data window (which would
    return 422 out_of_coverage rather than falling back silently).
    """
    today = datetime.now(timezone.utc).date().isoformat()

    # ---- replay coverage from the pack manifest ----
    pack_dir = _replay_pack_dir()
    replay = CoverageReplay()
    if pack_dir is not None:
        manifest_path = pack_dir / "manifest.json"
        if manifest_path.is_file():
            manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
            start = manifest.get("start")
            days = manifest.get("days", 0)
            end = None
            if start and days:
                end = (datetime.strptime(start, "%Y-%m-%d").date() + timedelta(days=days - 1)).isoformat()
            bbox = manifest.get("bbox")
            products: list[CoverageProduct] = []
            for p in manifest.get("products", []):
                products.append(
                    CoverageProduct(
                        layer=p.get("request_params", {}).get("variables", [p.get("product", "")])[0]
                        if p.get("request_params", {}).get("variables")
                        else p.get("product", ""),
                        product=p.get("product", ""),
                        version=p.get("version", ""),
                        kind=p.get("provenance_kind", ""),
                        start=p.get("valid_from") or start,
                        end=p.get("valid_to") or end,
                    )
                )
            replay = CoverageReplay(start=start, end=end, bbox=bbox, products=products)

    # ---- real_ice coverage from the NSIDC cache ----
    cache_dir = default_cache_dir()
    latest = _latest_nsidc_cached_date(cache_dir)
    real_ice = CoverageRealIce(
        latest_cached_date=latest.isoformat() if latest else None,
        walkback_days=14,
        today=today,
        available=latest is not None,
    )

    return CoverageResponse(replay=replay, real_ice=real_ice)
