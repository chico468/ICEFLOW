"""
ICEFLOW command-line console.

Runs a complete expedition simulation in the terminal, with no server and no browser: plan a
passage from Cape Town to an Indian Antarctic station, compare it against the route a ship would
sail without ice information, then sail it hour by hour and watch the alerts come in.

    python -m src.cli                      full demonstration
    python -m src.cli --leg capetown_maitri
    python -m src.cli --quick              skip the voyage simulation
    python -m src.cli --list               show the available legs, vessels and stations

This exists so that a judge with a laptop and no network can see the whole system work.
"""
from __future__ import annotations

import argparse
import sys
import time
from typing import List, Optional

from src.core.constants import (
    DATA_PROVENANCE,
    MGO_PRICE_USD_PER_TONNE,
    PROBLEM_STATEMENT_ID,
    SYSTEM_NAME,
    SYSTEM_VERSION,
    USD_TO_INR,
)
from src.core.iceberg_tracker import closest_approach, predict_iceberg_drift
from src.core.lindqvist_model import VESSEL_PRESETS, attainable_speed, calculate_ice_resistance
from src.core.polaris_risk import (
    IceClass,
    IceRegimeComponent,
    IceType,
    calculate_rio,
    classify_ice_type,
)
from src.core.sea_ice import get_sea_ice_model
from src.core.voyage import create_voyage
from src.data.icebergs import get_iceberg_profiles
from src.data.stations import default_voyage_legs, get_stations, resolve_endpoint

WIDTH = 84


def rule(char: str = "=") -> None:
    print(char * WIDTH)


def header(title: str) -> None:
    print()
    rule()
    print(f"  {title}")
    rule()


def section(number: int, title: str) -> None:
    print()
    print(f"[{number}] {title}")
    print("-" * WIDTH)


def banner() -> None:
    rule()
    print(f"  {SYSTEM_NAME} v{SYSTEM_VERSION}  |  Antarctic Navigation Decision Support")
    print(f"  Smart India Hackathon 2026  |  Problem Statement {PROBLEM_STATEMENT_ID}")
    print("  Ministry of Earth Sciences / National Centre for Polar and Ocean Research")
    rule()
    print("  Physics, POLARIS risk tables and the coastline are real.")
    print("  Atmosphere, ocean and sea-ice fields are simulated stand-ins for ERA5, CMEMS")
    print("  and OSI-SAF products. Every figure below is computed at run time.")
    rule()


def show_catalogue() -> None:
    header("AVAILABLE LEGS, VESSELS AND STATIONS")
    print("\nLegs:")
    for leg in default_voyage_legs():
        print(f"  {leg['id']:22s} {leg['label']}")
    print("\nVessels:")
    for key, vessel in VESSEL_PRESETS.items():
        print(f"  {key:22s} {vessel.display_name:44s} {vessel.ice_class.value:6s} {vessel.installed_power_kw:>7.0f} kW")
    print("\nStations:")
    for station in get_stations():
        flag = "IND" if station["is_indian"] else "   "
        inland = "inland" if station["station_is_inland"] else "coastal"
        print(
            f"  {flag} {station['id']:20s} {station['name']:26s} {inland:8s} "
            f"anchorage ({station['anchorage_lat']:7.2f}, {station['anchorage_lon']:7.2f})"
        )


def demo_polaris() -> None:
    section(1, "IMO POLARIS RISK INDEXING (MSC.1/Circ.1519)")
    regimes = [
        ("PC5 in open water", IceClass.PC5, [(IceType.OPEN_WATER, 10)]),
        ("PC5 in 6/10 medium first-year", IceClass.PC5, [(IceType.MEDIUM_FIRST_YEAR, 6)]),
        ("PC5 in 7/10 thick FY + 3/10 second-year", IceClass.PC5,
         [(IceType.THICK_FIRST_YEAR, 7), (IceType.SECOND_YEAR, 3)]),
        ("PC7 in 10/10 heavy multi-year", IceClass.PC7, [(IceType.HEAVY_MULTI_YEAR, 10)]),
    ]
    print(f"  {'Regime':<44} {'RIO':>5}  {'Status':<26} {'Max kn':>7}")
    for label, ice_class, parts in regimes:
        result = calculate_rio(
            ice_class, [IceRegimeComponent(ice_type=t, concentration_tenths=c) for t, c in parts]
        )
        print(f"  {label:<44} {result.rio:>5}  {result.status:<26} {result.max_recommended_speed_knots:>7.1f}")
    print("\n  RIO >= 0 normal, -10 to 0 restricted, below -10 prohibited.")


