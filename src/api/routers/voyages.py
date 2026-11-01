"""Voyage lifecycle: create, inspect, step, re-route, export, and stream live over a WebSocket."""
from __future__ import annotations

import asyncio
import json
import logging
import math
from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field, field_validator, model_validator

from src.core.environment_time import parse_utc_datetime

from src.core.geo import haversine_nm, initial_bearing_deg
from src.core.lindqvist_model import VesselParameters, get_vessel_preset
from src.core.solar import sun_position
from src.core.polaris_risk import IceClass
from src.core.route_optimizer import RouteWeights
from src.core.voyage import VoyageState, VoyageTick, create_voyage
from src.data.environment_provider import OutOfCoverage
from src.data.icebergs import bergs_near
from src.data.nsidc_sea_ice import NSIDCUnavailableError
from src.data.stations import get_waypoint, resolve_endpoint
from src.services.bandwidth import bandwidth_report
from src.services.exporters import (
    ice_overlay_s411,
    route_to_gpx,
    voyage_to_csv,
    voyage_to_geojson,
)
from src.services.store import get_store

router = APIRouter(prefix="/api/v1", tags=["voyage"])


class CreateVoyageRequest(BaseModel):
    origin_id: Optional[str] = Field(default="cape_town")
    destination_id: Optional[str] = Field(default="bharati")
    origin: Optional[List[float]] = Field(default=None, description="[lat, lon], overrides origin_id")
    destination: Optional[List[float]] = Field(default=None, description="[lat, lon]")
    vessel_key: str = "vasiliy_golovnin"
    ice_class: Optional[IceClass] = None
    weights: Optional[RouteWeights] = None
    route_profile_id: Literal["safety-first", "balanced", "fuel-efficient", "fastest"] = "balanced"
    departure_iso: Optional[str] = None
    departure_time_hours: float = Field(default=0.0, ge=0.0, allow_inf_nan=False)
    grid_resolution_deg: float = Field(default=0.5, ge=0.25, le=2.0)
    avoid_icebergs: bool = True
    environment_mode: Literal["simulated", "real_ice", "replay"] = Field(
        default="simulated",
        description="simulated: synthetic ice; real_ice: latest cached NSIDC observation; replay: observed V6 field for replay_date.",
    )
    replay_date: Optional[str] = Field(default=None, description="ISO date (YYYY-MM-DD) for replay mode.")

    @field_validator("departure_iso")
    @classmethod
    def _validate_departure_iso(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            parse_utc_datetime(value, "departure_iso")
        return value

    @field_validator("replay_date")
    @classmethod
    def _validate_replay_date(cls, value: Optional[str]) -> Optional[str]:
        if value is not None:
            datetime.strptime(value, "%Y-%m-%d")
        return value

    @model_validator(mode="after")
    def _require_replay_date(self) -> "CreateVoyageRequest":
        if self.environment_mode == "replay" and not self.replay_date:
            raise ValueError("replay_date is required when environment_mode is 'replay'.")
        return self


class StepRequest(BaseModel):
    hours: float = Field(default=6.0, gt=0.0, le=240.0)
    tick_hours: float = Field(default=1.0, gt=0.0, le=24.0)


def _endpoint(explicit: Optional[List[float]], identifier: Optional[str], label: str):
    if explicit and len(explicit) == 2:
        return (float(explicit[0]), float(explicit[1])), ""
    if identifier:
        resolved = resolve_endpoint(identifier)
        if resolved is None:
            raise HTTPException(status_code=400, detail=f"Unknown {label}: {identifier}")
        entry = get_waypoint(identifier)
        return resolved, (entry or {}).get("name", identifier)
    raise HTTPException(status_code=400, detail=f"A {label} is required.")


@router.post("/voyage", response_model=VoyageState)
def create(req: CreateVoyageRequest) -> VoyageState:
    """Plan a passage and register it as a voyage ready to sail."""
    origin, origin_name = _endpoint(req.origin, req.origin_id, "origin")
    destination, destination_name = _endpoint(req.destination, req.destination_id, "destination")

    try:
        vessel: VesselParameters = get_vessel_preset(req.vessel_key)
    except KeyError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    departure = parse_utc_datetime(req.departure_iso, "departure_iso") if req.departure_iso else None

    try:
        engine = create_voyage(
            origin=origin,
            destination=destination,
            vessel=vessel,
            ice_class=req.ice_class,
            weights=req.weights,
            route_profile_id=req.route_profile_id,
            departure=departure,
            departure_time_hours=req.departure_time_hours,
            origin_name=origin_name,
            destination_name=destination_name,
            vessel_key=req.vessel_key,
            avoid_icebergs=req.avoid_icebergs,
            grid_resolution_deg=req.grid_resolution_deg,
            environment_mode=req.environment_mode,
            replay_date=req.replay_date,
        )
    except NSIDCUnavailableError as exc:
        raise HTTPException(
            status_code=422,
            detail=f"environment_mode='{req.environment_mode}' could not be honoured: {exc}",
        ) from exc
    get_store().register(engine)
    return engine.state


@router.get("/voyage")
def list_voyages(limit: int = Query(default=25, ge=1, le=200)) -> Dict[str, Any]:
    return {"voyages": get_store().list_voyages(limit), "stats": get_store().stats()}


@router.get("/voyage/{voyage_id}", response_model=VoyageState)
def get_voyage(voyage_id: str) -> VoyageState:
    state = get_store().load(voyage_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown voyage: {voyage_id}")
    return state


# ------------------------------------------------------------------ timeline
_MAX_TIMELINE_STEPS = 4000  # size cap: keep the JSON payload bounded


def _wind_components(speed_ms: float | None, dir_from_deg: float | None):
    """Derive eastward/northward wind components (m/s) from speed and FROM-direction."""
    if speed_ms is None or dir_from_deg is None:
        return None, None
    rad = math.radians(dir_from_deg)
    # Meteorological direction is WHERE the wind comes FROM; the vector it blows
    # toward is dir + 180 deg.
    u = -speed_ms * math.sin(rad)  # eastward
    v = -speed_ms * math.cos(rad)  # northward
    return u, v


def _cog_deg(lat0, lon0, lat1, lon1) -> float | None:
    """Course over ground from the previous fix to this fix (degrees clockwise from north)."""
    if lat0 is None or lon0 is None:
        return None
    d = haversine_nm(lat0, lon0, lat1, lon1)
    if d < 1e-6:
        return None
    return initial_bearing_deg(lat0, lon0, lat1, lon1)


def _provenance_from_state(state: VoyageState) -> dict[str, dict[str, Any]]:
    """Per-variable provenance fallback when no live engine/environment is available."""
    out: dict[str, dict[str, Any]] = {}
    for prov in state.provenance or []:
        entry = {
            "kind": prov.kind,
            "source": prov.source,
            "product": prov.product,
            "valid_time": prov.valid_time,
            "age_hours": prov.age_hours,
        }
        if prov.layer == "sea_ice_field":
            out["ice_conc"] = entry
        elif prov.layer == "atmosphere_ocean":
            for var in ("u10", "v10", "wind_speed_ms", "wind_dir_from_deg", "sig_wave_height_m",
                        "t2m_c", "msl_hpa", "snowfall", "total_cloud_cover"):
                out[var] = entry
    return out


@router.get("/voyage/{voyage_id}/timeline")
def voyage_timeline(
    voyage_id: str,
    step_min: float = Query(default=10.0, gt=0.0, le=1440.0, description="Minutes between timeline steps"),
    ) -> Dict[str, Any]:
    """
    Replay a voyage as a timeline of per-step environmental and navigation state.

    Each step carries t_utc, position, speed/course/heading, ice concentration with its
    valid time and product, wind, waves, currents, nearby observed bergs, alerts and solar
    position. Anything the data cannot supply is omitted and listed in ``not_available``.
    ``provenance_by_variable`` gives {kind, source, product, valid_time, age_hours} per
    variable. The response is gzipped and size-capped via ``step_min``.
    """
    store = get_store()
    engine = store.engine(voyage_id)
    if engine is None:
        state = store.load(voyage_id)
        if state is None:
            raise HTTPException(status_code=404, detail=f"Unknown voyage: {voyage_id}")
        ticks = list(state.ticks)
        env = None
    else:
        state = engine.state
        ticks = list(state.ticks)
        env = engine.env

    departure = parse_utc_datetime(state.departure_iso)

    prov_fallback = _provenance_from_state(state)

    # Select ticks at the requested step interval (measure from departure).
    step_seconds = step_min * 60.0
    selected: List[VoyageTick] = []
    last_step_index: int | None = None
    for tick in ticks:
        tick_seconds = tick.sim_hours * 3600.0
        step_index = int(round(tick_seconds / step_seconds)) if step_seconds > 0 else 0
        if last_step_index is None or step_index != last_step_index:
            selected.append(tick)
            last_step_index = step_index
        if len(selected) >= _MAX_TIMELINE_STEPS:
            break

    not_available: set[str] = set()
    steps: List[Dict[str, Any]] = []
    prev_lat: float | None = None
    prev_lon: float | None = None

    for tick in selected:
        t_utc = tick.timestamp_iso
        lat, lon = tick.latitude, tick.longitude

        # --- provenance / coverage from the live environment (when available) ---
        prov_by_variable: dict[str, dict[str, Any]] = dict(prov_fallback)
        wave_valid = True
        if env is not None:
            try:
                sample = env.sample(lat, lon, parse_utc_datetime(t_utc))
                prov_by_variable = {**prov_fallback, **(sample.provenance_by_variable or {})}
                wave_valid = bool(sample.wave_valid)
                # Re-derive wind direction/speed from the sampled components for consistency.
                if sample.u10 is not None and sample.v10 is not None:
                    tick_wind_speed = math.hypot(sample.u10, sample.v10)
                    tick_wind_dir = (math.degrees(math.atan2(sample.u10, sample.v10)) + 360.0) % 360.0
                else:
                    tick_wind_speed = tick.wind_speed_ms
                    tick_wind_dir = tick.wind_dir_from_deg
            except OutOfCoverage:
                not_available.add("environment_sample")
                tick_wind_speed = tick.wind_speed_ms
                tick_wind_dir = tick.wind_dir_from_deg
        else:
            tick_wind_speed = tick.wind_speed_ms
            tick_wind_dir = tick.wind_dir_from_deg

        u10, v10 = _wind_components(tick_wind_speed, tick_wind_dir)
        if u10 is None:
            not_available.add("wind_u")
            not_available.add("wind_v")

        cog = _cog_deg(prev_lat, prev_lon, lat, lon)
        if cog is None and tick is selected[0]:
            not_available.add("cog")
        prev_lat, prev_lon = lat, lon

        hs = tick.wave_height_m
        if not wave_valid:
            hs = None
            not_available.add("hs")
        elif hs is None:
            not_available.add("hs")

        # Wave peak period and wave direction are not carried per-tick.
        not_available.add("tp")
        wave_dir = tick_wind_dir  # best available proxy (wind direction)
        if wave_dir is None:
            not_available.add("wave_dir")

        uo, vo = None, None
        not_available.add("current_u")
        not_available.add("current_v")

        ice_conc = tick.ice_concentration
        if ice_conc is None:
            not_available.add("ice_conc")

        # Solar position at this fix.
        try:
            sun_az, sun_el = sun_position(lat, lon, parse_utc_datetime(t_utc))
        except Exception:
            sun_az, sun_el = None, None
            not_available.add("sun")

        # Nearby observed bergs (fixed catalogue, never invented).
        try:
            near = bergs_near(lat, lon, radius_nm=50.0)
        except Exception:
            near = []
            not_available.add("bergs")
        bergs = [
            {
                "name": b.berg_id,
                "lat": b.latitude,
                "lon": b.longitude,
                "length_nm": round(b.length_m / 1852.0, 2) if b.length_m else None,
                "width_nm": round(b.width_m / 1852.0, 2) if b.width_m else None,
                "age": None,
                "kind": None,
            }
            for b in near
        ]
        if not bergs:
            not_available.add("nearby_bergs")

        alerts = list(tick.active_alerts)

        steps.append({
            "t_utc": t_utc,
            "lat": lat,
            "lon": lon,
            "sog_kn": tick.speed_over_ground_knots,
            "cog": cog,
            "heading": tick.heading_deg,
            "ice_conc": ice_conc,
            "wind_u": u10,
            "wind_v": v10,
            "hs": hs,
            "tp": None,
            "wave_dir": wave_dir,
            "current_u": uo,
            "current_v": vo,
            "nearby_bergs": bergs,
            "alerts": alerts,
            "sun_azimuth_deg": None if sun_az is None or (isinstance(sun_az, float) and math.isnan(sun_az)) else round(sun_az, 2),
            "sun_elevation_deg": None if sun_el is None or (isinstance(sun_el, float) and math.isnan(sun_el)) else round(sun_el, 2),
            "provenance_by_variable": prov_by_variable,
        })

    return {
        "voyage_id": voyage_id,
        "step_min": step_min,
        "n_steps": len(steps),
        "not_available": sorted(not_available),
        "steps": steps,
    }


@router.post("/voyage/{voyage_id}/step")
def step_voyage(voyage_id: str, req: StepRequest) -> Dict[str, Any]:
    """
    Advance the voyage in simulated time.

    This exists alongside the WebSocket so the whole system remains usable from curl, and so a
    test can drive a voyage deterministically without a socket.
    """
    store = get_store()
    engine = store.engine(voyage_id)
    if engine is None:
        raise HTTPException(
            status_code=404,
            detail=f"Voyage {voyage_id} is not live in this process. Create a new voyage to sail it.",
        )
    ticks: List[VoyageTick] = engine.run(hours=req.hours, tick_hours=req.tick_hours)
    store.save(engine.state)
    return {
        "voyage_id": voyage_id,
        "status": engine.state.status,
        "ticks_produced": len(ticks),
        "ticks": ticks,
        "sim_hours": engine.state.sim_hours,
        "total_fuel_tonnes": engine.state.total_fuel_tonnes,
        "distance_travelled_nm": engine.state.distance_travelled_nm,
        "open_alerts": sorted({a.code for a in engine.state.alerts if a.cleared_at_tick is None}),
    }


@router.post("/voyage/{voyage_id}/reroute")
def reroute_voyage(voyage_id: str) -> Dict[str, Any]:
    """Re-plan from the ship's present position, keeping the track already sailed."""
    store = get_store()
    engine = store.engine(voyage_id)
    if engine is None:
        raise HTTPException(status_code=404, detail=f"Voyage {voyage_id} is not live in this process.")
    plan = engine.reroute()
    store.save(engine.state)
    return {
        "voyage_id": voyage_id,
        "reroute_count": engine.state.reroute_count,
        "new_plan": plan,
        "planned_route": engine.state.planned_route,
    }


@router.delete("/voyage/{voyage_id}")
def delete_voyage(voyage_id: str) -> Dict[str, Any]:
    return {"deleted": get_store().delete(voyage_id)}


# ------------------------------------------------------------------------- exports
@router.get("/export/{voyage_id}.{fmt}")
def export_voyage(voyage_id: str, fmt: str) -> Response:
    """Export a voyage as GeoJSON, GPX, CSV or an S-411-shaped ice overlay."""
    state = get_store().load(voyage_id)
    if state is None:
        raise HTTPException(status_code=404, detail=f"Unknown voyage: {voyage_id}")

    fmt = fmt.lower()
    stem = f"polarnav-{voyage_id}"

    if fmt == "geojson":
        return JSONResponse(
            content=voyage_to_geojson(state),
            headers={"Content-Disposition": f'attachment; filename="{stem}.geojson"'},
        )
    if fmt == "gpx":
        gpx = route_to_gpx(
            state.planned_route,
            route_name=f"{state.origin_name or 'Origin'} to {state.destination_name or 'Destination'}",
        )
        return Response(
            content=gpx,
            media_type="application/gpx+xml",
            headers={"Content-Disposition": f'attachment; filename="{stem}.gpx"'},
        )
    if fmt == "csv":
        return PlainTextResponse(
            content=voyage_to_csv(state),
            headers={"Content-Disposition": f'attachment; filename="{stem}.csv"'},
        )
    if fmt in {"s411", "json"}:
        from src.core.sea_ice import get_sea_ice_model

        lats = [w.latitude for w in state.planned_route] or [state.destination[0]]
        lons = [w.longitude for w in state.planned_route] or [state.destination[1]]
        field = get_sea_ice_model().field(
            max(-78.0, min(lats) - 2), min(-40.0, max(lats) + 2),
            min(lons) - 3, max(lons) + 3, 1.0, 0.0, 0.0,
        )
        return JSONResponse(content=ice_overlay_s411(field))

    raise HTTPException(status_code=400, detail="Format must be one of: geojson, gpx, csv, s411.")


# ----------------------------------------------------------------------- telemetry
@router.get("/telemetry/bandwidth")
def telemetry_bandwidth(
    resolution_deg: float = Query(default=0.5, ge=0.25, le=2.0),
    updates_per_day: int = Query(default=4, ge=1, le=24),
) -> Dict[str, Any]:
    """
    The satellite-link budget, measured rather than asserted.

    Both payloads are actually built, serialised and gzipped, and the byte counts returned are
    the real lengths.
    """
    return bandwidth_report(resolution_deg=resolution_deg, updates_per_day=updates_per_day)


# ----------------------------------------------------------------------- websocket
@router.websocket("/ws/voyage/{voyage_id}")
async def voyage_socket(websocket: WebSocket, voyage_id: str) -> None:
    """
    Stream a voyage as it sails.

    The client may send {"action": "start", "tick_hours": 6, "interval_ms": 400} to begin, and
    {"action": "pause"} or {"action": "step"} at any time. Each tick is pushed as it is computed,
    with any newly raised alerts, so the bridge console updates the way a real one would.
    """
    await websocket.accept()
    store = get_store()
    engine = store.engine(voyage_id)
    if engine is None:
        await websocket.send_json({"type": "error", "payload": {"message": f"Unknown voyage {voyage_id}"}})
        await websocket.close()
        return

    await websocket.send_json({"type": "state", "payload": json.loads(engine.state.model_dump_json())})

    running = False
    tick_hours = 6.0
    interval = 0.4
    seen_alerts = {a.alert_id for a in engine.state.alerts}

    async def pump() -> None:
        nonlocal running
        try:
            while running:
                if engine.state.status in {"ARRIVED", "ABORTED"}:
                    await websocket.send_json({"type": "done", "payload": {"status": engine.state.status}})
                    running = False
                    break
                tick = await asyncio.to_thread(engine.step, tick_hours)
                # A pause can arrive while the tick is computing. Never ship a tick after the
                # operator asked to stop: it would overwrite the `paused` frame on the client
                # and leave the voyage reading as `running`.
                if not running:
                    break
                await websocket.send_json({"type": "tick", "payload": json.loads(tick.model_dump_json())})
                for alert in engine.state.alerts:
                    if alert.alert_id not in seen_alerts:
                        seen_alerts.add(alert.alert_id)
                        await websocket.send_json(
                            {"type": "alert", "payload": json.loads(alert.model_dump_json())}
                        )
                await asyncio.sleep(interval)
        finally:
            store.save(engine.state)

    pump_task: Optional[asyncio.Task] = None

    def _drain_pump_failure(task: asyncio.Task) -> None:
        # The pump task is fire-and-forget; without this its CancelledError (and any real
        # exception) would otherwise surface as "Task exception was never retrieved".
        try:
            task.result()
        except asyncio.CancelledError:
            pass
        except Exception:
            logger.exception("Voyage pump task failed for %s", voyage_id)

    try:
        while True:
            message = await websocket.receive_json()
            action = str(message.get("action", "")).lower()

            if action == "start":
                tick_hours = float(message.get("tick_hours", tick_hours))
                interval = max(0.05, float(message.get("interval_ms", 400)) / 1000.0)
                if not running:
                    running = True
                    pump_task = asyncio.create_task(pump())
                    pump_task.add_done_callback(_drain_pump_failure)
            elif action == "pause":
                # Stop the pump and interrupt its sleep. Setting only `running = False` lets
                # the current iteration finish and ship one more tick after the `paused`
                # frame; the client's tick handler then forces `running` and the voyage never
                # reads as paused.
                running = False
                if pump_task is not None and not pump_task.done():
                    pump_task.cancel()
                await websocket.send_json({"type": "paused", "payload": {"sim_hours": engine.state.sim_hours}})
            elif action == "step":
                tick = await asyncio.to_thread(engine.step, float(message.get("tick_hours", tick_hours)))
                await websocket.send_json({"type": "tick", "payload": json.loads(tick.model_dump_json())})
            elif action == "reroute":
                plan = await asyncio.to_thread(engine.reroute)
                await websocket.send_json(
                    {"type": "reroute", "payload": json.loads(plan.model_dump_json())}
                )
            elif action == "close":
                break
    except WebSocketDisconnect:
        pass
    finally:
        running = False
        if pump_task is not None:
            pump_task.cancel()
        store.save(engine.state)
