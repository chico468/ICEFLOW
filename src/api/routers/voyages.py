"""Voyage lifecycle: create, inspect, step, re-route, export, and stream live over a WebSocket."""
from __future__ import annotations

import asyncio
import json
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse, Response
from pydantic import BaseModel, Field

from src.core.lindqvist_model import VesselParameters, get_vessel_preset
from src.core.polaris_risk import IceClass
from src.core.route_optimizer import RouteWeights
from src.core.voyage import VoyageState, VoyageTick, create_voyage
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
    grid_resolution_deg: float = Field(default=0.5, ge=0.25, le=2.0)
    avoid_icebergs: bool = True


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

    engine = create_voyage(
        origin=origin,
        destination=destination,
        vessel=vessel,
        ice_class=req.ice_class,
        weights=req.weights,
        origin_name=origin_name,
        destination_name=destination_name,
        vessel_key=req.vessel_key,
        avoid_icebergs=req.avoid_icebergs,
        grid_resolution_deg=req.grid_resolution_deg,
    )
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
        while running:
            if engine.state.status in {"ARRIVED", "ABORTED"}:
                await websocket.send_json({"type": "done", "payload": {"status": engine.state.status}})
                running = False
                break
            tick = await asyncio.to_thread(engine.step, tick_hours)
            await websocket.send_json({"type": "tick", "payload": json.loads(tick.model_dump_json())})
            for alert in engine.state.alerts:
                if alert.alert_id not in seen_alerts:
                    seen_alerts.add(alert.alert_id)
                    await websocket.send_json(
                        {"type": "alert", "payload": json.loads(alert.model_dump_json())}
                    )
            await asyncio.sleep(interval)
        store.save(engine.state)

    pump_task: Optional[asyncio.Task] = None
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
            elif action == "pause":
                running = False
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