def demo_lindqvist() -> None:
    section(2, "LINDQVIST (1989) ICE RESISTANCE AND ATTAINABLE SPEED")
    vessel = VESSEL_PRESETS["vasiliy_golovnin"]
    print(f"  Vessel: {vessel.display_name}, {vessel.length_m:.0f} m LOA, "
          f"{vessel.installed_power_kw:.0f} kW installed\n")
    print(f"  {'Ice':>6} {'Conc':>6} {'V_att':>7} {'R_tot':>9} {'Power':>9} {'Fuel':>10} {'CO2':>10}")
    print(f"  {'(m)':>6} {'':>6} {'(kn)':>7} {'(kN)':>9} {'(kW)':>9} {'(kg/h)':>10} {'(kg/h)':>10}")
    for thickness, conc in [(0.0, 0.0), (0.3, 0.6), (0.6, 0.7), (1.0, 0.6), (1.5, 0.6), (2.0, 0.8)]:
        speed = attainable_speed(vessel, vessel.installed_power_kw, thickness, conc)
        if speed <= 0.0:
            print(f"  {thickness:>6.1f} {conc:>6.1f} {'BESET':>7} {'-':>9} {'-':>9} {'-':>10} {'-':>10}")
            continue
        res = calculate_ice_resistance(vessel, speed, thickness, conc)
        print(
            f"  {thickness:>6.1f} {conc:>6.1f} {speed:>7.2f} {res.total_resistance_kn:>9.1f} "
            f"{res.required_power_kw:>9.0f} {res.fuel_burn_rate_kg_per_hour:>10.0f} "
            f"{res.co2_kg_per_hour:>10.0f}"
        )
    print("\n  Speed is solved from the power and propeller-thrust balance, never assumed.")


def demo_sea_ice() -> None:
    section(3, "SEA-ICE ANALYSIS AND FORECAST SKILL")
    model = get_sea_ice_model()
    print("  Transect along 76 E toward Prydz Bay:\n")
    print(f"  {'Lat':>7} {'Conc':>6} {'Thick':>7} {'Stage':<32} {'Compr':>6} {'Beset':>9}")
    for lat in (-58.0, -61.0, -63.0, -65.0, -67.0, -68.5):
        state = model.state(lat, 76.0)
        print(
            f"  {lat:>7.1f} {state.concentration:>6.2f} {state.thickness_m:>7.2f} "
            f"{state.stage_of_development[:32]:<32} {state.compression_index:>6.2f} {state.besetting_risk:>9}"
        )

    print("\n  Forecast verification against the analysis valid at the same time:\n")
    print(f"  {'Lead':>6} {'RMSE':>8} {'Persist':>8} {'Skill':>8} {'IIEE':>8} {'Persist':>8}")
    for row in model.skill_table([24, 48, 72, 120, 168]):
        print(
            f"  {row['lead_hours']:>5.0f}h {row['rmse']:>8.4f} {row['persistence_rmse']:>8.4f} "
            f"{row['skill_score_vs_persistence']:>+8.3f} {row['iiee_fraction']:>8.3f} "
            f"{row['persistence_iiee_fraction']:>8.3f}"
        )
    print("\n  A positive skill score means the forecast beat persistence, which is the bar")
    print("  any ice forecast has to clear. Measured inside the synthetic environment.")


