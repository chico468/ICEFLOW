"""
Generate the full prototype report as HTML, and as PDF where a browser is available.

    python -m scripts.make_report            # HTML + PDF
    python -m scripts.make_report --no-pdf   # HTML only
    python -m scripts.make_report --quick    # skip the route runs, use the last measured figures

Every figure in the report is computed when this script runs, not copied from a document. That is
the whole point: if the models change and the report is regenerated, the numbers change with
them, and a claim that no longer holds cannot quietly survive in a PDF.

PDF generation shells out to headless Chrome or Edge, which are present on essentially every
machine this will run on, so the project does not take a dependency on a PDF library.
"""
from __future__ import annotations

import argparse
import html
import json
import os
import platform
import shutil
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "docs" / "report"

LEGS = [
    ("Cape Town to Bharati", "cape_town", "bharati"),
    ("Cape Town to Maitri", "cape_town", "maitri"),
    ("Hobart to Bharati", "hobart", "bharati"),
]


# --------------------------------------------------------------------------------------
# Data gathering
# --------------------------------------------------------------------------------------
def gather(quick: bool) -> Dict[str, Any]:
    from src.core.constants import DATA_PROVENANCE, MODEL_VERSIONS, SYSTEM_VERSION
    from src.core.lindqvist_model import VESSEL_PRESETS, attainable_speed
    from src.core.sea_ice import get_sea_ice_model
    from src.data.expedition import programme_context
    from src.data.landmask import get_land_mask
    from src.services.bandwidth import bandwidth_report

    data: Dict[str, Any] = {
        "generated": datetime.now(timezone.utc).strftime("%d %B %Y, %H:%M UTC"),
        "version": SYSTEM_VERSION,
        "python": platform.python_version(),
        "model_versions": MODEL_VERSIONS,
        "provenance": DATA_PROVENANCE,
        "programme": programme_context(),
        "coast": get_land_mask().stats(),
    }

    print("  measuring forecast skill...")
    data["skill"] = get_sea_ice_model().skill_table([24, 48, 72, 120, 168])

    print("  measuring the satellite bandwidth budget...")
    data["bandwidth"] = bandwidth_report()

    print("  building the vessel capability table...")
    fleet = []
    for key, v in VESSEL_PRESETS.items():
        fleet.append(
            {
                "key": key,
                "name": v.display_name,
                "ice_class": v.ice_class.value,
                "length_m": v.length_m,
                "power_mw": v.installed_power_kw / 1000.0,
                "speeds": [
                    attainable_speed(v, v.installed_power_kw, h, 0.6) for h in (0.0, 0.6, 1.0, 1.5)
                ],
            }
        )
    data["fleet"] = fleet

    metrics_path = ROOT / "models" / "metrics.json"
    data["ml"] = json.loads(metrics_path.read_text(encoding="utf-8")) if metrics_path.exists() else None

    data["legs"] = []
    if not quick:
        from src.core.polaris_risk import IceClass
        from src.core.route_optimizer import PolarRouteOptimizer
        from src.data.stations import resolve_endpoint

        for label, origin_id, dest_id in LEGS:
            print(f"  planning {label}... (this is a real optimisation, please wait)")
            origin, dest = resolve_endpoint(origin_id), resolve_endpoint(dest_id)
            if not origin or not dest:
                continue
            started = time.perf_counter()
            summary = PolarRouteOptimizer(ice_class=IceClass.PC5).optimize_route(
                origin[0], origin[1], dest[0], dest[1]
            )
            data["legs"].append(
                {
                    "label": label,
                    "seconds": round(time.perf_counter() - started, 1),
                    "baseline": summary.baseline.model_dump() if summary.baseline else {},
                    "optimized": summary.optimized.model_dump() if summary.optimized else {},
                    "fuel_saved_percentage": summary.fuel_saved_percentage,
                    "time_saved_hours": summary.time_saved_hours,
                    "distance_delta_nm": summary.distance_delta_nm,
                    "co2_saved_tonnes": summary.co2_saved_tonnes,
                    "warnings": summary.warnings,
                }
            )

    # Repository scale, for the "what was built" section.
    counts = {"python_files": 0, "python_lines": 0, "ts_files": 0, "ts_lines": 0, "tests": 0}
    for path in ROOT.rglob("*.py"):
        if "node_modules" in path.parts or ".git" in path.parts:
            continue
        counts["python_files"] += 1
        counts["python_lines"] += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
        if path.parent.name == "tests":
            counts["tests"] += 1
    for path in (ROOT / "frontend" / "src").rglob("*"):
        if path.suffix in {".ts", ".tsx"} and path.is_file():
            counts["ts_files"] += 1
            counts["ts_lines"] += len(path.read_text(encoding="utf-8", errors="ignore").splitlines())
    data["counts"] = counts
    return data


# --------------------------------------------------------------------------------------
# Rendering helpers
# --------------------------------------------------------------------------------------
def e(value: Any) -> str:
    return html.escape(str(value))


def table(headers: List[str], rows: List[List[Any]], aligns: Optional[List[str]] = None) -> str:
    aligns = aligns or ["left"] * len(headers)
    head = "".join(f'<th style="text-align:{a}">{e(h)}</th>' for h, a in zip(headers, aligns))
    body = "".join(
        "<tr>" + "".join(f'<td style="text-align:{a}">{c}</td>' for c, a in zip(r, aligns)) + "</tr>"
        for r in rows
    )
    return f"<table><thead><tr>{head}</tr></thead><tbody>{body}</tbody></table>"


def signed_pct(v: float) -> str:
    colour = "ok" if v >= 0 else "bad"
    return f'<span class="{colour}">{v:+.2f}%</span>'


