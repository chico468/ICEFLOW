"""
ICEFLOW REST and WebSocket service.

Serves the Antarctic navigation decision-support models to the bridge console and to any client
that speaks HTTP. Everything is computed on request from the physics core; there are no canned
responses anywhere in this service.

Run it with:

    uvicorn src.api.main:app --reload --port 8000

and open http://localhost:8000/docs for the interactive schema.
"""
from __future__ import annotations

import os
import threading
import time
from contextlib import asynccontextmanager
from typing import Any, AsyncIterator, Dict

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware

from src.core.constants import (
    DATA_PROVENANCE,
    DEPARTMENT,
    MODEL_VERSIONS,
    ORGANIZATION,
    PROBLEM_STATEMENT_ID,
    SYSTEM_NAME,
    SYSTEM_VERSION,
)
from src.api.routers import environment as environment_router
from src.api.routers import copernicus_layers as copernicus_layers_router
from src.api.routers import geo as geo_router
from src.api.routers import navigation as navigation_router
from src.api.routers import observed_ice as observed_ice_router
from src.api.routers import real_flow as real_flow_router
from src.api.routers import physics as physics_router
from src.api.routers import voyages as voyages_router

_STARTED_AT = time.time()
_WARMUP: Dict[str, Any] = {"state": "pending", "seconds": 0.0, "detail": ""}


def _warm_caches() -> None:
    """
    Build the expensive process-wide caches before anyone asks for them.

    Three things are slow exactly once: the coast-distance lookup grid (a batched KD-tree query
    over the coastline), the vessel performance tables (a bisection per thickness/concentration
    cell), and the iceberg drift tracks. Left lazy, the cost lands on whoever presses the button
    first - which, at a demonstration, is the person you least want to keep waiting.
    """
    started = time.perf_counter()
    try:
        from src.core.lindqvist_model import VESSEL_PRESETS
        from src.core.route_optimizer import get_performance
        from src.data.landmask import get_coast_field, get_land_mask

        get_land_mask()
        get_coast_field()
        for vessel in VESSEL_PRESETS.values():
            get_performance(vessel, vessel.installed_power_kw)

        _WARMUP.update(state="warming", detail="Caches built; pre-planning the default leg.")

        # Pre-plan the default demonstration leg. This is what actually removes the stall: the
        # remaining cost is integrating iceberg drift tracks, which are cached per berg and
        # departure time, so doing it here means the first plan a user asks for is the fast path.
        # Set ICEFLOW_SKIP_WARM_PLAN=1 or POLARNAV_SKIP_WARM_PLAN=1 to skip it on a constrained machine.
        if os.environ.get("ICEFLOW_SKIP_WARM_PLAN") != "1" and os.environ.get("POLARNAV_SKIP_WARM_PLAN") != "1":
            from src.core.route_optimizer import PolarRouteOptimizer
            from src.data.stations import resolve_endpoint

            origin = resolve_endpoint("cape_town")
            dest = resolve_endpoint("bharati")
            if origin and dest:
                vessel = VESSEL_PRESETS["vasiliy_golovnin"]
                PolarRouteOptimizer(
                    vessel=vessel,
                    ice_class=vessel.ice_class,
                    installed_power_kw=vessel.installed_power_kw,
                ).optimize_route(origin[0], origin[1], dest[0], dest[1])

        _WARMUP.update(
            state="ready",
            seconds=round(time.perf_counter() - started, 2),
            detail=(
                "Coast-distance grid, vessel performance tables and iceberg drift tracks built. "
                "The default Cape Town to Bharati plan is now on the fast path."
            ),
        )
    except Exception as exc:  # pragma: no cover - warm-up must never break start-up
        _WARMUP.update(
            state="failed",
            seconds=round(time.perf_counter() - started, 2),
            detail=f"{type(exc).__name__}: {exc}. Caches will build lazily instead.",
        )

@asynccontextmanager
async def _lifespan(_: FastAPI) -> AsyncIterator[None]:
    """
    Warm the caches in a worker thread, so the server answers immediately but the first real
    request does not pay for the lookup tables.
    """
    threading.Thread(target=_warm_caches, name="polarnav-warmup", daemon=True).start()
    yield


app = FastAPI(
    lifespan=_lifespan,
    title=f"{SYSTEM_NAME}: Antarctic Navigation Decision Support",
    description=(
        "Sea-ice forecasting, iceberg drift, IMO POLARIS risk indexing, Lindqvist ice resistance "
        "and risk-constrained route optimisation for Indian Antarctic Expedition vessels. "
        "Smart India Hackathon 2026, problem statement 26059, for MoES / NCPOR.\n\n"
        "**Honesty note.** The physics, the POLARIS tables and the coastline are real. The "
        "atmospheric, oceanographic and sea-ice fields are synthetic stand-ins for ERA5, CMEMS "
        "and OSI-SAF products; every response carrying them says so in an `is_synthetic` field."
    ),
    version=SYSTEM_VERSION,
)

# The bridge console is served from a separate origin during development, and on a ship it is a
# local device on the same LAN. Neither case benefits from origin restrictions here.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(geo_router.router)
app.include_router(environment_router.router)
app.include_router(copernicus_layers_router.router)
app.include_router(physics_router.router)
app.include_router(navigation_router.router)
app.include_router(observed_ice_router.router)
app.include_router(real_flow_router.router)
app.include_router(voyages_router.router)