def demo_icebergs() -> None:
    section(4, "ICEBERG DRIFT (RK4 LAGRANGIAN, PERTURBED ENSEMBLE)")
    bergs = [b for b in get_iceberg_profiles() if b.berg_id in {"D-28", "D-21B"}]
    for berg in bergs:
        forecast = predict_iceberg_drift(berg, forecast_hours=72, time_step_hours=24, ensemble_members=12)
        budget = forecast.force_budget
        print(f"\n  {berg.berg_id} from the {berg.origin}, {berg.length_m / 1000:.0f} km waterline length")
        print(f"    72 h drift {forecast.net_displacement_km:.1f} km at a mean "
              f"{forecast.mean_speed_knots:.2f} kn, mass lost {forecast.mass_lost_percent:.2f}%")
        if budget:
            print(f"    Force budget (MN): air {budget.air_drag_mn:.2f}  water {budget.water_drag_mn:.2f}  "
                  f"Coriolis {budget.coriolis_mn:.2f}  pressure {budget.pressure_gradient_mn:.2f}  "
                  f"wave {budget.wave_radiation_mn:.2f}")
            print(f"    Drag response timescale {budget.response_timescale_hours:.1f} h")
        last = forecast.trajectory[-1]
        print(f"    Position uncertainty at 72 h: {last.uncertainty_radius_50_km:.1f} km (50%), "
              f"{last.uncertainty_radius_90_km:.1f} km (90%)")


def demo_route(leg_id: str, vessel_key: str, run_voyage: bool, voyage_hours: float) -> None:
    leg = next((l for l in default_voyage_legs() if l["id"] == leg_id), None)
    if leg is None:
        print(f"Unknown leg '{leg_id}'. Use --list to see the options.")
        sys.exit(2)

    origin = resolve_endpoint(leg["origin"])
    destination = resolve_endpoint(leg["destination"])
    vessel = VESSEL_PRESETS[vessel_key]

    section(5, f"ROUTE OPTIMISATION: {leg['label'].upper()}")
    print(f"  Vessel {vessel.display_name}, ice class {vessel.ice_class.value}")
    print(f"  From ({origin[0]:.2f}, {origin[1]:.2f}) to ({destination[0]:.2f}, {destination[1]:.2f})")
    print("\n  Planning. Two routes are computed and both are sailed through identical physics,")
    print("  so the saving is a difference between model runs and not a fixed multiplier.")

    started = time.perf_counter()
    engine = create_voyage(
        origin=origin, destination=destination, vessel=vessel,
        origin_name=leg["origin"], destination_name=leg["destination"], vessel_key=vessel_key,
    )
    plan = engine.state.plan_summary
    print(f"  Planned in {time.perf_counter() - started:.1f} s "
          f"({plan.search.nodes_expanded} nodes expanded, {plan.search.search_ms:.0f} ms in A*)\n")

    print(f"  {'Route':<42} {'Dist':>8} {'Time':>8} {'Fuel':>8} {'minRIO':>7} {'Compr':>7}")
    for evaluation in (plan.baseline, plan.optimized):
        print(
            f"  {evaluation.label:<42} {evaluation.total_distance_nm:>7.0f}n "
            f"{evaluation.total_transit_hours:>7.0f}h {evaluation.total_fuel_burn_tonnes:>7.0f}t "
            f"{evaluation.minimum_rio:>7} {evaluation.max_compression_index:>7.2f}"
        )

    fuel_delta = plan.baseline.total_fuel_burn_tonnes - plan.optimized.total_fuel_burn_tonnes
    print()
    print(f"  Fuel saved      {plan.fuel_saved_percentage:>8.2f} %   ({fuel_delta:+.1f} tonnes MGO)")
    print(f"  Time saved      {plan.time_saved_hours:>8.1f} h   ({plan.time_saved_hours / 24.0:+.1f} days)")
    print(f"  CO2 avoided     {plan.co2_saved_tonnes:>8.1f} t")
    print(f"  Extra distance  {plan.distance_delta_nm:>8.1f} nm  (the safe route is usually longer)")
    print(f"  Cost avoided    {plan.cost_saved_inr / 1e5:>8.2f} lakh INR at "
          f"${MGO_PRICE_USD_PER_TONNE:.0f}/t and {USD_TO_INR:.0f} INR/USD")
    if plan.baseline_would_be_prohibited:
        print("\n  NOTE: the ice-blind baseline enters ice where POLARIS prohibits operation.")
    for warning in plan.warnings:
        print(f"  WARNING: {warning}")

    # Iceberg proximity against the planned track.
    route_pts = [(w.latitude, w.longitude, w.cumulative_hours) for w in plan.optimized.waypoints]
    horizon = int(min(240, max(24, plan.optimized.total_transit_hours)))
    threats = []
    for berg in get_iceberg_profiles():
        forecast = predict_iceberg_drift(berg, forecast_hours=horizon, time_step_hours=24)
        threats.append(closest_approach(forecast, route_pts))
    threats.sort(key=lambda a: a.distance_nm)
    print("\n  Tracked iceberg closest approach against this route:")
    for approach in threats[:3]:
        print(f"    {approach.berg_id:8s} {approach.distance_nm:>7.1f} nm at "
              f"+{approach.time_hours:>5.0f} h   {approach.threat_level}")

    if not run_voyage:
        return

    section(6, "VOYAGE SIMULATION")
    print(f"  Sailing {voyage_hours:.0f} simulated hours at 6-hour ticks.\n")
    print(f"  {'Hour':>6} {'Latitude':>9} {'Longitude':>10} {'Spd':>6} {'Conc':>6} {'Thick':>6} "
          f"{'RIO':>5} {'Pwr%':>6} {'Fuel':>8}  Alerts")
    ticks = engine.run(hours=voyage_hours, tick_hours=6.0)
    for tick in ticks[::2]:
        alerts = ",".join(tick.active_alerts) if tick.active_alerts else ""
        print(
            f"  {tick.sim_hours:>6.0f} {tick.latitude:>9.3f} {tick.longitude:>10.3f} "
            f"{tick.speed_knots:>6.1f} {tick.ice_concentration:>6.2f} {tick.ice_thickness_m:>6.2f} "
            f"{tick.rio:>5} {tick.power_utilisation_percent:>6.1f} {tick.fuel_used_tonnes:>8.1f}  {alerts}"
        )

    print("\n  Alert log:")
    if not engine.state.alerts:
        print("    No alerts raised.")
    for alert in engine.state.alerts:
        print(f"    [{alert.severity:<8}] +{alert.sim_hours:>5.0f} h  {alert.code:<22} {alert.message}")

    final = ticks[-1] if ticks else None
    print()
    print(f"  Status {engine.state.status} after {engine.state.sim_hours:.0f} simulated hours")
    print(f"  Distance made good {engine.state.distance_travelled_nm:.0f} nm, "
          f"{final.progress_percent if final else 0:.1f}% of the passage")
    print(f"  Fuel burned {engine.state.total_fuel_tonnes:.1f} t, "
          f"CO2 {engine.state.total_co2_tonnes:.1f} t")