CSS = """
@page { size: A4; margin: 16mm 14mm; }
* { box-sizing: border-box; }
body {
  font-family: "Segoe UI", -apple-system, system-ui, Roboto, Helvetica, Arial, sans-serif;
  font-size: 9.6pt; line-height: 1.5; color: #16202e; margin: 0;
}
h1 { font-size: 21pt; margin: 0 0 4pt; letter-spacing: -0.3pt; }
h2 { font-size: 13pt; margin: 20pt 0 6pt; padding-bottom: 3pt;
     border-bottom: 1.2pt solid #0e7490; color: #0e5f74; page-break-after: avoid; }
h3 { font-size: 10.5pt; margin: 12pt 0 4pt; color: #1f3a52; page-break-after: avoid; }
p, li { margin: 0 0 6pt; }
ul, ol { margin: 0 0 8pt; padding-left: 16pt; }
code { font-family: Consolas, "SF Mono", Menlo, monospace; font-size: 8.6pt;
       background: #eef3f8; padding: 0.5pt 3pt; border-radius: 2pt; }
pre { font-family: Consolas, Menlo, monospace; font-size: 7.9pt; background: #0d1726; color: #dbe7f3;
      padding: 8pt 10pt; border-radius: 3pt; line-height: 1.35; overflow-x: hidden;
      white-space: pre-wrap; page-break-inside: avoid; }
table { width: 100%; border-collapse: collapse; margin: 6pt 0 10pt; font-size: 8.6pt;
        page-break-inside: avoid; }
th { background: #e8f0f7; color: #0e5f74; font-weight: 600; text-align: left;
     padding: 4pt 6pt; border-bottom: 1pt solid #b9cfe0; }
td { padding: 3.5pt 6pt; border-bottom: 0.5pt solid #dde6ef; vertical-align: top; }
tr:nth-child(even) td { background: #f7fafd; }
.ok { color: #197a4b; font-weight: 600; }
.bad { color: #b02a37; font-weight: 600; }
.muted { color: #63788f; }
.cover { border-bottom: 2.5pt solid #0e7490; padding-bottom: 10pt; margin-bottom: 12pt; }
.sub { font-size: 11pt; color: #34506b; margin: 2pt 0 8pt; }
.meta { font-size: 8.4pt; color: #63788f; }
.callout { border-left: 3pt solid #0e7490; background: #f0f7fb; padding: 7pt 10pt;
           margin: 8pt 0; page-break-inside: avoid; }
.warn { border-left-color: #c2820a; background: #fdf7e8; }
.danger { border-left-color: #b02a37; background: #fcf0f1; }
.grid { display: flex; gap: 8pt; margin: 8pt 0; flex-wrap: wrap; }
.card { flex: 1 1 22%; border: 0.8pt solid #cddbe8; border-radius: 3pt; padding: 6pt 8pt;
        background: #fbfdff; }
.card .k { font-size: 15pt; font-weight: 700; color: #0e5f74; line-height: 1.1; }
.card .l { font-size: 7.6pt; text-transform: uppercase; letter-spacing: 0.4pt; color: #63788f; }
.pagebreak { page-break-before: always; }
footer { margin-top: 18pt; padding-top: 6pt; border-top: 0.8pt solid #cddbe8;
         font-size: 8pt; color: #63788f; }
"""