@app.get("/", tags=["meta"])
def read_root(request: Request) -> Any:
    """
    Service identity, or the bridge console.

    Two callers want different things from `/`. An API client - including the v0.1 test suite -
    expects the identity JSON, and that contract is kept. A browser in a single-container
    deployment expects the application. Rather than break either, the response is negotiated on
    the Accept header: browsers ask for text/html and get the console, everything else gets JSON.
    """
    if _frontend_dist() is not None and "text/html" in request.headers.get("accept", ""):
        from fastapi.responses import FileResponse

        return FileResponse(_frontend_dist() / "index.html")

    return {
        "system": f"{SYSTEM_NAME} Decision Support System",
        "problem_statement_id": PROBLEM_STATEMENT_ID,
        "organization": f"{ORGANIZATION} / NCPOR",
        "status": "OPERATIONAL",
        "version": SYSTEM_VERSION,
        "docs_url": "/docs",
        "health_url": "/api/v1/health",
    }


@app.get("/api/v1/health", tags=["meta"])
def health() -> Dict[str, Any]:
    """
    Liveness, model versions and data provenance.

    The provenance block is the important part: it states, per data layer, whether it is real or
    simulated and what it stands in for. A reviewer should be able to answer "which of these
    numbers came from the world?" without reading any code.
    """
    ml_status: Dict[str, Any]
    try:
        from src.ml.registry import ml_status as _ml_status

        ml_status = _ml_status()
    except Exception:
        # The machine-learning layer is optional. The physics path never depends on it.
        ml_status = {"available": False, "reason": "ML package not installed or no trained models found"}

    return {
        "status": "ok",
        "system": SYSTEM_NAME,
        "version": SYSTEM_VERSION,
        "problem_statement_id": PROBLEM_STATEMENT_ID,
        "organization": ORGANIZATION,
        "department": DEPARTMENT,
        "uptime_seconds": round(time.time() - _STARTED_AT, 1),
        "warmup": dict(_WARMUP),
        "model_versions": MODEL_VERSIONS,
        "data_provenance": DATA_PROVENANCE,
        "machine_learning": ml_status,
        "programme": {
            "name": "Indian Scientific Expedition to Antarctica (ISEA)",
            "nodal_agency": "National Centre for Polar and Ocean Research (NCPOR), Goa",
            "legal_framework": "Indian Antarctic Act, 2022; Antarctic Treaty; IMO Polar Code",
            "season_window": "Austral summer, December to March",
            "stations_served": ["Maitri", "Bharati"],
            "detail_url": "/api/v1/geo/programme",
        },
        "external_network_calls": False,
        "api_keys_required": False,
    }


# --------------------------------------------------------------------------------------
# Serve the built bridge console, when one has been built.
#
# This is what makes a deployment a single service rather than two. With the frontend served by
# the API, everything is same-origin: no CORS configuration to get wrong, and no build-time
# variable telling the bundle where its backend lives.
#
# It is mounted LAST so that every API route above wins the match, and it is skipped entirely
# when frontend/dist is absent - which is the normal case in development, where Vite serves the
# console itself on port 5173.
# --------------------------------------------------------------------------------------
def _frontend_dist():
    """The built console directory, or None when it has not been built."""
    from pathlib import Path

    dist = Path(__file__).resolve().parents[2] / "frontend" / "dist"
    return dist if (dist / "index.html").is_file() else None


def _mount_frontend() -> None:
    from fastapi.responses import FileResponse
    from fastapi.staticfiles import StaticFiles

    dist = _frontend_dist()
    if dist is None:
        return

    app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

    @app.get("/{path:path}", include_in_schema=False)
    def spa(path: str):
        """
        Serve a real file when one exists, otherwise the app shell.

        A single-page app owns its own routing, so any unmatched path has to return index.html
        rather than a 404 - except under /api, where a 404 is the correct and useful answer.
        """
        if path.startswith("api/"):
            raise HTTPException(status_code=404, detail=f"No such endpoint: /{path}")
        candidate = dist / path
        if path and candidate.is_file():
            return FileResponse(candidate)
        return FileResponse(dist / "index.html")


@app.get("/api/v1/visualize/antarctica-grid", tags=["meta"])
def antarctica_grid() -> Dict[str, Any]:
    """
    Stations and tracked icebergs as a GeoJSON FeatureCollection.

    Retained from v0.1 so existing clients keep working. New clients should prefer
    `/api/v1/geo/stations`, `/api/v1/geo/coastline` and `/api/v1/icebergs`, which carry far more.
    """
    from src.data.icebergs import get_iceberg_catalogue
    from src.data.stations import get_stations

    features = []
    for station in get_stations():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [station["longitude"], station["latitude"]]},
                "properties": {
                    "type": "Research_Station",
                    "name": station["name"],
                    "region": station["region"],
                    "country": station["country"],
                    "anchorage": [station["anchorage_lat"], station["anchorage_lon"]],
                },
            }
        )
    for berg in get_iceberg_catalogue():
        features.append(
            {
                "type": "Feature",
                "geometry": {"type": "Point", "coordinates": [berg["longitude"], berg["latitude"]]},
                "properties": {
                    "type": "Tracked_Iceberg",
                    "berg_id": berg["berg_id"],
                    "length_m": berg["length_m"],
                    "origin": berg["origin"],
                },
            }
        )
    return {"type": "FeatureCollection", "features": features}


# Declared last: the catch-all must not shadow the API routes above.
_mount_frontend()
