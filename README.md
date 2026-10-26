# ICEFLOW

**AI-Enabled Antarctic Sea-Ice, Iceberg Trajectory and Navigation Decision Support System**

[![SIH 2026](https://img.shields.io/badge/SIH-2026-blue.svg)](https://www.sih.gov.in/)
[![Problem ID](https://img.shields.io/badge/Problem%20Statement-26059-orange.svg)](https://www.sih.gov.in/)
[![Organisation](https://img.shields.io/badge/MoES-NCPOR-green.svg)](https://ncpor.res.in/)
[![IMO POLARIS](https://img.shields.io/badge/IMO-MSC.1%2FCirc.1519-brightgreen.svg)](https://www.imo.org/)
[![Python](https://img.shields.io/badge/Python-3.11-3776AB.svg)](https://www.python.org/)
[![React](https://img.shields.io/badge/React-18-61DAFB.svg)](https://react.dev/)

A working decision-support system for the ships that resupply India's Antarctic stations,
**Maitri** and **Bharati**. It forecasts sea ice, predicts iceberg drift, and plans a route that
satisfies the IMO Polar Code, arrives days sooner, and carries a materially better safety
margin than the route a ship would otherwise sail.

---

## Problem statement

| Field | Detail |
| :--- | :--- |
| **Problem Statement ID** | 26059 |
| **Title** | AI-Enabled Antarctic Sea-Ice, Iceberg Trajectory, and Navigation Decision Support System |
| **Theme** | Transportation & Logistics |
| **Category** | Software |
| **Organisation** | Ministry of Earth Sciences (MoES) |
| **Department** | National Centre for Polar and Ocean Research (NCPOR) |
| **Solution name** | ICEFLOW |
| **Team name** | _fill in_ |
| **Team ID** | _fill in_ |

**The ask.** Develop an AI/ML-enabled decision support platform capable of forecasting Antarctic
sea-ice concentration, predicting iceberg trajectories, and identifying safe and fuel-efficient
navigation routes for research vessels using satellite, oceanographic and meteorological datasets.

**What is delivered.** All four capabilities, running end to end: a sea-ice analysis and forecast
that beats persistence, an RK4 Lagrangian iceberg drift model with ensembles, a
POLARIS-constrained route optimiser measured honestly against an ice-blind baseline, and a bridge
console that sails the plan hour by hour with live alerting. Plus three trained models, of which
one is good enough to use and two are reported as failures.

---

## Built for the Indian Antarctic programme, specifically

This is not a generic polar router with Indian place names pasted on. The programme's actual
constraints are in the model.

**The two stations are supplied in completely different ways, and the router knows it.**
Maitri sits about 80 km inland on the Schirmacher Oasis — no ship can reach it. Cargo is landed
on the shelf ice at **India Bay** and hauled inland by convoy. Bharati is coastal but sits behind
the Prydz Bay fast ice, with the Amery Ice Shelf calving tabular bergs straight into the
approach. Every destination therefore carries a **validated seaward anchorage**, checked against
the real coastline at start-up, so the planner can never be handed a destination a ship cannot
reach.

**The season is a hard constraint.** The window is roughly 90 days, December to March. The
environment model's reference date is **26 November — the southbound departure, not the February
ice minimum**. That is deliberate: late November is when the pack is still extensive and the
routing problem is hardest. Planning against the February minimum would flatter the system.

**The fleet is real, including the gap in it.** Four presets, and the comparison between them is
an argument India can use. Same passage, 1.5 m ice at 6/10 concentration:

| Vessel | Ice class | Power | Attainable speed |
| :--- | :--- | ---: | ---: |
| **ORV Sagar Nidhi** (NIOT / MoES, first Indian vessel to Antarctica, 2010) | PC7 | 5.6 MW | **0.0 kn — beset** |
| **MV Vasiliy Golovnin** (the ship NCPOR charters) | PC5 | 13.5 MW | 2.6 kn |
| Arc7 resupply vessel (generic) | Arc7 | 13.0 MW | 4.5 kn |
| **Indian Polar Research Vessel** (planned, notional) | PC4 | 12.0 MW | **4.2 kn** |

India has no dedicated polar research vessel. This system lets that cost be *measured* rather
than argued: plan the same passage with each hull and see where the planner refuses to go.

**The legal frame is enforced, not cited.** The Indian Antarctic Act 2022, the Antarctic Treaty
environmental protocol, and the IMO Polar Code. POLARIS is a hard constraint in the optimiser —
a route through prohibited ice is not returned at all — and the fuel model is marine gas oil
throughout, because the Polar Code bans heavy fuel oil carriage.

Full context at `GET /api/v1/geo/programme`.

---

## Read this first: what is real and what is simulated

This is the part most prototypes are vague about, so it goes at the top.

| Layer | Status | Detail |
| :--- | :--- | :--- |
| Ship ice-resistance physics | **Real** | Lindqvist (1989), validated against published results to within a few percent |
| IMO POLARIS risk tables | **Real** | Transcribed from MSC.1/Circ.1519, all 12 ice classes x 11 ice types |
| Antarctic coastline | **Real** | Natural Earth 1:50m, 97 polygons, used as the hard land mask |
| Station coordinates | **Real** | Published NCPOR positions |
| Iceberg identities and origins | **Real** | US National Ice Center naming (D-28, A-23A, A-74, …) |
| Geodesy and EPSG:3031 projection | **Real** | Exact WGS84 ellipsoidal projection, inverse-verified |
| Iceberg drift equations | **Real** | RK4 on the Bigg et al. (1997) momentum balance |
| **Model sea-ice concentration and thickness fields** | **Simulated** | Model/dashboard fields stand in for OSI-SAF OSI-401-b, AMSR2, Sentinel-1 SAR |
| **Regional-map sea-ice edge** | **Observed** | Copernicus Marine OSI SAF Antarctic categorical ice-edge classes with a same-time quality mask; stale observations are labeled |
| **Dashboard flow particles** | **Optional real data** | NOAA GFS 10 m wind forecast/analysis and Copernicus Marine surface-current analysis can be acquired explicitly; simulation remains a separately selected demo |
| **Temperature and wave fields** | **Simulated** | Stands in for ECMWF ERA5/HRES and Copernicus Marine CMEMS |
| **Radar returns** | **Simulated** | Radar-equation model standing in for a real X-band PPI |

**The models are real; the weather is simulated.** Every API response carrying a simulated field
sets `is_synthetic: true` and names the product it stands in for. Switching to live data is a
data-loader change, not a model change — the interfaces already match the real products.

### Real flow data (optional)

Real wind and current files are downloaded only by explicit commands and stored outside the
repository in the local ICEFLOW cache (`~/Library/Caches/ICEFLOW/flow` on macOS, or
`~/.cache/iceflow/flow` on Linux). Set `ICEFLOW_FLOW_CACHE_DIR` to use another directory.
The Polar map's layer panel lets you select NOAA GFS wind or Copernicus currents, choose one
shared UTC valid date for both, and switch between animated particles and static arrows. An
unavailable real source stays unavailable; it never silently uses the simulation.

```sh
# NOAA GFS 0.25° 10 m east/north wind; choose the model date, cycle, and forecast lead.
./.venv-test312/bin/python -m src.data.fetch_gfs_wind --date 2026-10-23 --cycle 00 --lead-hours 0

# Install the official Copernicus Marine Toolbox and configure credentials once (optional).
./.venv-test312/bin/python -m pip install -r requirements-optional.txt
./.venv-test312/bin/copernicusmarine login
# Core routing, physics and the UI work without optional dependencies; only real wind/current download needs them.
# Copernicus Marine daily surface-current uo/vo subset for the same UTC date.
./.venv-test312/bin/python -m src.data.fetch_copernicus_current --date 2026-10-23
```

GFS lead hour zero is labeled model analysis; positive leads are labeled forecast. Copernicus
subsetting requires a Copernicus Marine account and configured credentials. Both products use
eastward/northward velocity components in m/s on geographic latitude/longitude grids; returned
valid time, retrieval time, product, resolution, and stale status are shown in the flow legend.

---

## Quickstart

### Prerequisites

| | Version | Check with | If missing |
| :--- | :--- | :--- | :--- |
| Python | 3.11 or newer | `python --version` | [python.org/downloads](https://www.python.org/downloads/) |
| Node.js | 24 or newer | `node --version` | [nodejs.org](https://nodejs.org/) |
| Git | any | `git --version` | [git-scm.com](https://git-scm.com/) |

Nothing else. **No accounts, no cloud services, no database server, no Docker, no GPU.**
The core Antarctic chart is offline-capable; it runs on a laptop in aeroplane mode, which is the
point: the target user is on a ship below 60°S where there is no connectivity to depend on. The
optional *Regional* context map uses Mapbox and needs a token + network (see the map-layers
section); every other screen runs without either.

> On some systems Python is `python3` and pip is `pip3`. If `python --version` prints nothing or
> reports Python 2, use `python3` and `pip3` throughout.

### Clone and run

```bash
git clone https://github.com/sumonachatterjeebw-byte/sih2026.git
cd sih2026
```

Then take Option A or Option B below. Both have been verified from a clean clone on a machine
with nothing installed but Python and Node.

### Option A — one command

```powershell
# Windows (PowerShell)
.\start.ps1

# macOS, Linux, or Git Bash on Windows
./start.sh
```

It installs anything missing, starts the API, waits for it to warm its caches, then starts the
bridge console and tells you when to open the browser.

> **If PowerShell blocks the script** with an execution-policy error, either run
> `powershell -ExecutionPolicy Bypass -File .\start.ps1` once, or use Option B.

Useful flags: `.\start.ps1 -Check` runs the verification suite instead of serving, and
`-SkipInstall` skips dependency installation on later runs.

### Option B — two terminals, by hand

```bash
# Terminal 1 — backend.  Run from the repository root, not from inside src/.
pip install -r requirements.txt
uvicorn src.api.main:app --port 8000
#   API docs:  http://localhost:8000/docs

# Terminal 2 — bridge console
cd frontend
npm install          # first run only, takes a minute
npm run dev
#   Console:   http://localhost:5173
```

Then open **http://localhost:5173**.

> Add `--reload` to the uvicorn command while developing. Without it the server keeps running the
> code it started with, and edits to Python files will not take effect until you restart it.

**If a port is already taken**, use different ones. The frontend reads the backend location from
`frontend/vite.config.ts`, so change it there if you move the API:

```bash
uvicorn src.api.main:app --port 8001        # then set BACKEND in frontend/vite.config.ts
npm run dev -- --port 5174                  # the console can move freely
```

**To let others on your network reach it**, bind to all interfaces and share your machine's LAN
address:

```bash
uvicorn src.api.main:app --host 0.0.0.0 --port 8000
npm run dev -- --host
```

### What to expect on first run

| | |
| :--- | :--- |
| Backend answers requests | immediately |
| Cache warm-up finishes in the background | about 35 s |
| First route plan | about 12 s once warm, up to 30 s if you plan before warm-up completes |
| Voyage: press Start, first tick appears | about 12 s |

The waits are real computation, not loading spinners: planning runs two independent A\* searches
and integrates iceberg drift tracks. The interface names the stage it is working on while you
wait.

### Using it — three steps

The console opens on the **Voyage Planner**, where you choose an origin, destination and vessel.

1. **1. Plan a route** — pick an origin and an Indian Antarctic station, pick a ship, press
   **Plan voyage**. Cape Town → Bharati is the default and the one worth seeing first.
2. **2. Sail it** — press **Start voyage**. The ship sails the plan hour by hour: watch it slow
   as it meets the ice, and watch the alerts arrive.
3. **Simple view** (top right) toggles on the Ice Forecast, Iceberg Tracker and Analytics screens.

Every piece of jargon on screen — RIO, besetting, compression, CPA — carries its own plain-English
definition behind the **?** next to it.

### Terminal-only demonstration

No browser needed, and it exercises the same models:

```bash
python -m src.cli                 # POLARIS, Lindqvist, ice, icebergs, route, and a voyage
python -m src.cli --quick         # skip the voyage simulation
python -m src.cli --list          # available legs, vessels and stations
python -m src.cli --leg capetown_maitri
```

### Optional: the trained models

The machine-learning artefacts are **not committed** — they total about 13 MB and regenerate in
roughly four minutes:

```bash
python -m scripts.train           # trains all three, rewrites models/metrics.json
python -m scripts.train --quick   # faster, smaller datasets
```

**This is genuinely optional.** The physics path never depends on a trained model, and the system
runs identically without them. `/api/v1/health` reports which are present, and
`models/metrics.json` — which *is* committed — carries every measured metric so the results can be
checked without retraining.

### Regenerating the documentation

```bash
python -m scripts.make_report     # rebuilds the 20-page PDF from live model runs
```

Every figure in the report is computed when it is generated, so it cannot drift out of step with
the code.

**Want the whole thing in one document?**
**[docs/report/iceflow-Prototype-Report.pdf](docs/report/iceflow-Prototype-Report.pdf)**
covers the problem statement, what was built, how it helps, how it was built, the architecture,
the technology choices and the reasoning behind each, every measured result, the machine learning
including the two models that failed, and the honest limitations.

Presenting this to someone? **[docs/DEMO_SCRIPT.md](docs/DEMO_SCRIPT.md)** is a five-minute
walkthrough with the numbers, the order to show them in, and the questions worth rehearsing.

---

## Map layers added in Stage A: regional context, wind and current, observed bergs

**Regional context map.** The Plan and Sail charts have a switch between the Antarctic chart and a Mercator
*Regional context* map showing Africa, India and Australia, the ports, stations and the same route, with an
outline of what the polar chart is showing. Its land comes from Natural Earth (public domain), clipped to the
voyage region and simplified to about 4 km. **It is drawing data only**: it is never read by the land mask,
coastal clearance or the route optimiser. Build it once, on a machine with network access:

```bash
python -m scripts.build_regional_context
```

Certificate verification is never disabled. If the download fails on a certificate error the script prints
the fix (on a python.org Mac build, run `Install Certificates.command`). With no network, download
`ne_50m_land.geojson` and `ne_110m_admin_0_countries.geojson` in a browser and run
`python -m scripts.build_regional_context --land-file <path> --countries-file <path>`. Until the file exists,
the map says "Regional coastline not built" and still draws ports, stations and the route.
Commit `src/data/regional_context.json` if the demonstration machine will have no network.

**Wind and ocean-current particles.** Open the layer button (sliders icon) on any chart. The particles
animate the `u10/v10` and `current_u/current_v` fields from `/api/v1/env/field`. Those fields are
**simulated**, and the legend says so from the response's own `is_synthetic` flag. Colour is true speed; the
particle speed is a visual scale and differs between wind and current. The layers stop when their screen or
the browser tab is hidden, and show a still picture when the system asks for reduced motion.

**Sea ice.** The legend gives units, the five display classes and the grid-cell size. The layer panel adds
opacity, visibility, a *Classes* mode, a *Change vs +0 h* mode and the forecast time. A failed or missing ice
field is reported as missing, never as open water.

**Observed icebergs.** `data/raw/iceberg/AntarcticIcebergs_YYYYMMDD.csv` (the newest is used) is served at
`/api/v1/icebergs/observed` and drawn as a separate, hollow, dashed layer with its observation date and age.
Older than 7 days is flagged STALE. It is **not** merged into the simulated catalogue, not drifted forward, and
not used by routing or alerts. Its origin is not recorded in the repository, so it is labelled "USNIC-format".

Tests: `pytest tests/test_observed_icebergs.py tests/test_regional_context.py tests/test_stage_a_api.py`, and
`cd frontend && npm run test:unit` (Node 22.18 or newer; no extra dependency).

## Layout, regional map and browser tests (Stage B)

The map stage is a stable workspace, not a map with panels floating over it: a command bar (Plan), the map
cell (guaranteed at least 300 px tall), a result tray (Plan) and a tabbed bottom dock (Sail, Sea ice, Icebergs)
that shows one instrument panel at a time. Map controls live in one toolbar in the map's top-right corner, and
the legend starts collapsed to a one-line summary. Everything a map overlay needs is positioned inside the map
cell, so nothing can run underneath the dock.

Unit tests (no browser): `cd frontend && npm run test:unit` (Node 22.18 or newer).

Browser tests (Playwright). One-time setup, which also records the dependency in `package.json` and
`package-lock.json` (the Docker build uses `npm ci`, so the two must agree):

```bash
cd frontend
npm i -D @playwright/test
npx playwright install chromium
npm run test:e2e        # starts the backend and the dev server if they are not already running
```

The backend used by the tests defaults to `../.venv-test312/bin/python`; override with
`ICEFLOW_PYTHON=/path/to/python npm run test:e2e`. The specs check the layout at 1024x640, 1280x720, 1366x768,
1440x900 and 1920x1080, the regional map's zoom, pan, reset and keyboard behaviour, the wind and current layers
(including reduced motion, a failed request and a malformed response), and the sea-ice legend states.

## How to check the prototype is actually working

Six checks, in order. Each one prints something you can compare against the expected result, so
you can tell the difference between "it started" and "it works".

### 1. The test suite

```bash
python -m pytest tests/ -q
```

Expect **106 passed**. This covers the geodesy and its inverse projection, the land mask, ice
physics bounds, forecast skill against persistence, Lindqvist monotonicity, radar determinism,
and that the route optimiser's saving is consistent with its two route evaluations.

### 2. The backend is up and honest about itself

```bash
uvicorn src.api.main:app --port 8000
curl http://127.0.0.1:8000/api/v1/health
```

Expect `"status": "ok"` plus a `data_provenance` block naming, per layer, whether it is `real` or
`synthetic`. Interactive API docs are at **http://localhost:8000/docs**.

### 3. The land mask is real geometry, not a bounding box

```bash
curl "http://127.0.0.1:8000/api/v1/geo/point?lat=-70.7667&lon=11.7333"   # Maitri
curl "http://127.0.0.1:8000/api/v1/geo/point?lat=-60&lon=20"             # open ocean
```

Maitri returns `"is_land": true` — it sits about 80 km inland — and the open-ocean point returns
`false` with roughly 606 nm of coastal clearance. The `epsg3031` block round-trips back to the
input coordinates, which is the projection check.

### 4. The forecast beats persistence

```bash
curl "http://127.0.0.1:8000/api/v1/ice/forecast-skill"
```

Expect `skill_score_vs_persistence` **positive at every lead from 24 h**, rising to about +0.17 at
120 h. A forecast that cannot beat "assume nothing changes" is not a forecast, so this is the one
number that matters most.

### 5. A route is planned, and the saving is a real difference

```bash
python -m src.cli --quick     # then read section [5]
```

Expect roughly, for Cape Town to Bharati:

```
Ice-blind shortest navigable route     2853 nm   719 h   301 t   minRIO  6
POLARIS-constrained optimised route    3018 nm   306 h   292 t   minRIO 12
Fuel saved 2.83 %   Time saved 412.9 h (17.2 days)
```

The two routes are planned independently and both sailed through identical physics. Change the
leg to `--leg capetown_maitri` and the fuel saving goes **negative** — that is the system telling
the truth rather than a bug.

### 6. The bridge console renders

```bash
cd frontend && npm install && npm run dev
```

Open **http://localhost:5173**. You should see the Antarctic coastline in polar stereographic
projection with a sea-ice raster over it, and the amber provenance bar stating which layers are
simulated. Press **Plan voyage** on the Voyage Planner tab (allow 15 to 30 seconds), then
**Start voyage** on the Bridge Console to watch the ship sail, slow down in the ice, and raise
alerts.

`npm run build` should complete with **zero TypeScript errors**.

### Troubleshooting

| Symptom | Cause and fix |
| :--- | :--- |
| Frontend loads but every panel is empty | The backend is not running. The header will say **Backend offline**. Start it on port 8000. |
| `[Errno 10048] only one usage of each socket address` | Port 8000 is already taken, usually by a backend you started earlier. Reuse it, or stop it first. |
| Planning seems to hang | It is not hanging. The first plan is about 30 s while caches warm, roughly 12 s afterwards. The overlay names the stage being computed. |
| Python edits have no effect | `uvicorn` was started without `--reload`, so it is still running the code it loaded at start-up. Restart it. |
| `ModuleNotFoundError: src` | Run from the repository **root**, not from inside `src/`. |
| PowerShell refuses to run `start.ps1` | Execution policy. Use `powershell -ExecutionPolicy Bypass -File .\start.ps1`, or start the two servers by hand. |
| `/health` says the ML models are not trained | Expected on a fresh clone; the binaries are not committed. Run `python -m scripts.train`, or ignore it — the physics path does not use them. |
| The map area is blank | Should not happen; it was a real bug and is fixed. If it recurs, check the browser console and confirm the canvas has a non-zero height. |
| `Cannot find module '../lib/format'` when building | You are on a clone from before this was fixed. `git pull`. A stray `lib/` rule in `.gitignore` used to exclude `frontend/src/lib/` from the repository. |
| `npm install` reports vulnerabilities | Development-only dependencies of the build tooling. They do not ship in the bundle. Do not run `npm audit fix --force`; it will upgrade Vite across a major version and break the build. |
| `'python' is not recognized` | Use `python3` and `pip3`, or add Python to PATH. On Windows the Microsoft Store build sometimes registers only `python3`. |
| Port 5173 already in use | Vite will pick the next free port and print it. Use whatever it prints. |

## Deploying it somewhere other people can open

The system deploys as a single container serving both the FastAPI backend and the built React console from one origin, with no CORS setup or external dependencies.

> **Do not try to host the backend on Vercel Serverless Functions.** The Python dependencies total 262 MB against a 250 MB limit, the live voyage stream requires WebSockets which serverless functions do not support, voyage simulation state is held in process memory, and dual-route planning takes ~32 seconds of CPU.

### Deploy to Render (Free, recommended)

1. Sign in to [Render](https://render.com) with GitHub.
2. Click **New +** &rarr; **Blueprint**.
3. Select this repository. Render detects `render.yaml`, builds the container, and assigns a permanent public HTTPS URL.

### Run with Docker on any host

```bash
docker build -t ICEFLOW .
docker run -p 8000:8000 ICEFLOW
```

Open `http://localhost:8000`.

See **[docs/DEPLOYMENT.md](docs/DEPLOYMENT.md)** for architecture details, resource requirements, free-tier cold-start notes, and the split-deployment option.

---

## What the system actually does

### The problem

Every austral summer NCPOR sends the Indian Antarctic Expedition from Cape Town or Goa across
the Southern Ocean. Ships meet seasonal pack ice, katabatic storms, closing leads and calved
tabular icebergs. Getting it wrong means burning millions of litres of marine gas oil ramming
ice, missing a resupply window, or being beset — trapped in ice that has closed around the hull.
Ice charts today are largely manual and 12 to 24 hours old.

### The answer, in one screen

Plan a passage from Cape Town to Bharati. The system computes **two** routes and sails both
through identical physics:

```
Route                                       Distance    Time     Fuel   min RIO
Ice-blind shortest navigable route             2853 nm    719 h    301 t       6
POLARIS-constrained optimised route            3018 nm    306 h    292 t      12

Time saved   413 h  (17.2 days)
Fuel saved   2.84 %
Distance     +165 nm — the safe route is longer, and still far faster
```

That result is the whole argument. The optimised route sails **165 nautical miles further** and
arrives **17 days sooner**, because it goes around the thick ice instead of grinding through it,
and its worst-case POLARIS risk index is 12 instead of 6.

### The result we did not expect, and did not hide

Run the same comparison across three legs and the fuel story falls apart:

| Leg | Fuel saved | Transit time saved | Minimum RIO |
| :--- | ---: | ---: | :--- |
| Cape Town → Bharati | **+2.8%** | 413 h (17.2 d) | 6 → **12** |
| Cape Town → Maitri | **−8.0%** | 169 h (7.0 d) | 5 → **10** |
| Hobart → Bharati | **−2.4%** | 151 h (6.3 d) | 9 → **12** |

A negative number means the optimised route burns *more* fuel than the ice-blind one.

On two of three legs the safe route **burns more fuel**, because going around the ice adds
distance and the distance costs more than the ice avoided. What it buys instead is 6 to 17 days
of transit time and a materially better risk margin on every single leg.

We tried to make the fuel number look better by re-weighting the objective toward fuel. It
barely moved: on the Maitri leg the fuel penalty stays near 8% whichever way the weights are
set, because it is a property of the geography and the ice, not of the search.

**So the honest headline for this system is time and safety, not fuel.** The planner emits an
explicit warning whenever the optimised route costs more fuel than the ice-blind one, saying it
is being recommended because it is safer, not cheaper. There is no fixed percentage anywhere in
the codebase, which is exactly why the number is allowed to come out negative.

---

## Technology stack, and why each piece

### Backend

| Choice | Why this and not the obvious alternative |
| :--- | :--- |
| **Python 3.11** | The polar science ecosystem (xarray, NetCDF4, GDAL, Copernicus toolboxes) is Python. Ingesting real ERA5 and OSI-SAF products later means staying where those libraries live. |
| **FastAPI** | Pydantic v2 models give a typed schema and an OpenAPI document for free, so the frontend generates its types from the running server instead of guessing. WebSocket support is native, which the live voyage stream needs. |
| **Pydantic v2** | Validation at the boundary, and the same models serialise to the wire. An ice concentration above 1.0 or a negative thickness is rejected at the edge rather than corrupting a route. |
| **NumPy** | Every field is evaluated on grids of thousands of points. Vectorising the ice model and caching the static coast geometry took route planning from 24 seconds to 15, and the iceberg drift ensemble from 109 seconds to 4. |
| **SciPy** | `cKDTree` for distance-to-coast over 1698 coastline vertices. |
| **scikit-learn** | Trains in seconds on a CPU. A laptop demo cannot depend on a GPU, and a bridge PC does not have one. See the training section for why this was the right size of tool. |
| **SQLite** | The shipboard console is one rugged PC on a bridge with no infrastructure behind it. A file-backed database with WAL works there unchanged and works at NCPOR headquarters too. |
| **No PyTorch** | Considered and rejected. The trained models here are tabular; a deep network would add a heavy dependency, a GPU expectation and an ONNX export step for no measured gain. When the pipeline moves to real satellite rasters, a U-Net becomes the right call — that is documented as future work, not claimed as done. |

### Frontend

| Choice | Why |
| :--- | :--- |
| **React 18 + Vite + TypeScript (strict)** | Fast iteration, and strict typing against generated API types means a backend field rename breaks the build instead of the demo. |
| **Tailwind CSS** | A dense instrument panel needs consistent spacing and colour tokens more than it needs bespoke CSS. |
| **Custom `<canvas>` map engine** | **The most important decision in the frontend.** Mapbox, MapLibre and Leaflet all assume Web Mercator and a tile server. Web Mercator is unusable at 70°S, and a tile server is unreachable at sea. So the map is written from scratch: WGS84 projected to **EPSG:3031 Antarctic Polar Stereographic** in TypeScript, mirroring the backend projection exactly, drawing coastline vectors and the ice raster served by our own API. The result is correct at the pole and renders our own model output rather than someone else's basemap. The **Regional** map uses Mapbox and requires a Mapbox access token and network connectivity. |
| **Zustand + TanStack Query** | Server state (slow, cacheable route plans) and client state (layer toggles, playback) are genuinely different problems and get different tools. |
| **Recharts** | Charts as React components, so the analytics screen stays declarative. |

### What we deliberately did not use

- **No map tile provider** — offline capability is a hard requirement below 60°S.
- **No cloud services, no external APIs, no keys** — a clean checkout must run.
- **No Docker requirement** — `pip install` and `npm install` are fewer moving parts for a judge.

---

## Where we trained, what, and how

**Status:** synthetic-only; not validated. The models are **not used in routing**; they appear only in `/api/v1/health`.

| Model | Task | Status | Trained on | Operational skill validated | Beats best baseline (current metrics.json) | Used in routing |
| :--- | :--- | :--- | :--- | :--- | :--- | :--- |
| **Sea-ice concentration forecaster** (`sic_forecaster`) | Forecast concentration at t0 + lead from analysis state at t0 | demo_synthetic | synthetic | false | false | false |
| **Iceberg drift residual corrector** (`drift_residual`) | Correct iceberg drift position/error residuals | demo_synthetic | synthetic | false | false | false |
| **Growler vs sea clutter classifier** (`growler_classifier`) | Classify growlers vs sea clutter | demo_synthetic | synthetic | false | false | false |

**Real results (from `models/metrics.json`, mode: quick, 100% synthetic):**
- **SIC forecaster:** Loses to physics at all leads (overall skill vs physics −0.232, vs persistence −0.029). Does not beat best baselines.
- **Drift residual corrector:** Position error worse vs persistence (7.49 km → 8.02 km). Improvement negative.
- **Growler classifier:** Reports ~0.98 F1 but comes from the generator's own distributions relative to weak baselines; not validated.

**Training:** `python -m scripts.train` / `python -m scripts.train --quick` write `models/` and `models/metrics.json`. Full (non-quick) training takes ~4 min; command to regenerate full metrics (do **not** run unless asked): `python -m scripts.train` (without `--quick`). After running, ensure `evaluation_status` remains present as additive metadata.

**Python version:** 3.11 (Dockerfile and CI). `setup.py` allows `>=3.10` but that range is untested.

**Data provenance:** Training data is generated by `src/core/environment.py`, `src/core/sea_ice.py`, `src/core/iceberg_tracker.py` (synthetic stand-ins for ERA5/CMEMS, OSI-SAF/AMSR2, USNIC/BYU). All metrics are simulated-environment metrics, not operational skill. Dead links in prior text: `docs/ML_MODELS.md`, `docs/report/iceflow-Prototype-Report.pdf`, `docs/DEMO_SCRIPT.md`, `docs/DEPLOYMENT.md` are not present in this repo; removed/fixed in this section.


## How it works

```
                    +--------------------------------------------------+
                    |  BRIDGE CONSOLE  (React, EPSG:3031 canvas map)   |
                    |  5 screens, offline-capable, no tile server      |
                    +---------------+------------------+---------------+
                          REST      |                  |  WebSocket
                                    v                  v
                    +--------------------------------------------------+
                    |  FastAPI service                                 |
                    |  geo | env | ice | risk | resistance | icebergs  |
                    |  route | voyage | radar | export | telemetry     |
                    +---------------+----------------------------------+
                                    v
    +---------------------------------------------------------------------------+
    |  PHYSICS CORE                                                             |
    |                                                                           |
    |  environment.py   westerlies, katabatic outflow, ACC, synoptic lows       |
    |  sea_ice.py       concentration, Stefan thickness, drift, divergence,     |
    |                   semi-Lagrangian forecast, verification harness          |
    |  polaris_risk.py  IMO MSC.1/Circ.1519 risk index                          |
    |  lindqvist_model  crushing + bending + submergence, attainable speed      |
    |  iceberg_tracker  RK4 momentum balance, melt, perturbed ensembles, CPA    |
    |  route_optimizer  risk-constrained A*, honest baseline comparison         |
    |  growler_radar    X-band PPI with real misses and false alarms            |
    |  voyage.py        hour-by-hour simulation, alerts, re-routing             |
    +---------------------------------------------------------------------------+
                                    v
    +---------------------------------------------------------------------------+
    |  DATA: Natural Earth coastline | NCPOR stations | USNIC bergs | SQLite    |
    +---------------------------------------------------------------------------+
```

### The five things that make it credible

**1. Speed is an output, not an assumption.** Every route edge solves the Lindqvist power and
propeller-thrust balance for the speed the ship can actually make. In 1.0 m ice at 6/10
concentration the *Vasiliy Golovnin* makes 6.2 knots on 5.3 MW. In 2.0 m ice at 8/10 she is
beset, and the planner routes around it.

**2. The saving is measured, not multiplied.** The v0.1 prototype computed
`baseline = optimised × 1.22` and reported "22% saved" — a constant dressed as a result. Now two
routes are planned and both are sailed through identical physics. The difference is the saving,
and across three legs the fuel saving ranges from **+2.8% to −8.0%** while transit time saved
ranges from 151 to 413 hours. A measurement that is allowed to come out negative is the
difference between a result and a slogan.

**3. The land mask is real.** 97 Natural Earth polygons answer 25,000 point-in-polygon queries
per second. A waypoint cannot be placed on the continent. Because Maitri is 80 km inland, each
station carries a validated seaward **anchorage** — ships route to India Bay, not to the station.

**4. The forecast is verified against persistence.** Any forecast must beat "assume nothing
changes" or it is not a forecast. Ours does, from 24 hours out:

| Lead | Forecast RMSE | Persistence RMSE | Skill | IIEE |
| ---: | ---: | ---: | ---: | ---: |
| 24 h | 0.081 | 0.088 | +0.076 | 0.046 |
| 48 h | 0.110 | 0.128 | +0.146 | 0.054 |
| 72 h | 0.126 | 0.151 | +0.164 | 0.050 |
| 120 h | 0.138 | 0.166 | +0.173 | 0.050 |
| 168 h | 0.152 | 0.182 | +0.164 | 0.058 |

**5. The bandwidth claim is measured.** Both payloads are built, serialised and gzipped, and the
byte counts are real: a full raster is 66 KB, the contour payload is **6.2 KB**, and four updates
a day total **23.4 KB** against the 50 KB Iridium Certus budget.

### Answers to the questions judges actually ask

**"How do you know ice thickness without altimetry?"** CryoSat-2 and ICESat-2 have narrow swaths
and long repeat cycles, so they cannot support tactical navigation. Thickness comes from
**Stefan's Law growth on accumulated Freezing Degree Days**, plus a dynamic ridging term where
the drift field converges. That is what operational ice services do. Pure Stefan growth diverges
as √FDD and would predict 3 to 4 m by late season, which is wrong for the Antarctic, so growth
saturates near 1.55 m where oceanic heat flux balances conduction through the ice and its snow.

**"What if a lead closes behind us?"** The drift field's divergence `∇·v` is computed by central
differences and mapped to a **compression index**. Convergent regimes are penalised in the route
cost and raise a `COMPRESSION_BESETTING` alert during a voyage.

**"What about growlers the satellites miss?"** A separate near-field layer. The simulated X-band
radar reports **misses**: a representative pack-ice sweep has 39 real targets, paints 13, and
misses 26 — one of them inside the 3 nm alert perimeter. Growler detection range collapses from
3.0 nm in calm water to 0.6 nm in saturated clutter. Reporting that honestly is the point.

**"You cannot install software in a certified ECDIS."** Correct. This runs on a separate console
and exports **GPX 1.1**, GeoJSON and an S-411-shaped ice overlay over the ship's LAN, which the
ECDIS loads read-only. The S-411 export is explicitly labelled a representative subset, not a
certified encoding.

---

## Repository layout

```
src/
  core/
    constants.py        every physical constant, with citations
    geo.py              haversine, bearings, EPSG:3031 forward and inverse
    noise.py            seeded Perlin noise for realistic field structure
    environment.py      synthetic Southern Ocean atmosphere and ocean
    sea_ice.py          concentration, thickness, drift, divergence, forecast, verification
    polaris_risk.py     IMO MSC.1/Circ.1519 risk index
    lindqvist_model.py  ice resistance, powering, attainable speed, vessel presets
    iceberg_tracker.py  RK4 drift, deterioration, ensembles, closest approach
    route_optimizer.py  risk-constrained A* and the honest baseline
    growler_radar.py    X-band PPI simulation with misses and false alarms
    voyage.py           hour-by-hour voyage engine and alerting
  ml/                   trained models, datasets, registry
  data/                 coastline, stations, iceberg catalogue, land mask
  services/             SQLite store, exporters, bandwidth measurement
  api/                  FastAPI app and routers
  cli.py                terminal demonstration
frontend/               React bridge console
scripts/train.py        trains every model, writes models/metrics.json
docs/                   architecture, POLARIS manual, datasets, ML models, build spec
tests/                  pytest suite
```

---

## API

Interactive documentation at `http://localhost:8000/docs`.

| Method | Path | Purpose |
| :--- | :--- | :--- |
| GET | `/api/v1/health` | model versions, data provenance, ML status |
| GET | `/api/v1/geo/coastline` | Antarctic land polygons (the planner's land mask) |
| GET | `/api/v1/geo/stations` | stations, ports and their navigable anchorages |
| GET | `/api/v1/env/sample` · `/env/field` | wind, current, temperature, sea state |
| GET | `/api/v1/ice/point` · `/ice/field` | concentration, thickness, drift, compression |
| GET | `/api/v1/ice/forecast-skill` | RMSE, IIEE and skill against persistence |
| POST | `/api/v1/risk/polaris` | Risk Index Outcome with per-component arithmetic |
| GET | `/api/v1/risk/matrix` | the full POLARIS risk-value table |
| POST | `/api/v1/resistance/calculate` | Lindqvist resistance, power, fuel, CO₂ |
| GET | `/api/v1/resistance/attainable-speed` | the speed the ship can actually make |
| GET | `/api/v1/vessels` | vessel presets |
| GET | `/api/v1/icebergs` | catalogue, optionally drift-propagated |
| POST | `/api/v1/icebergs/predict-drift` | RK4 ensemble drift with uncertainty |
| POST | `/api/v1/route/optimize` | full plan plus the measured baseline comparison |
| POST | `/api/v1/route/compare` | optimised, ice-blind and great-circle side by side |
| POST | `/api/v1/voyage` | create a voyage |
| POST | `/api/v1/voyage/{id}/step` | advance simulated hours |
| POST | `/api/v1/voyage/{id}/reroute` | re-plan from the present position |
| WS | `/api/v1/ws/voyage/{id}` | live tick and alert stream |
| GET | `/api/v1/export/{id}.{geojson,gpx,csv,s411}` | ECDIS-ready exports |
| GET | `/api/v1/telemetry/bandwidth` | the measured satellite budget |

Backwards compatible: every v0.1 endpoint and request body still works.

---

## Feasibility and viability

**Technical.** Every input the production system needs is a mature, free, operationally-supported
data product: OSI-SAF OSI-401-b, AMSR2, Sentinel-1 SAR, ECMWF ERA5/HRES, Copernicus Marine, and
the USNIC iceberg database. Nothing here depends on a commercial feed or a research prototype.
The models run on CPU — no GPU appears anywhere in the stack — because the target hardware is a
ruggedised PC on a ship's bridge.

**Operational.** Maritime regulation forbids installing unapproved software inside a
type-approved ECDIS. The console therefore runs on separate hardware and exports **GPX 1.1**,
GeoJSON and an S-411-shaped ice overlay over the ship's LAN, which the ECDIS loads read-only.
Communications are the other hard constraint: south of 60°S there is no geostationary coverage,
so the system is built to work over Iridium Certus at a **measured 23.4 KB/day**.

**Economic.** Open-source stack, no per-voyage licence, and no commercial weather-routing
subscription. On the Cape Town to Bharati leg the modelled fuel difference alone is about
₹5.8 lakh, but the material saving is charter time: **17 days**.

### Risks, and what the build actually does about each

| Risk | Mitigation, as implemented |
| :--- | :--- |
| Polar night and cloud make optical sensors useless for months | The design relies on C-band SAR and passive microwave, which are unaffected by darkness or cloud. No optical product is in the critical path. |
| Satellite bandwidth below 60°S | Contours and deltas instead of rasters, **measured** at 23.4 KB/day against a 50 KB budget. |
| A lead closes behind the ship | Drift-field divergence gives a compression index; convergent regimes are penalised in the route cost and raise a `COMPRESSION_BESETTING` alert under way. |
| Growlers are invisible to satellites | A separate near-field radar layer that reports its own misses — 26 of 39 real targets undetected in a representative pack-ice sweep. |
| The forecast is wrong on arrival | The voyage engine resamples conditions at the ship's actual arrival time and re-plans from the present position when a hard constraint is violated. |
| Ice thickness cannot be measured tactically | Thermodynamic derivation from Freezing Degree Days plus dynamic ridging, which is what operational ice services do. |

---

## Impact and benefits

**For NCPOR and the expedition.** Mission assurance for the annual Indian Antarctic Expedition.
The measured result across three legs is **151 to 413 hours of transit time saved** and a better
worst-case POLARIS index on every leg — 6→12, 5→10 and 9→12. Charter time is the dominant cost of
a polar resupply, so days are worth more than tonnes.

**For the ice navigator.** Replaces a 12-to-24-hour-old manual ice chart with a quantitative risk
surface, a speed that is derived from hull physics rather than assumed, and alerting that names
the hazard and the action.

**Safety.** The optimiser refuses to route through ice where POLARIS prohibits operation, and it
refuses cells where the ship cannot make way at all. In testing it lifted the closest approach to
a 32 km tabular berg from 3.0 nm — inside the berg — to 160 nm.

**Environmental.** CO₂ is reported per voyage at 3.206 kg per kg of MGO. Shorter transits mean
less time operating in Antarctic Specially Protected Areas, and the Polar Code heavy-fuel-oil
carriage ban is respected by construction, since the fuel model is MGO throughout.

**Strategic.** An open, auditable, offline-capable stack with no foreign commercial dependency,
supporting India's obligations under the Antarctic Act, 2022.

---

## Honest limitations

1. **Environmental fields are synthetic.** Skill figures are simulated-environment figures.
2. **Two of three trained models lose to their physics baselines** and are not used in the
   serving path. See above; the reasoning is in `docs/ML_MODELS.md`.
3. **Route optimality is approximate in time.** Edge costs depend on arrival time, and each node
   carries the arrival time of the best path found so far — standard in weather routing, but a
   label-correcting approximation rather than a proof of optimality.
4. **Forecasts are clamped at 240 hours.** Longer passages use climatology beyond that, which is
   correct — nobody can forecast ice 30 days out — but it means very slow baseline routes are
   evaluated against climatology in their later legs.
5. **The S-411 export is not certified.** It is a representative attribute subset.
6. **Vessel hull angles, block coefficients and SFOC are engineering estimates**, marked as such
   in the source. Principal dimensions and installed power are published figures.
7. **We do not reproduce the 15–22% fuel reduction** claimed in the original blueprint. That
   figure came from the literature, not from this system. What our models measure is a fuel
   saving between +2.8% and −8.0%, alongside 151 to 413 hours of transit time saved and a better
   minimum RIO on every leg. On two of three legs the safe route costs more fuel, and the system
   says so rather than burying it.

---

## References

1. IMO Resolution MSC.385(94) — *International Code for Ships Operating in Polar Waters*.
2. IMO MSC.1/Circ.1519 — *Polar Operational Limit Assessment Risk Indexing System (POLARIS)*.
3. Lindqvist, G. (1989). "A straightforward method for calculation of ice resistance of ships."
   *POAC 89*, Luleå, 722–735.
4. Fan, T. et al. (2019). "Comparative analysis of ice resistance prediction methods."
   *Advances in Polar Science*, 30(4).
5. Bigg, G. R. et al. (1997). "Modelling the dynamics and thermodynamics of icebergs."
   *Cold Regions Science and Technology*, 26(2), 113–135.
6. Rackow, T. et al. (2017). "A simulation of small to giant Antarctic iceberg evolution and drift."
   *JGR Oceans*, 122(4), 3170–3190.
7. El-Tahan, M. et al. (1987). "Estimation of iceberg deterioration." *Cold Regions Science and Technology*.
8. Andersson, T. R. et al. (2021). "Seasonal Arctic sea ice forecasting with probabilistic deep
   learning." *Nature Communications*, 12, 5124.
9. Timco, G. W. & Weeks, W. F. (2010). "A review of the engineering properties of sea ice."
   *Cold Regions Science and Technology*, 60(2), 107–129.
10. Anderson, D. L. (1961). "Growth rate of sea ice." *Journal of Glaciology*, 3(30), 1170–1172.

---

Built for **Smart India Hackathon 2026**, problem statement 26059, for the Ministry of Earth
Sciences and the National Centre for Polar and Ocean Research.

### CORS / deployment

- **Same-origin (Render/Docker):** When FastAPI serves `frontend/dist`, no CORS is needed. By default (no `ICEFLOW_CORS_ORIGINS` and `ICEFLOW_ENV` not `dev`), no `CORSMiddleware` is added (same-origin only).
- **Local dev:** `start.sh` and `start.ps1` set `ICEFLOW_ENV=dev` for the API automatically, which adds a permissive (`allow_origins=["*"]`, `allow_credentials=False`) CORS middleware. The Vite dev proxy also makes `/api` calls same-origin, so the bridge console on `:5173` can reach the API on `:8000` without extra config. `allow_credentials` is never combined with `*`.
- **Tile URLs are same-origin by default:** Copernicus sea-ice tile templates are emitted by the API as relative `/api/v1/...` paths, so they route through the Vite proxy in dev and through same-origin serving in production. No CORS is required for the tiles themselves in either case.
- **Vercel-hosted frontend calling a separate API:** Set `VITE_API_BASE_URL` in the frontend build (e.g. `https://iceflow-api.example.com`) so `client.ts` qualifies the relative tile template with that origin. That split deployment also requires the backend to run with `ICEFLOW_CORS_ORIGINS` set to a comma-separated list of allowed origins (e.g. `https://your-app.vercel.app`); without it the tile requests (and all API calls) are same-origin only. `allow_credentials` is only enabled when the origins list does not contain `*`. See `frontend/src/api/client.ts` (`resolveTileTemplate`).

## Evaluation on real data

**Status:** Baselines only; no ML model has been evaluated on real data.

This section will be populated by running `python -m scripts.eval_sic` on real NSIDC G10016 V4 observations (downloaded explicitly via `python -m scripts.fetch_real_sic`). The harness evaluates honest baselines (persistence, damped-anomaly persistence, climatology with/without trend fitted on training years only) with leakage-proof splits, 95% bootstrap CIs resampled by blocks of days, IIEE at 15% (Goessling et al. 2016) weighted by cell area, reported over all ocean cells and over the variable-ice zone (5-95% climatology) with the latter as headline. Leads: 1, 3, 7, 14 days; all seasons and austral departure season (Nov-Mar); sectors: Weddell Sea (-60W to 20E), Indian Ocean (20E to 90E, includes Prydz Bay/Bharati), Western Pacific (90E to 160E), Ross Sea (160E to 130W), Bellingshausen-Amundsen (130W to 60W). Maitri approach (~12E) is in the Weddell sector. Gaps are never interpolated silently; n reported per cell. 2016-2023 regime change makes extrapolated trends unreliable.

**Sensor caveat:** G02202 V6 uses AMSR2 from 1 Jan 2025 onward (different sensor). The held-out test block must end by 31 Dec 2024. Data from 2025 onward is reported separately and labeled as a different-sensor period.