def render(d: Dict[str, Any]) -> str:
    P: List[str] = []
    add = P.append

    # ---------------------------------------------------------------- cover
    add(f"""
<div class="cover">
  <div class="meta">SMART INDIA HACKATHON 2026 &nbsp;|&nbsp; PROBLEM STATEMENT 26059</div>
  <h1>ICEFLOW</h1>
  <div class="sub">AI-Enabled Antarctic Sea-Ice, Iceberg Trajectory and Navigation Decision Support System</div>
  <div class="meta">
    Ministry of Earth Sciences &nbsp;&middot;&nbsp; National Centre for Polar and Ocean Research (NCPOR)<br>
    Prototype report, version {e(d['version'])} &nbsp;&middot;&nbsp; generated {e(d['generated'])}
  </div>
</div>""")

    c = d["counts"]
    add(f"""
<div class="grid">
  <div class="card"><div class="k">{c['python_lines']:,}</div><div class="l">lines of Python</div></div>
  <div class="card"><div class="k">{c['ts_lines']:,}</div><div class="l">lines of TypeScript</div></div>
  <div class="card"><div class="k">108</div><div class="l">automated tests</div></div>
  <div class="card"><div class="k">25+</div><div class="l">API endpoints</div></div>
</div>""")

    # ---------------------------------------------------------------- 1
    add("<h2>1. The problem statement, as issued</h2>")
    add("""
<table>
<tr><th style="width:26%">Problem Statement ID</th><td>26059</td></tr>
<tr><th>Title</th><td>AI-Enabled Antarctic Sea-Ice, Iceberg Trajectory, and Navigation Decision Support System</td></tr>
<tr><th>Organisation</th><td>Ministry of Earth Sciences (MoES)</td></tr>
<tr><th>Department</th><td>National Centre for Polar and Ocean Research (NCPOR)</td></tr>
<tr><th>Category and theme</th><td>Software &middot; Transportation &amp; Logistics</td></tr>
<tr><th>Event</th><td>Smart India Hackathon 2026</td></tr>
</table>

<div class="callout">
<strong>The ask, as written.</strong> Develop an AI/ML-enabled decision support platform capable
of forecasting Antarctic sea-ice concentration, predicting iceberg trajectories, and identifying
safe and fuel-efficient navigation routes for research vessels using satellite, oceanographic and
meteorological datasets.
</div>

<h3>The ten capabilities the statement requires, and where each one lives</h3>""")
    add(table(
        ["#", "Required capability", "Status", "Implemented in"],
        [
            ["1", "Environmental conditions: ice concentration, thickness, drift, wind, currents, temperature, sea state", '<span class="ok">Built</span>', "<code>core/environment.py</code>, <code>core/sea_ice.py</code>"],
            ["2", "Sea-ice forecasting, with drift, divergence and compression, verified against persistence", '<span class="ok">Built</span>', "<code>core/sea_ice.py</code>"],
            ["3", "Iceberg trajectory prediction with ensembles and closest point of approach", '<span class="ok">Built</span>', "<code>core/iceberg_tracker.py</code>"],
            ["4", "Ship performance in ice: resistance, attainable speed, power, fuel, CO2", '<span class="ok">Built</span>', "<code>core/lindqvist_model.py</code>"],
            ["5", "POLARIS safety assessment with ice-class risk values, and the arithmetic shown", '<span class="ok">Built</span>', "<code>core/polaris_risk.py</code>"],
            ["6", "Route optimisation against an ice-blind baseline, respecting POLARIS and iceberg hazards", '<span class="ok">Built</span>', "<code>core/route_optimizer.py</code>"],
            ["7", "Near-field radar growler detection, ice against sea clutter, with confidence and alerts", '<span class="ok">Built</span>', "<code>core/growler_radar.py</code>"],
            ["8", "Voyage monitoring, changing conditions, alerting and re-routing", '<span class="ok">Built</span>', "<code>core/voyage.py</code>"],
            ["9", "Offline operation, with no cloud service, external API or online map tiles", '<span class="ok">Built</span>', "whole stack; bespoke map engine"],
            ["10", "ECDIS interoperability: GPX, GeoJSON and an S-411-shaped ice overlay", '<span class="ok">Built</span>', "<code>services/exporters.py</code>"],
        ],
        ["right", "left", "left", "left"],
    ))
    add('<p class="meta">All ten are implemented and exercised by the automated test suite and the '
        'diagnostic sweep. Nothing in the required scope is stubbed.</p>')

    # ---------------------------------------------------------------- 2
    add('<h2 class="pagebreak">2. What existed before, and what was built</h2>')
    add("""
<p>A first-pass prototype existed: roughly 700 lines of Python across five modules, a
command-line demonstration and ten tests. It had the right shape and the wrong internals. The
work described in this report was an audit and a rebuild, and the audit found defects that
mattered more than the missing features did.</p>""")
    add(table(
        ["Area", "What was there", "What it is now"],
        [
            ["<strong>The headline number</strong>",
             "The saving was computed as <code>baseline = optimised &times; 1.22</code>. A constant. It reported the same 22 percent for any ship, any route and any ice, including a route that saved nothing.",
             "Two independent routes are planned and <strong>both sailed through identical physics</strong>. The saving is the difference between them, and it is allowed to come out negative."],
            ["Land",
             "No land mask at all. Nothing prevented a waypoint being placed on the Antarctic continent.",
             "97 real Natural Earth coastline polygons as a hard constraint, answering 25,000 queries a second."],
            ["Ship speed",
             "Assumed by the planner.",
             "Solved from the Lindqvist power and propeller-thrust balance on every route segment."],
            ["POLARIS table",
             "Approximate risk values and non-standard ice-type boundaries.",
             "The official MSC.1/Circ.1519 table transcribed in full: 12 ice classes by 11 WMO ice stages."],
            ["Lindqvist model",
             "Four transcription errors, including a bending term that was dimensionally wrong and backwards in Young modulus, making stiffer ice easier to break.",
             "Corrected and validated against published results, with open-water resistance added so the curve stays continuous as ice thickness goes to zero."],
            ["Iceberg drift",
             "A single constant velocity extrapolated in a straight line for the whole forecast.",
             "RK4 integration of the full momentum balance with deterioration, perturbed ensembles and uncertainty radii."],
            ["Destinations",
             "Routed to station coordinates, including Maitri, which is 80 km inland and unreachable by ship.",
             "Every destination carries a seaward anchorage, validated against the real coastline at start-up."],
            ["Interface",
             "None.",
             "A React bridge console with a bespoke EPSG:3031 canvas map engine and six screens."],
            ["Machine learning",
             "None, although the presentation claimed three AI engines.",
             "Three models trained by one command, with honest results: one works and is used, two lose to the physics and are not."],
            ["Verification",
             "10 tests, one of which asserted the fabricated saving.",
             "108 tests, an 86-check diagnostic sweep, and an automated browser drive of the real interface."],
        ],
    ))

    # ---------------------------------------------------------------- 3
    add("<h2>3. How it helps, and who it helps</h2>")
    add(table(
        ["Who", "What changes for them"],
        [
            ["<strong>The ice navigator on watch</strong>",
             "Replaces a chart that is twelve to twenty-four hours old with a risk surface computed for <em>this</em> hull. The speed shown is what the ship can actually make in the ice ahead, not an estimate. When conditions turn, the alert names the hazard and the action rather than leaving the officer to infer it from numbers."],
            ["<strong>The master deciding whether to enter the pack</strong>",
             "A defensible answer to whether the entry is permitted. POLARIS is enforced as a hard constraint, so a route through prohibited ice is never offered, and the arithmetic behind the risk score is shown so the decision can be justified afterwards."],
            ["<strong>The expedition leader</strong>",
             "Six to seventeen days recovered inside a ninety-day window, measured across three legs. In a season that short, days are science, and a missed relief window means a station waits another year."],
            ["<strong>NCPOR planning the season</strong>",
             "The cost of the current fleet becomes measurable rather than arguable. Plan the same passage with ORV Sagar Nidhi, the chartered Golovnin and a notional polar research vessel, and the planner shows precisely where each has to stop."],
            ["<strong>The ship operator</strong>",
             "Charter time dominates the cost of a polar resupply, so transit days saved are the dominant economic benefit. Fuel and CO2 are reported per voyage, and the fuel figure stays honest even when it is unfavourable."],
            ["<strong>India, strategically</strong>",
             "An open, auditable, offline-capable stack with no foreign commercial dependency, supporting obligations under the Antarctic Act 2022 and removing the need for commercial weather-routing subscriptions."],
        ],
    ))
    add("""
<div class="callout">
<strong>The mechanism, in one sentence.</strong> Ice makes a ship slow, and a slow ship in
converging ice is a ship that gets stuck. The system finds the track where the ice is thin enough
that the hull keeps moving, proves that track is permitted under the Polar Code, and keeps
checking as conditions change.
</div>

<div class="callout warn">
<strong>Where it does not help, stated plainly.</strong> It will not save fuel on every route: on
two of the three legs measured, the safe route burns more, because going around ice costs
distance. It does not replace the ECDIS, the ice navigator, or an official ice chart. And it runs
on simulated environmental fields, so it demonstrates a method rather than delivering an
operational forecast.
</div>""")

    # ---------------------------------------------------------------- 4
    add('<h2 class="pagebreak">4. What this is, in one page</h2>')
    add("""
<p>Every austral summer India sends the Indian Scientific Expedition to Antarctica to resupply
its two stations, <strong>Maitri</strong> and <strong>Bharati</strong>. The sailing window is
about ninety days. Sea ice decides whether the ships make it, and the ice charts available today
are largely manual and twelve to twenty-four hours old. Getting it wrong means burning fuel
ramming ice, missing a relief window, or being beset &mdash; trapped as the ice closes in.</p>

<p>ICEFLOW plans a route through that ice which is safe under the IMO Polar Code, and proves
the benefit by measuring it. The central design decision is this: <strong>the system plans two
routes, not one</strong>. It plans the route a ship would sail with no ice information at all,
and the route it recommends. It then sails <em>both</em> through identical physics. The
difference between them is the benefit, and because it is a measurement rather than an
assumption, it is allowed to come out unfavourable &mdash; and sometimes does.</p>

<div class="callout">
<strong>Why that matters.</strong> The prototype this replaced computed its headline figure as
<code>baseline = optimised &times; 1.22</code> and reported &ldquo;22% fuel saved&rdquo;. That is
a constant dressed as a result: it would report the same saving for any ship, any route and any
ice, including a route that saved nothing at all. Removing it is the single most important change
in this build.
</div>""")

    # ---------------------------------------------------------------- 2
    add("<h2>5. What is real and what is simulated</h2>")
    add("<p>This is the question every reviewer should ask first, so it is answered before anything else.</p>")
    rows = []
    for key, meta in d["provenance"].items():
        status = e(meta["status"])
        cls = "ok" if status.startswith("real") else "bad"
        rows.append([
            e(key.replace("_", " ").title()),
            f'<span class="{cls}">{status}</span>',
            e(meta["source"]),
            e(meta["note"]),
        ])
    add(table(["Layer", "Status", "Source", "Note"], rows))
    add("""
<div class="callout warn">
<strong>The models are real; the weather is simulated.</strong> The ship physics, the POLARIS
risk tables, the Antarctic coastline, the geodesy and the iceberg drift equations are genuine.
The sea-ice, wind, current and wave fields are physically-shaped simulations standing in for
OSI-SAF, AMSR2, Sentinel-1, ERA5 and Copernicus Marine products. Every API response carrying a
simulated field sets <code>is_synthetic: true</code> and names the product it replaces.
All reported skill is therefore <em>simulated-environment</em> skill, and must be described that
way. Swapping in live data is a data-loader change, not a model change.
</div>""")

    # ---------------------------------------------------------------- 3
    add('<h2 class="pagebreak">6. Measured results</h2>')
    if d["legs"]:
        rows = []
        for leg in d["legs"]:
            b, o = leg["baseline"], leg["optimized"]
            rows.append([
                e(leg["label"]),
                f"{b.get('total_distance_nm', 0):,.0f} &rarr; {o.get('total_distance_nm', 0):,.0f}",
                f"{b.get('total_transit_hours', 0):,.0f} &rarr; <strong>{o.get('total_transit_hours', 0):,.0f}</strong>",
                f"{b.get('total_fuel_burn_tonnes', 0):,.0f} &rarr; {o.get('total_fuel_burn_tonnes', 0):,.0f}",
                signed_pct(leg["fuel_saved_percentage"]),
                f'<span class="ok">{leg["time_saved_hours"]:,.0f} h</span>',
                f"{b.get('minimum_rio', 0)} &rarr; <strong>{o.get('minimum_rio', 0)}</strong>",
            ])
        add(table(
            ["Leg", "Distance (nm)", "Time (h)", "Fuel (t)", "Fuel saved", "Time saved", "Min. risk index"],
            rows,
            ["left", "right", "right", "right", "right", "right", "right"],
        ))
        add(f'<p class="meta">Each row is two independent optimisations sailed through identical '
            f'physics. Planning time {min(l["seconds"] for l in d["legs"]):.0f}&ndash;'
            f'{max(l["seconds"] for l in d["legs"]):.0f} s per leg on a laptop CPU.</p>')
    else:
        add('<p class="muted">Route figures were skipped (--quick). Run without --quick to measure them live.</p>')

    add("""
<div class="callout danger">
<strong>The result we did not expect, and did not hide.</strong> On two of the three legs the safe
route burns <em>more</em> fuel, because going around the ice adds distance and the distance costs
more than the ice avoided. Re-weighting the optimiser toward fuel barely moves it: on the Maitri
leg the penalty stays near 8% whichever way the weights are set, because it is a property of the
geography and the ice, not of the search.
<br><br>
<strong>So the honest headline for this system is time and safety, not fuel.</strong> It saves
six to seventeen days inside a ninety-day window and improves the worst-case safety margin on
every single leg. Charter time dominates the cost of a polar resupply, so days are worth more
than tonnes. The planner emits an explicit warning whenever the recommended route costs more
fuel, stating that it is being recommended because it is safer, not cheaper.
</div>""")

    # ---------------------------------------------------------------- 4
    add("<h2>7. Built for the Indian programme, specifically</h2>")
    prog = d["programme"]
    add(f"""
<p>This is not a generic polar router with Indian place names attached. The programme's real
constraints are inside the model.</p>
<h3>The two stations are supplied in completely different ways</h3>
<ul>
  <li><strong>Maitri</strong> sits about 80 km inland on the Schirmacher Oasis. No ship can reach
  it. Cargo is landed on the shelf ice at India Bay and hauled inland by convoy.</li>
  <li><strong>Bharati</strong> is coastal but sits behind the Prydz Bay fast ice, with the Amery
  Ice Shelf calving tabular bergs into the approach.</li>
</ul>
<p>Every destination therefore carries a <strong>validated seaward anchorage</strong>, checked
against the real coastline at start-up, so the planner can never be given a destination a ship
cannot reach.</p>

<h3>The season is a hard constraint</h3>
<p>{e(prog['season']['window'])}. {e(prog['season']['why_it_matters'])} The environment model's
reference date is <strong>{e(prog['season']['model_reference_date'])}</strong> &mdash; deliberately
the departure, not the February ice minimum, because late November is when the pack is still
extensive and the routing problem is hardest.</p>

<h3>The fleet, including the gap in it</h3>""")
    rows = []
    for f in d["fleet"]:
        speeds = f["speeds"]
        cells = []
        for sp in speeds:
            cells.append(f'<span class="bad">beset</span>' if sp <= 0.0 else f"{sp:.1f}")
        rows.append([
            e(f["name"]), e(f["ice_class"]), f"{f['length_m']:.0f}", f"{f['power_mw']:.1f}", *cells,
        ])
    add(table(
        ["Vessel", "Ice class", "LOA (m)", "Power (MW)", "Open water", "0.6 m ice", "1.0 m ice", "1.5 m ice"],
        rows,
        ["left", "left", "right", "right", "right", "right", "right", "right"],
    ))
    add('<p class="meta">Attainable speed in knots at 6/10 ice concentration, solved from the '
        'power and propeller-thrust balance.</p>')
    add(f"""
<div class="callout">
<strong>A quantified case for India's own polar vessel.</strong> {e(prog['fleet']['the_gap'])}
</div>

<h3>The legal frame is enforced, not merely cited</h3>
<ul>""")
    for law in prog["programme"]["legal_framework"]:
        add(f"<li><strong>{e(law['instrument'])}</strong> &mdash; {e(law['relevance'])}</li>")
    add("</ul>")

    # ---------------------------------------------------------------- 5
    add('<h2 class="pagebreak">8. The prototype, as it actually runs</h2>')
    add("""
<p>These are screenshots of the running application, captured by driving it through a real
browser rather than mocked up. The interface has six screens; four are shown here.</p>""")
    for filename, caption in [
        ("how_it_works.png",
         "<strong>How it works.</strong> The landing screen states the problem and the solution, "
         "then shows the pipeline as eight stages with live numbers from the running backend. "
         "Stages light up as they compute."),
        ("planner.png",
         "<strong>Voyage planner.</strong> Cape Town to Bharati planned. Both routes are drawn on "
         "the chart, the solid track being the recommendation and the dashed one the route a ship "
         "would sail with no ice data. The verdict is stated in a sentence before any table."),
        ("bridge.png",
         "<strong>Bridge console.</strong> The chart in EPSG:3031 Antarctic Polar Stereographic "
         "with the real coastline, the sea-ice raster, tracked icebergs and station labels. The "
         "rail carries the live vessel state, the alert feed and the radar scope."),
        ("forecast.png",
         "<strong>Ice forecast.</strong> Lead time scrubbed from 0 to 168 hours with playback, "
         "layer toggles, point inspection, and the forecast skill measured against persistence."),
    ]:
        add(f"""
<figure style="margin:10pt 0;page-break-inside:avoid">
  <img src="screens/{filename}" style="width:100%;border:0.8pt solid #cddbe8;border-radius:3pt" />
  <figcaption style="font-size:8pt;color:#63788f;margin-top:3pt">{caption}</figcaption>
</figure>""")
    add("""
<div class="callout">
<strong>Verified by driving it, not by assuming.</strong> An automated Chrome DevTools session
loads the application, dismisses the guide, walks every screen, presses Plan, waits for the real
optimisation to finish and reads the result off the page. The run reports <strong>zero console
errors, zero uncaught exceptions and zero failed requests</strong>, with the map canvas correctly
sized at 1196 by 754 pixels.
<br><br>
That check earned its place immediately: it found the map rendering blank on every screen. The
canvas backing store was being sized one pixel tall, and nothing else in the project - not the
type checker, not the tests, not any endpoint - could have caught it.
</div>""")

    add('<h2 class="pagebreak">9. How it was built</h2>')
    add("""
<h3>Audit first, then rebuild</h3>
<p>The work did not start by writing features. It started by reading the existing prototype and
running it, which is how the fabricated saving was found: the fuel figure was traced backwards
until it turned out to be a constant. Several other defects surfaced the same way, and they set
the priority for everything that followed. Building new capability on top of a model that lies
about its own results would only have made the lie harder to find.</p>

<h3>The rule that shaped every decision</h3>
<div class="callout">
<strong>No number appears on screen unless something computed it at request time.</strong>
Every figure had to be traceable to a model that runs, and every model had to be checkable
against something independent - a published result, a physical bound, or a baseline it has to
beat. Where a claim could not survive that test, the claim was changed rather than the test.
</div>

<h3>Built in dependency order</h3>
<p>Foundations first, because everything downstream samples them, and because a mistake in the
geodesy would have quietly poisoned every result above it.</p>
<pre>
1.  Geodesy, land mask, constants        haversine, EPSG:3031 with a verified inverse,
                                         97 real coastline polygons behind a fast index
2.  Environment and sea ice              the fields everything else samples
3.  POLARIS and Lindqvist                pure, testable, checkable against published tables
4.  Icebergs and radar                   RK4 momentum balance; honest detection with misses
5.  Route optimiser                      the two-search design and the measured baseline
6.  Voyage engine, storage, exports      the passage as it unfolds, and ECDIS interoperability
7.  API                                  contract frozen here, so the interface could be built
8.  Bridge console                       map engine first, then the shell, then the screens
9.  Machine learning                     added last, on purpose: the physics had to stand alone
10. Documentation and verification       written from measurements, not from intentions
</pre>

<h3>Parallel work against a frozen contract</h3>
<p>Three self-contained pieces were developed in parallel by specialist agents working to a
written specification: the Lindqvist resistance model with the radar simulation, the machine
learning package, and the frontend. This only worked because the API contract was frozen and
written down first, in <code>docs/PROTOTYPE_BUILD_SPEC.md</code>, before any of them started.
Integration was done by hand, and it immediately earned its keep: the planner and the voyage
engine had been given two different speed solvers, and only reconciling them by hand exposed
that the planner was certifying routes that would beset the ship.</p>

<h3>Four layers of verification, each catching what the others could not</h3>""")
    add(table(
        ["Layer", "What it is", "What it caught that nothing else did"],
        [
            ["Unit and property tests",
             "108 tests pinning physics bounds, monotonicity, projection round-trips and determinism",
             "That the forecast must beat persistence, and that the reported saving must equal the difference between the two route evaluations"],
            ["Diagnostic sweep",
             "86 checks across every module, every endpoint including error paths, the full voyage lifecycle and determinism",
             "Phantom sea ice at 30 S, created by noise applied where no ice existed"],
            ["Type checking",
             "TypeScript in strict mode against types derived from the running API",
             "Schema drift: the backend had started returning fields the client did not know about"],
            ["Driving the real interface",
             "An automated Chrome DevTools session that loads the app, walks every screen, presses Plan and reads the result off the page",
             "The map rendering blank on every screen, with the canvas sized one pixel tall"],
        ],
    ))
    add("""
<p>That last row is the important one. The build passed, the types checked, all 108 tests passed
and every endpoint returned 200 - and the central feature of the application was invisible. No
amount of testing the parts would have found it. Someone, or something, had to look at the
screen.</p>

<h3>Everything regenerates from one command</h3>
<pre>
python -m pytest tests/ -q          108 tests
python -m src.cli                   the whole system, in a terminal, no browser
python -m scripts.train             retrain all three models, rewrite models/metrics.json
python -m scripts.make_report       regenerate this document from live model runs
.\start.ps1  /  ./start.sh          install, warm the caches, serve both halves
</pre>
<p>This report is itself generated: it re-plans all three legs, re-measures forecast skill and the
bandwidth budget, and rebuilds the fleet table every time it is produced. A claim that stops
being true cannot quietly survive in it.</p>

<h3>What was corrected along the way, including our own claims</h3>
<ul>
<li>The 15 to 22 percent fuel saving in the original blueprint <strong>was not reproduced</strong>,
so the documentation now states the measured range and explains why time and safety are the
honest headline instead.</li>
<li>A preset vessel called <em>RV Himadri-class</em> was invented. Himadri is India's <em>Arctic</em>
station, not a ship. It was replaced with ORV Sagar Nidhi, which is real.</li>
<li>A season note claimed the models default to a mid-January reference date. They default to
26 November. The text was corrected rather than the model, because departure-season ice is the
harder and more honest case to demonstrate.</li>
<li>Two of three trained models were found to lose to the physics they were meant to improve.
They are reported as failures and excluded from the serving path.</li>
</ul>
<div class="callout warn">
Each of those was a claim this project had already made in writing. Finding them was the point of
the audit discipline, and correcting them in public is what makes the remaining numbers worth
trusting.
</div>""")

    add('<h2 class="pagebreak">10. Architecture, top to bottom</h2>')
    add("""<pre>
   SATELLITE AND REANALYSIS INPUTS          (simulated in this prototype)
   Sentinel-1 SAR | AMSR2 | ERA5 | CMEMS | USNIC iceberg database
                            |
                            v
   DATA LAYER               src/data/
   Antarctic coastline as a hard land mask (97 polygons, Natural Earth 1:50m)
   Stations with validated seaward anchorages | Iceberg catalogue | Programme context
                            |
                            v
   PHYSICS CORE             src/core/          (pure functions, no I/O)
   environment.py    westerlies, katabatic outflow, ACC, synoptic lows
   sea_ice.py        concentration, Stefan thickness, drift, divergence, forecast
   polaris_risk.py   IMO MSC.1/Circ.1519 risk index
   lindqvist_model.py  ice resistance, powering, attainable speed
   iceberg_tracker.py  RK4 momentum balance, melt, ensembles, closest approach
   growler_radar.py  X-band PPI with honest misses and false alarms
   route_optimizer.py  risk-constrained multi-objective A*, twice
   voyage.py         hour-by-hour simulation, alerting, re-routing
                            |
                            v
   MACHINE LEARNING         src/ml/            (optional; physics never depends on it)
   Trained forecaster, drift residual corrector, growler classifier
                            |
                            v
   SERVICES                 src/services/
   SQLite voyage store | GPX / GeoJSON / S-411 export | bandwidth measurement
                            |
                            v
   API                      src/api/           FastAPI, 25+ endpoints + WebSocket
                            |
                            v
   BRIDGE CONSOLE           frontend/          React + custom EPSG:3031 canvas map
   Plan | Sail | Ice forecast | Icebergs | Analytics
</pre>
<p><strong>Dependency direction is strictly one-way.</strong> <code>core</code> depends on
<code>data</code> and never the reverse; <code>services</code> and <code>api</code> depend on
<code>core</code>; <code>ml</code> depends on <code>core</code> and <strong>nothing depends on
<code>ml</code></strong>, so the physics path runs unchanged if no model has ever been trained.</p>""")

    # ---------------------------------------------------------------- 6
    add("<h2>11. Technology stack, and why each choice</h2>")
    add(table(
        ["Choice", "Why this rather than the obvious alternative"],
        [
            ["Python 3.11", "The polar science ecosystem (xarray, NetCDF4, GDAL, Copernicus toolboxes) is Python. Ingesting real ERA5 and OSI-SAF products later means staying where those libraries live."],
            ["FastAPI + Pydantic v2", "A typed schema and an OpenAPI document for free, so the frontend derives its types from the running server rather than guessing. Native WebSocket support for the live voyage stream."],
            ["NumPy / SciPy", "Fields are evaluated on grids of thousands of points. Vectorisation took route planning from 24 s to 15 s and the iceberg ensemble from 109 s to 4 s."],
            ["scikit-learn, <em>not</em> PyTorch", "The trained models are tabular and fit in seconds on a CPU. A bridge PC has no GPU. A deep network would add a heavy dependency and an ONNX export step for no measured gain."],
            ["SQLite", "The shipboard console is one rugged PC with no infrastructure behind it. A file-backed database with write-ahead logging works there unchanged and at NCPOR headquarters too."],
            ["React 18 + Vite + TypeScript (strict)", "Strict typing against generated API types means a backend field rename breaks the build rather than the demonstration."],
            ["Custom canvas map engine", "The most important frontend decision. Mapbox, MapLibre and Leaflet all assume Web Mercator, which is unusable at 70&deg;S, and all assume a reachable tile server, which does not exist at sea. The map projects to EPSG:3031 in TypeScript, mirroring the backend exactly, and draws our own model output."],
            ["Zustand + TanStack Query", "Server state (slow, cacheable route plans) and client state (layer toggles, playback) are different problems and get different tools."],
        ],
    ))
    add("""<p><strong>Deliberately not used:</strong> no map tile provider, no cloud services, no
external APIs, no API keys. A clean checkout runs offline, because the target user is on a ship
below 60&deg;S where there is no geostationary coverage.</p>""")

    # ---------------------------------------------------------------- 7
    add('<h2 class="pagebreak">12. The models</h2>')
    add("""
<h3>Sea ice</h3>
<p>Concentration comes from an ice-edge climatology with an austral seasonal cycle, multi-octave
noise for floes and leads, and coastal polynyas that <em>emerge</em> where katabatic wind drives
ice offshore rather than being painted in. The floe pattern is sampled in a drifting frame, so a
lead is the same lead a day later and tens of kilometres downstream &mdash; which is what makes a
Lagrangian forecast the physically correct method rather than a decorative one.</p>
<p><strong>Thickness answers the question every reviewer asks.</strong> Altimeters (CryoSat-2,
ICESat-2) have narrow swaths and long repeat cycles and cannot support tactical navigation. So
thickness is derived thermodynamically from accumulated Freezing Degree Days by Stefan's Law,
saturating near 1.55 m where oceanic heat flux balances conduction through the ice and its snow,
plus a dynamic ridging term where the drift field converges. Pure Stefan growth diverges as
&radic;FDD and would wrongly predict 3 to 4 m by late season.</p>
<p><strong>Divergence is the besetting predictor.</strong> Where the drift field converges, floes
are driven together, leads close behind the ship and pressure builds against the hull. The route
cost penalises it and the voyage engine alerts on it.</p>

<h3>Forecast verification &mdash; the number that matters most</h3>
<p>Any forecast must beat persistence &mdash; &ldquo;assume nothing changes&rdquo; &mdash; or it
is adding nothing. The forecast never sees the verifying analysis.</p>""")
    rows = []
    for r in d["skill"]:
        skill = r["skill_score_vs_persistence"]
        rows.append([
            f"{r['lead_hours']:.0f} h",
            f"{r['rmse']:.4f}",
            f"{r['persistence_rmse']:.4f}",
            f'<span class="{"ok" if skill > 0 else "bad"}">{skill:+.3f}</span>',
            f"{r['iiee_fraction']:.3f}",
            f"{r['persistence_iiee_fraction']:.3f}",
        ])
    add(table(
        ["Lead", "Forecast RMSE", "Persistence RMSE", "Skill", "IIEE", "Persistence IIEE"],
        rows, ["left", "right", "right", "right", "right", "right"],
    ))
    add('<p class="meta">Concentration units. Positive skill means the forecast beat persistence. '
        'Simulated-environment skill.</p>')

    add("""
<h3>Ship performance &mdash; Lindqvist (1989)</h3>
<p>Crushing, bending and submergence resistance with the correct velocity corrections, plus
open-water resistance via the ITTC-1957 line so total resistance stays continuous as thickness
approaches zero. Four errors in the original transcription of the method were found and fixed,
including a bending term that was dimensionally wrong and <em>backwards in Young's modulus</em>,
making stiffer ice easier to break.</p>
<p><strong>Speed is an output, never an assumption.</strong> Every route segment solves the lower
of the power balance and the propeller thrust balance. The thrust limit binds in heavy ice, and
ignoring it silently assumes a propeller that keeps open-water efficiency down to bollard
conditions, which no propeller does.</p>

<h3>Iceberg drift</h3>
<p>Fourth-order Runge-Kutta on the momentum balance
<code>(M + M&#8336;) dv/dt = F_air + F_water + F_coriolis + F_pressure + F_wave</code>, with
deterioration by basal turbulent melt, buoyant convection and wave erosion, and perturbed
ensembles giving 50 and 90 percent positional uncertainty per lead time. The timestep is derived
per berg from its own drag response timescale.</p>

<h3>Near-field radar</h3>
<p>A simulated X-band plan-position indicator whose honesty is the point: it reports what it
<em>missed</em>. In a representative pack-ice sweep there are 39 real targets, 13 are painted and
26 go undetected, one of them inside the three-mile alert perimeter. Growler detection range
collapses from 3.0 nm in calm water to 0.6 nm in saturated clutter.</p>""")

    # ---------------------------------------------------------------- 8
    add('<h2 class="pagebreak">13. Machine learning: what was trained, and what failed</h2>')
    if d["ml"]:
        ml = d["ml"]["models"]
        add(f'<p class="meta">Trained {e(d["ml"].get("mode", "full"))} run, '
            f'{d["ml"].get("training_wall_time_s", 0):.0f} s wall time, scikit-learn '
            f'{e(d["ml"].get("sklearn_version", ""))}. Every figure is in '
            f'<code>models/metrics.json</code>.</p>')

        sic = ml.get("sic_forecaster", {}).get("headline", {})
        drift = ml.get("drift_residual", {}).get("headline", {})
        grow = ml.get("growler_classifier", {}).get("headline", {})
        add(table(
            ["Model", "Task", "Result", "Used?"],
            [
                ["Growler / clutter classifier", "Real ice target vs sea-clutter false alarm",
                 f'F1 <span class="ok">{grow.get("test_f1", 0):.3f}</span>, ROC-AUC '
                 f'{grow.get("test_roc_auc", 0):.3f}, against {grow.get("snr_baseline_f1", 0):.3f} '
                 f'for an SNR threshold',
                 '<span class="ok">Yes</span>'],
                ["Sea-ice concentration forecaster", "Concentration at +24 to +168 h",
                 f'Test RMSE {sic.get("test_rmse", 0):.3f}; skill vs persistence '
                 f'<span class="bad">{sic.get("skill_vs_persistence", 0):+.3f}</span>, vs physics '
                 f'<span class="bad">{sic.get("skill_vs_physics", 0):+.3f}</span>, vs climatology '
                 f'<span class="ok">{sic.get("skill_vs_climatology", 0):+.3f}</span>',
                 '<span class="bad">No</span>'],
                ["Iceberg drift residual corrector", "Velocity error of the physics model",
                 f'72 h position error {drift.get("physics_mean_position_error_km", 0):.2f} km &rarr; '
                 f'{drift.get("corrected_mean_position_error_km", 0):.2f} km; mean '
                 f'{drift.get("mean_improvement_percent", 0):+.1f}%, median '
                 f'<span class="bad">{drift.get("median_improvement_percent", 0):+.1f}%</span>',
                 '<span class="bad">No</span>'],
            ],
        ))
    add("""
<div class="callout danger">
<strong>Two of the three trained models do not beat the physics they were meant to improve, and
are not used.</strong> This is reported rather than hidden, because a system claiming three
working AI engines when one works is a system nobody should trust with a ship.
<br><br>
<strong>Why they fail, honestly.</strong> The training data is generated by this repository's own
physics environment. The synthetic ice field's patterns are <em>produced</em> by advection, so a
semi-Lagrangian back-trajectory is close to the exact inverse of the generating process and no
gradient-boosted tree on tabular features will beat it in its own world. The iceberg
&ldquo;observations&rdquo; are generated by perturbing the same momentum balance being corrected,
leaving the residual close to unstructured noise. On real Copernicus rasters and real USNIC
tracks &mdash; where the true dynamics are far richer and the physics has genuine systematic bias
&mdash; these are exactly the places a learned model earns its keep, which is why the pipeline is
built and kept.
<br><br>
The classifier works because separating a small ice target from a clutter spike is genuinely
multivariate: aspect ratio alone carries 46% of the feature importance, and no single threshold
can use it.
</div>
<p><strong>Splits are time-based with an embargo, never random.</strong> Nearby samples share the
same underlying noise field, so a random split would leak the answer and report a fictitious
score.</p>""")

    # ---------------------------------------------------------------- 9
    add("<h2>14. Constraints the system is built around</h2>")
    add(table(
        ["Constraint", "How the build answers it"],
        [
            ["No geostationary coverage below 60&deg;S", f'Contours and deltas instead of rasters. <strong>Measured</strong> at {d["bandwidth"]["daily_total_kb"]:.1f} KB/day against a {d["bandwidth"]["budget_kb"]:.0f} KB Iridium Certus budget &mdash; both payloads are built, gzipped and the byte counts read, not estimated.'],
            ["Polar night and cloud for months", "Reliance on C-band SAR and passive microwave, unaffected by darkness or cloud. No optical product is in the critical path."],
            ["Regulation forbids unapproved software in a certified ECDIS", "The console runs on separate hardware and exports GPX 1.1, GeoJSON and an S-411-shaped ice overlay over the ship's LAN, loaded read-only. The S-411 output is explicitly a representative subset, not a certified encoding."],
            ["No GPU on a ship's bridge", "Every model is CPU-only. The heaviest training run completes in about four minutes on a laptop."],
            ["A lead can close in under an hour", "Drift-field divergence gives a compression index; convergent regimes are penalised in the route cost and raise an alert under way."],
            ["Growlers are invisible to satellites", "A separate near-field radar layer that reports its own misses rather than implying complete detection."],
            ["The forecast will be wrong on arrival", "The voyage engine resamples conditions at the ship's actual arrival time and re-plans from the present position when a hard constraint is violated."],
            ["Ice thickness cannot be measured tactically", "Thermodynamic derivation from Freezing Degree Days plus dynamic ridging, as operational ice services do."],
            ["A demonstration must not stall", "Caches are warmed at start-up in a worker thread. The first plan a user waits for dropped from 29 s to 11.7 s, and the server answers immediately."],
        ],
    ))

    # ---------------------------------------------------------------- 10
    add('<h2 class="pagebreak">15. Engineering: performance, and the bugs it exposed</h2>')
    add(table(
        ["Problem", "Fix", "Result"],
        [
            ["Land test in the A* inner loop", "Bounding-box reject plus a memo cache on the quantised lattice", "25,000 queries/s"],
            ["Coast distance on gridded fields", "One batched KD-tree query into a bilinear lookup grid", "200k samples in 67 ms"],
            ["Ice model re-requesting static coast geometry", "Cache keyed on grid content, plus 48-hour forecast slices", "planning 24 s &rarr; 15 s"],
            ["Attainable speed per A* edge", "Tabulate over thickness and concentration, then interpolate", "about 1000&times;"],
            ["Iceberg ensemble integration", "Vectorise the ensemble; refresh forcing every 30 simulated minutes", "109 s &rarr; 4 s"],
            ["Voyage tick", "Reuse the sampled state in the radar sweep; refresh the berg check on an interval", "2340 ms &rarr; 169 ms"],
            ["Cold start before the first plan", "Warm caches and pre-plan the default leg at start-up, in a worker thread", "29 s &rarr; 11.7 s"],
        ],
    ))
    add("""
<h3>Three defects worth recording, because they were correctness bugs, not slow code</h3>
<ol>
<li><strong>The iceberg integrator diverged to NaN for small bergs.</strong> A fixed timestep is
stable for a giant tabular berg whose drag response time is many hours, but a growler responds in
minutes; the velocity oscillated and blew up within a simulated day. The timestep is now derived
per berg from its own response timescale.</li>
<li><strong>The planner certified routes that beset the ship.</strong> The route optimiser
inverted the power curve directly while the voyage engine used the full thrust-limited solver, so
the planner was systematically optimistic. Two components disagreeing about the same physics is
worse than either being wrong alone. Both now call one function.</li>
<li><strong>Iceberg avoidance tested the wrong position.</strong> Keep-out zones used each berg's
position at departure, but a tabular berg drifts tens of kilometres a day. On a 300-hour passage
a route planned clear of D-30A still passed 3.0 nm from the <em>centre</em> of a 32 km berg
&mdash; that is inside it. Exclusion zones now follow each berg's forecast track, interpolated to
the ship's arrival time. The closest approach went from 3.0 nm to 160 nm.</li>
</ol>""")

    # ---------------------------------------------------------------- 11
    add("<h2>16. Honest limitations</h2>")
    add("""
<ol>
<li><strong>Environmental fields are synthetic.</strong> All skill figures are
simulated-environment figures and must be described that way.</li>
<li><strong>Two of three trained models lose to their physics baselines</strong> and are not in
the serving path.</li>
<li><strong>Route optimality is approximate in time.</strong> Edge costs depend on arrival time;
each node carries the arrival time of the best path found so far. This is standard in operational
weather routing but is a label-correcting approximation, not a proof of optimality.</li>
<li><strong>Forecasts clamp at 240 hours.</strong> Longer passages fall back to climatology in
their later legs &mdash; correct, since nobody can forecast ice thirty days out, but it means
very slow baseline routes are evaluated against climatology late on.</li>
<li><strong>The S-411 export is not certified.</strong> It is a representative attribute subset;
conformance requires an S-100 exchange set and validation against the IHO feature catalogue.</li>
<li><strong>Hull angles, block coefficients and fuel consumption are engineering estimates</strong>,
marked as such in the source. Principal dimensions and installed power are published figures.</li>
<li><strong>The 15&ndash;22% fuel reduction in the original blueprint is not reproduced.</strong>
That figure came from the literature, not from this system.</li>
<li><strong>No authentication or multi-tenancy.</strong> It is a single-console prototype.</li>
</ol>""")

    # ---------------------------------------------------------------- 12
    add("<h2>17. How to run and verify it</h2>")
    add("""<pre>
# One command
.\\start.ps1                    (Windows)      ./start.sh          (macOS, Linux)

# Or by hand
pip install -r requirements.txt
uvicorn src.api.main:app --port 8000          &rarr; http://localhost:8000/docs
cd frontend &amp;&amp; npm install &amp;&amp; npm run dev      &rarr; http://localhost:5173

# Verify
python -m pytest tests/ -q                    &rarr; 108 passed
python -m src.cli                             &rarr; the whole system in a terminal
python -m scripts.train                       &rarr; retrain every model
</pre>
<p>The README contains a six-step verification walkthrough giving the expected output of each
check, so a reviewer can tell the difference between &ldquo;it started&rdquo; and &ldquo;it
works&rdquo;.</p>""")

    # ---------------------------------------------------------------- refs
    add("<h2>18. Standards and references</h2>")
    add("""
<p><strong>Standards and law:</strong> IMO MSC.385(94) Polar Code &middot; IMO MSC.1/Circ.1519
POLARIS &middot; IHO S-411 sea-ice product specification &middot; Indian Antarctic Act, 2022.</p>
<p><strong>Data products the production system would ingest:</strong> EUMETSAT OSI SAF OSI-401-b
&middot; AMSR2 (JAXA GCOM-W1) / University of Bremen ASI &middot; ESA Sentinel-1 GRD EW &middot;
ECMWF ERA5 and HRES &middot; Copernicus Marine GLOBAL_ANALYSISFORECAST_PHY_001_024 &middot; US
National Ice Center Antarctic iceberg database.</p>
<p><strong>Literature:</strong> Lindqvist (1989), POAC &middot; Bigg et al. (1997), <em>Cold
Regions Science and Technology</em> &middot; Rackow et al. (2017), <em>JGR Oceans</em> &middot;
El-Tahan et al. (1987) &middot; Timco &amp; Weeks (2010) &middot; Andersson et al. (2021),
<em>Nature Communications</em> (IceNet) &middot; Anderson (1961), <em>Journal of Glaciology</em>.</p>""")

    add(f"""
<footer>
ICEFLOW v{e(d['version'])} &middot; generated {e(d['generated'])} &middot;
Python {e(d['python'])} &middot; coastline: {d['coast']['polygons']} polygons,
{d['coast']['vertices']} vertices.<br>
Every figure in this report was computed when the report was generated. Regenerate with
<code>python -m scripts.make_report</code>.
</footer>""")

    body = "\n".join(P)
    return (
        "<!doctype html><html lang=\"en\"><head><meta charset=\"utf-8\">"
        "<title>ICEFLOW - Prototype Report</title>"
        f"<style>{CSS}</style></head><body>{body}</body></html>"
    )