def main(argv: Optional[List[str]] = None) -> int:
    parser = argparse.ArgumentParser(
        prog="polarnav",
        description="ICEFLOW Antarctic navigation decision-support console.",
    )
    parser.add_argument("--leg", default="capetown_bharati", help="Voyage leg id (see --list)")
    parser.add_argument("--vessel", default="vasiliy_golovnin", help="Vessel preset key (see --list)")
    parser.add_argument("--quick", action="store_true", help="Skip the voyage simulation")
    parser.add_argument("--voyage-hours", type=float, default=180.0, help="Simulated hours to sail")
    parser.add_argument("--list", action="store_true", help="List legs, vessels and stations, then exit")
    args = parser.parse_args(argv)

    if args.list:
        show_catalogue()
        return 0

    if args.vessel not in VESSEL_PRESETS:
        print(f"Unknown vessel '{args.vessel}'. Use --list to see the options.")
        return 2

    banner()
    demo_polaris()
    demo_lindqvist()
    demo_sea_ice()
    demo_icebergs()
    demo_route(args.leg, args.vessel, run_voyage=not args.quick, voyage_hours=args.voyage_hours)

    header("PROVENANCE")
    for layer, meta in DATA_PROVENANCE.items():
        print(f"  {layer:<22} {meta['status']:<11} {meta['source']}")
    print()
    print("  Swapping the synthetic layers for live feeds is a data-loader change, not a")
    print("  model change: the same interfaces read Copernicus, NSIDC and ECMWF products.")
    rule()
    print("  Simulation complete. Start the API with:")
    print("      uvicorn src.api.main:app --reload --port 8000")
    print("  and the bridge console with:")
    print("      cd frontend && npm install && npm run dev")
    rule()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
