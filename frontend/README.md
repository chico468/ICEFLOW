# ICEFLOW — bridge console

The web client for the Antarctic navigation decision-support system. React 18, Vite, TypeScript
in strict mode, Tailwind, Zustand, TanStack Query and Recharts.

## Running it

The backend must be up first, from the repository root:

```bash
uvicorn src.api.main:app --port 8000
```

Then:

```bash
npm install
npm run dev      # http://localhost:5173
npm run build    # must complete with zero TypeScript errors
```

Vite proxies `/api` and `/ws` to `http://127.0.0.1:8000`, so there is no CORS configuration and
no environment variable to set. If the masthead says "Backend offline", the API is not running.

## Why the map is written by hand

This is the decision worth explaining, because reaching for Mapbox or Leaflet is the obvious move
and it is the wrong one here.

**Web Mercator does not work at 70°S.** Every mainstream web-mapping library assumes it. It
diverges at the poles, and the entire operating area of this system is inside the region where it
fails. Antarctic charts use **EPSG:3031 Antarctic Polar Stereographic**, and none of the usual
libraries support it without a projection plugin that then fights the tile pipeline.

**There are no map tiles at sea.** Below 60°S a ship has Iridium Certus and a strict daily byte
budget. A console that blanks out when it cannot reach a tile server is a console that fails
exactly when it is needed. So the map has no external dependency at all: the coastline arrives as
vector polygons from our own API, and the ice raster is model output, not somebody's basemap.

**We need to draw model output, not a basemap.** The interesting layers — concentration,
compression, drift vectors, iceberg uncertainty ellipses, a route coloured by POLARIS risk — are
not things a tile provider has. They would be overlays on top of a basemap we do not need.

So `src/map/` is a small canvas engine: `projection.ts` ports the backend's EPSG:3031 forward and
inverse transforms exactly, `viewport.ts` handles pan and zoom, `layers.ts` holds sixteen draw
routines, and `MapEngine.ts` composes them bottom-up into a frame. It redraws only when something
changes, and it is device-pixel-ratio aware.

## Layout

```
src/
  api/         typed client and TanStack Query hooks; types mirror the FastAPI schema
  components/  Panel, Stat, RioGauge, Meter, Slider, RadarScope, ProvenanceBar
  hooks/       useVoyageSocket (live WebSocket), useScene (composes the MapScene)
  map/         the EPSG:3031 canvas engine
  screens/     BridgeConsole, VoyagePlanner, IceForecast, IcebergTracker, Analytics
  store/       Zustand client state
```

Server state lives in TanStack Query and is never copied into Zustand. The one exception is the
live voyage, which arrives over a WebSocket rather than a request and so has no query to own it.

## Things worth knowing before changing it

- **Planning is slow on purpose.** `POST /api/v1/route/optimize` and `POST /api/v1/voyage` run a
  real optimisation: about 30 seconds cold, 12 after the caches warm. Both are wrapped in a
  `ComputeOverlay` that names the stage being computed. Do not add a spinner-only state.
- **`fuel_saved_percentage` can be negative,** and it genuinely is on some legs, because the safe
  route is longer and the extra distance costs more fuel than the ice it avoids. Never clamp it
  or take its absolute value. The `warnings` array explains when it happens; it is surfaced in
  the planner.
- **Screens stay mounted** and are hidden rather than unmounted, so the chart keeps the viewport
  the user panned to.
- **Anything simulated must stay labelled.** The API sets `is_synthetic` and `source` on every
  response carrying a modelled field, and `ProvenanceBar` reads those rather than hardcoding a
  message. Keep it that way.