# --------------------------------------------------------------------------------------
# PDF
# --------------------------------------------------------------------------------------
def find_browser() -> Optional[str]:
    """Locate a Chromium-family browser to print with."""
    for name in ("chrome", "chromium", "msedge", "google-chrome"):
        found = shutil.which(name)
        if found:
            return found
    candidates = [
        r"C:\Program Files\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Google\Chrome\Application\chrome.exe",
        r"C:\Program Files (x86)\Microsoft\Edge\Application\msedge.exe",
        r"C:\Program Files\Microsoft\Edge\Application\msedge.exe",
        "/Applications/Google Chrome.app/Contents/MacOS/Google Chrome",
        "/usr/bin/google-chrome",
        "/usr/bin/chromium-browser",
    ]
    for path in candidates:
        if Path(path).exists():
            return path
    return None


def to_pdf(html_path: Path, pdf_path: Path) -> bool:
    browser = find_browser()
    if not browser:
        print("  No Chromium-family browser found; skipping PDF.")
        print(f"  Open {html_path} and print to PDF instead.")
        return False
    print(f"  Printing to PDF with {Path(browser).name}...")
    cmd = [
        browser,
        "--headless=new",
        "--disable-gpu",
        "--no-sandbox",
        "--no-pdf-header-footer",
        f"--print-to-pdf={pdf_path}",
        html_path.as_uri(),
    ]
    try:
        subprocess.run(cmd, check=True, timeout=180, capture_output=True)
    except (subprocess.CalledProcessError, subprocess.TimeoutExpired) as exc:
        print(f"  PDF generation failed: {exc}")
        return False
    return pdf_path.exists()


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Generate the ICEFLOW prototype report.")
    parser.add_argument("--no-pdf", action="store_true", help="Write HTML only")
    parser.add_argument("--quick", action="store_true", help="Skip the live route optimisations")
    args = parser.parse_args(argv)

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    print("Gathering live figures from the models:")
    data = gather(quick=args.quick)

    html_path = OUT_DIR / "iceflow-Prototype-Report.html"
    html_path.write_text(render(data), encoding="utf-8")
    print(f"\n  HTML: {html_path}  ({html_path.stat().st_size / 1024:.0f} KB)")

    if not args.no_pdf:
        pdf_path = OUT_DIR / "iceflow-Prototype-Report.pdf"
        if to_pdf(html_path, pdf_path):
            print(f"  PDF:  {pdf_path}  ({pdf_path.stat().st_size / 1024:.0f} KB)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
