"""
Voyage simulation engine: the thing that turns a plan into a passage.

A planned route is a static object. What a bridge officer needs is the passage as it unfolds -
the ship at a position, at a time, in the ice that is actually there then, with the alerts that
condition raises. This engine steps a vessel along its plan in simulated time and, at every tick:

  * resamples the ice and weather at the *arrival* time, not the planning time, so a forecast
    that was right at departure can be wrong on arrival and the system notices
  * recomputes POLARIS, the attainable speed and the fuel burn from the conditions found
  * runs an X-band radar sweep for growlers inside the near-field perimeter
  * tests the tracked iceberg catalogue for closest approach against the remaining route
  * raises, sustains and clears alerts
  * triggers a re-plan when a hard constraint is violated, and records the diversion

The tick history is retained, so the interface can scrub back through the passage, and every
number shown is one this engine computed rather than one it was handed.
"""
from __future__ import annotations

import math
import uuid
from datetime import datetime, timedelta, timezone
from typing import Dict, List, Optional, Sequence, Tuple

from pydantic import BaseModel, Field

from src.core.constants import (
    COMPRESSION_BESETTING_THRESHOLD,
    GROWLER_ALERT_RANGE_NM,
    MGO_CO2_FACTOR,
    RIO_PROHIBITED_THRESHOLD,
)
from src.core.environment import EnvironmentModel, get_environment
from src.core.geo import destination_point, haversine_nm, initial_bearing_deg
from src.core.growler_radar import RadarSweep, highest_threat, simulate_sweep
from src.core.lindqvist_model import (
    VesselParameters,
    attainable_speed,
    calculate_ice_resistance,
)
from src.core.polaris_risk import IceClass, IceRegimeComponent, calculate_rio, classify_ice_type
from src.core.route_optimizer import (
    OptimizationSummary,
    PolarRouteOptimizer,
    RouteWeights,
    Waypoint,
)
from src.core.sea_ice import SeaIceModel, get_sea_ice_model

DEFAULT_TICK_HOURS = 1.0
OFF_TRACK_LIMIT_NM = 25.0
HEAVY_WEATHER_WAVE_M = 6.0
HEAVY_WEATHER_WIND_MS = 22.0
# How often the tracked-berg closest-approach check is refreshed, in simulated hours.
ICEBERG_CPA_INTERVAL_HOURS = 24.0


class VoyageAlert(BaseModel):
    """One raised condition. Alerts persist in the log even after the condition clears."""

    alert_id: str
    tick: int
    sim_hours: float
    code: str
    severity: str  # INFO, CAUTION, WARNING, CRITICAL
    message: str
    advisory: str
    latitude: float
    longitude: float
    cleared_at_tick: Optional[int] = None


class VoyageTick(BaseModel):
    """Complete ship and environment state at one simulated hour."""

    tick: int
    sim_hours: float
    timestamp_iso: str

    latitude: float
    longitude: float
    heading_deg: float
    speed_knots: float
    speed_over_ground_knots: float

    distance_travelled_nm: float
    distance_remaining_nm: float
    progress_percent: float
    eta_hours: float

    fuel_used_tonnes: float
    fuel_rate_kg_per_hour: float
    required_power_kw: float
    power_utilisation_percent: float
    co2_tonnes: float

    ice_concentration: float
    ice_thickness_m: float
    ice_type: str
    rio: int
    rio_status: str
    polaris_speed_cap_knots: float
    attainable_speed_knots: float
    compression_index: float
    besetting_risk: str

    wind_speed_ms: float
    wind_dir_from_deg: float
    wave_height_m: float
    air_temp_c: float
    sst_c: float
    visibility_km: float

    radar_contacts: int
    radar_highest_threat: str
    nearest_contact_nm: Optional[float] = None
    sea_clutter_level: float = 0.0

    active_alerts: List[str] = Field(default_factory=list)
    is_beset: bool = False


class VoyageState(BaseModel):
    """Everything the interface needs to render a voyage."""

    voyage_id: str
    status: str  # PLANNED, UNDER_WAY, ARRIVED, BESET, ABORTED
    created_iso: str
    departure_iso: str

    vessel_name: str
    vessel_key: str
    ice_class: str
    origin: Tuple[float, float]
    destination: Tuple[float, float]
    origin_name: str = ""
    destination_name: str = ""

    planned_route: List[Waypoint] = Field(default_factory=list)
    baseline_route: List[Waypoint] = Field(default_factory=list)
    travelled_track: List[Tuple[float, float]] = Field(default_factory=list)

    ticks: List[VoyageTick] = Field(default_factory=list)
    alerts: List[VoyageAlert] = Field(default_factory=list)

    current_tick: int = 0
    sim_hours: float = 0.0
    total_fuel_tonnes: float = 0.0
    total_co2_tonnes: float = 0.0
    distance_travelled_nm: float = 0.0
    reroute_count: int = 0

    plan_summary: Optional[OptimizationSummary] = None
    is_synthetic_environment: bool = True


class VoyageEngine:
    """Steps one voyage forward in simulated time."""

    def __init__(
        self,
        vessel: VesselParameters,
        ice_class: IceClass,
        plan: OptimizationSummary,
        origin_name: str = "",
        destination_name: str = "",
        vessel_key: str = "",
        departure: Optional[datetime] = None,
        weights: Optional[RouteWeights] = None,
        sea_ice: Optional[SeaIceModel] = None,
        environment: Optional[EnvironmentModel] = None,
        avoid_icebergs: bool = True,
    ) -> None:
        self.vessel = vessel
        self.ice_class = ice_class
        self.weights = weights or RouteWeights()
        self.sea_ice = sea_ice or get_sea_ice_model()
        self.env = environment or get_environment()
        self.avoid_icebergs = avoid_icebergs

        departure = departure or datetime.now(timezone.utc)
        route = plan.optimized.waypoints if plan.optimized else plan.waypoints

        self.state = VoyageState(
            voyage_id=uuid.uuid4().hex[:12],
            status="PLANNED",
            created_iso=datetime.now(timezone.utc).isoformat(timespec="seconds"),
            departure_iso=departure.isoformat(timespec="seconds"),
            vessel_name=vessel.name,
            vessel_key=vessel_key,
            ice_class=ice_class.value,
            origin=plan.origin,
            destination=plan.destination,
            origin_name=origin_name,
            destination_name=destination_name,
            planned_route=list(route),
            baseline_route=list(plan.baseline.waypoints) if plan.baseline else [],
            travelled_track=[(plan.origin[0], plan.origin[1])],
            plan_summary=plan,
        )

        self._departure = departure
        self._leg_index = 0  # index of the route waypoint we are steering toward
        self._position = (plan.origin[0], plan.origin[1])
        self._alert_seq = 0
        self._open_alerts: Dict[str, VoyageAlert] = {}
        self._last_cpa_check = -1e9
        self._cpa_checked_once = False

    # ------------------------------------------------------------------ alerts
    def _raise(self, code: str, severity: str, message: str, advisory: str) -> VoyageAlert:
        existing = self._open_alerts.get(code)
        if existing is not None:
            return existing
        self._alert_seq += 1
        alert = VoyageAlert(
            alert_id=f"{self.state.voyage_id}-{self._alert_seq:04d}",
            tick=self.state.current_tick,
            sim_hours=self.state.sim_hours,
            code=code,
            severity=severity,
            message=message,
            advisory=advisory,
            latitude=round(self._position[0], 4),
            longitude=round(self._position[1], 4),
        )
        self._open_alerts[code] = alert
        self.state.alerts.append(alert)
        return alert

    def _clear(self, code: str) -> None:
        alert = self._open_alerts.pop(code, None)
        if alert is not None:
            alert.cleared_at_tick = self.state.current_tick

    # -------------------------------------------------------------- geometry
    def _remaining_route(self) -> List[Tuple[float, float]]:
        pts = [(w.latitude, w.longitude) for w in self.state.planned_route[self._leg_index:]]
        return pts or [self.state.destination]

    def _distance_remaining(self) -> float:
        pts = [self._position] + self._remaining_route()
        return sum(haversine_nm(pts[i][0], pts[i][1], pts[i + 1][0], pts[i + 1][1]) for i in range(len(pts) - 1))

    def _advance_along_route(self, distance_nm: float) -> Tuple[float, float, float]:
        """
        Move the ship `distance_nm` along the planned track.

        Returns the new position and the heading actually steered. Waypoints are consumed as they
        are passed, so a slow tick in heavy ice does not skip a leg.
        """
        lat, lon = self._position
        heading = 0.0
        remaining = distance_nm

        while remaining > 1e-6:
            targets = self.state.planned_route[self._leg_index:]
            if not targets:
                target = self.state.destination
            else:
                target = (targets[0].latitude, targets[0].longitude)

            leg_nm = haversine_nm(lat, lon, target[0], target[1])
            heading = initial_bearing_deg(lat, lon, target[0], target[1]) if leg_nm > 1e-6 else heading

            if leg_nm <= remaining:
                lat, lon = target
                remaining -= leg_nm
                if self._leg_index < len(self.state.planned_route):
                    self._leg_index += 1
                else:
                    break
                if self._leg_index >= len(self.state.planned_route):
                    break
            else:
                lat, lon = destination_point(lat, lon, heading, remaining)
                remaining = 0.0

        return lat, lon, heading

    # ------------------------------------------------------------------ tick
    def step(self, hours: float = DEFAULT_TICK_HOURS, run_radar: bool = True) -> VoyageTick:
        """Advance the voyage by `hours` of simulated time and return the resulting state."""
        if self.state.status in {"ARRIVED", "ABORTED"}:
            return self.state.ticks[-1]

        self.state.status = "UNDER_WAY"
        self.state.current_tick += 1
        t_now = self.state.sim_hours

        lat, lon = self._position

        # Conditions where the ship is, at the time it is there.
        ice = self.sea_ice.state(lat, lon, t_hours=0.0, lead_hours=t_now)
        env = self.env.sample(lat, lon, t_now, ice_concentration=ice.concentration)

        polaris = calculate_rio(
            self.ice_class,
            [IceRegimeComponent(ice_type=ice.ice_type, concentration_tenths=ice.concentration_tenths)],
        )
        attainable = attainable_speed(
            self.vessel, self.vessel.installed_power_kw, ice.thickness_m, ice.concentration
        )
        speed = min(polaris.max_recommended_speed_knots, attainable)
        is_beset = speed < 0.5

        resistance = calculate_ice_resistance(
            self.vessel, max(speed, 0.5), ice.thickness_m, ice.concentration
        )
        # A beset ship is at full power and going nowhere. Reporting the power needed to make
        # half a knot would show the plant almost idle at the exact moment it is maxed out.
        reported_power_kw = self.vessel.installed_power_kw if is_beset else resistance.required_power_kw

        # Move.
        step_nm = max(0.0, speed) * hours
        new_lat, new_lon, heading = self._advance_along_route(step_nm)
        self._position = (new_lat, new_lon)
        self.state.travelled_track.append((round(new_lat, 4), round(new_lon, 4)))

        fuel_this_tick = resistance.fuel_burn_rate_kg_per_hour * hours / 1000.0
        if is_beset:
            # A beset ship is not making way, but it is still burning fuel holding station and
            # working the ice. Reporting zero would understate the cost of a besetting.
            fuel_this_tick = resistance.fuel_burn_rate_kg_per_hour * hours * 0.35 / 1000.0

        self.state.sim_hours = round(t_now + hours, 3)
        self.state.distance_travelled_nm = round(self.state.distance_travelled_nm + step_nm, 2)
        self.state.total_fuel_tonnes = round(self.state.total_fuel_tonnes + fuel_this_tick, 3)
        self.state.total_co2_tonnes = round(self.state.total_fuel_tonnes * MGO_CO2_FACTOR, 3)

        # Radar sweep for near-field ice.
        sweep: Optional[RadarSweep] = None
        if run_radar:
            sweep = simulate_sweep(
                new_lat, new_lon, heading, max(speed, 0.0), self.state.sim_hours,
                sea_ice_model=self.sea_ice, environment=self.env,
                ice_state=ice, env_sample=env,
            )

        remaining_nm = self._distance_remaining()
        planned_total = self.state.plan_summary.total_distance_nm if self.state.plan_summary else 1.0
        progress = 100.0 * (1.0 - remaining_nm / max(planned_total, 1e-6))

        self._evaluate_alerts(polaris, ice, env, sweep, speed, is_beset, remaining_nm)

        eta = remaining_nm / max(speed, 0.5)
        tick = VoyageTick(
            tick=self.state.current_tick,
            sim_hours=self.state.sim_hours,
            timestamp_iso=(self._departure + timedelta(hours=self.state.sim_hours)).isoformat(timespec="seconds"),
            latitude=round(new_lat, 5),
            longitude=round(new_lon, 5),
            heading_deg=round(heading, 1),
            speed_knots=round(speed, 2),
            speed_over_ground_knots=round(step_nm / max(hours, 1e-6), 2),
            distance_travelled_nm=self.state.distance_travelled_nm,
            distance_remaining_nm=round(remaining_nm, 1),
            progress_percent=round(max(0.0, min(100.0, progress)), 2),
            eta_hours=round(eta, 1),
            fuel_used_tonnes=self.state.total_fuel_tonnes,
            fuel_rate_kg_per_hour=round(resistance.fuel_burn_rate_kg_per_hour, 1),
            required_power_kw=round(reported_power_kw, 1),
            power_utilisation_percent=round(
                100.0 * min(1.0, reported_power_kw / max(self.vessel.installed_power_kw, 1.0)), 1
            ),
            co2_tonnes=self.state.total_co2_tonnes,
            ice_concentration=ice.concentration,
            ice_thickness_m=ice.thickness_m,
            ice_type=ice.ice_type.value,
            rio=polaris.rio,
            rio_status=polaris.status,
            polaris_speed_cap_knots=polaris.max_recommended_speed_knots,
            attainable_speed_knots=round(attainable, 2),
            compression_index=ice.compression_index,
            besetting_risk=ice.besetting_risk,
            wind_speed_ms=env.wind_speed_ms,
            wind_dir_from_deg=env.wind_dir_from_deg,
            wave_height_m=env.sig_wave_height_m,
            air_temp_c=env.t2m_c,
            sst_c=env.sst_c,
            visibility_km=env.visibility_km,
            radar_contacts=len(sweep.contacts) if sweep else 0,
            radar_highest_threat=(_worst.threat_level if (_worst := highest_threat(sweep) if sweep else None) else "NONE"),
            nearest_contact_nm=(
                round(min(c.range_nm for c in sweep.contacts), 2) if sweep and sweep.contacts else None
            ),
            sea_clutter_level=round(sweep.sea_clutter_level, 3) if sweep else 0.0,
            active_alerts=sorted(self._open_alerts.keys()),
            is_beset=is_beset,
        )
        self.state.ticks.append(tick)

        if is_beset:
            self.state.status = "BESET"
        if remaining_nm <= 5.0:
            self.state.status = "ARRIVED"

        return tick

    def run(self, hours: float, tick_hours: float = DEFAULT_TICK_HOURS) -> List[VoyageTick]:
        """Advance several ticks, stopping early on arrival."""
        produced: List[VoyageTick] = []
        steps = max(1, int(round(hours / tick_hours)))
        for _ in range(steps):
            if self.state.status in {"ARRIVED", "ABORTED"}:
                break
            produced.append(self.step(tick_hours))
        return produced

    # ---------------------------------------------------------------- alerts
    def _evaluate_alerts(
        self,
        polaris,
        ice,
        env,
        sweep: Optional[RadarSweep],
        speed: float,
        is_beset: bool,
        remaining_nm: float,
    ) -> None:
        if polaris.rio < RIO_PROHIBITED_THRESHOLD:
            self._raise(
                "RIO_PROHIBITED", "CRITICAL",
                f"POLARIS prohibits operation here: RIO {polaris.rio}.",
                "Stop, back out along the track already sailed, and re-plan. Request icebreaker escort.",
            )
        elif polaris.rio < 0:
            self._clear("RIO_PROHIBITED")
            self._raise(
                "RIO_RESTRICTED", "WARNING",
                f"Elevated operational risk: RIO {polaris.rio}.",
                polaris.advisory_notes,
            )
        else:
            self._clear("RIO_PROHIBITED")
            self._clear("RIO_RESTRICTED")

        if ice.compression_index >= COMPRESSION_BESETTING_THRESHOLD and ice.concentration >= 0.7:
            self._raise(
                "COMPRESSION_BESETTING", "WARNING",
                f"Convergent ice regime: compression index {ice.compression_index:.2f} at "
                f"{ice.concentration_tenths}/10 concentration.",
                "Leads are closing. Work toward divergent ice or a shear zone; do not enter a closing lead.",
            )
        else:
            self._clear("COMPRESSION_BESETTING")

        if is_beset:
            self._raise(
                "BESET", "CRITICAL",
                "Vessel cannot make way: available power is below the ice resistance.",
                "Besetting in progress. Attempt to back and ram along the existing channel, and report position.",
            )
        else:
            self._clear("BESET")

        if env.sig_wave_height_m >= HEAVY_WEATHER_WAVE_M or env.wind_speed_ms >= HEAVY_WEATHER_WIND_MS:
            self._raise(
                "HEAVY_WEATHER", "CAUTION",
                f"Heavy weather: {env.wind_speed_ms:.0f} m/s wind, {env.sig_wave_height_m:.1f} m significant wave.",
                "Secure for heavy weather, reduce to a comfortable speed and review the deck cargo lashings.",
            )
        else:
            self._clear("HEAVY_WEATHER")

        if env.visibility_km < 1.0:
            self._raise(
                "LOW_VISIBILITY", "CAUTION",
                f"Visibility down to {env.visibility_km:.1f} km in blowing snow.",
                "Post an extra lookout, reduce speed and rely on radar for near-field ice.",
            )
        else:
            self._clear("LOW_VISIBILITY")

        if sweep and sweep.contacts:
            close = [c for c in sweep.contacts if c.range_nm <= GROWLER_ALERT_RANGE_NM]
            critical = [c for c in sweep.contacts if c.threat_level in {"HIGH", "CRITICAL"}]
            worst = highest_threat(sweep)
            if critical and worst is not None:
                self._raise(
                    "GROWLER_CONTACT", "WARNING" if worst.threat_level == "HIGH" else "CRITICAL",
                    f"{worst.size_class.replace('_', ' ')} bearing {worst.bearing_deg:.0f} at "
                    f"{worst.range_nm:.1f} nm, CPA {worst.cpa_nm:.1f} nm in {worst.tcpa_minutes:.0f} min.",
                    "Alter course to open the CPA. Small ice is poorly detected in clutter, so treat the "
                    "contact count as a lower bound.",
                )
            elif not close:
                self._clear("GROWLER_CONTACT")
        else:
            self._clear("GROWLER_CONTACT")

        # Iceberg closest approach against the remaining route.
        #
        # This integrates a drift forecast per berg, which is by far the most expensive check in
        # the loop. Tabular bergs move a few kilometres a day, so re-running it every tick buys
        # nothing; it is refreshed on a fixed simulated-time interval and the verdict held between
        # refreshes.
        if self.state.sim_hours - self._last_cpa_check < ICEBERG_CPA_INTERVAL_HOURS and self._cpa_checked_once:
            return
        self._last_cpa_check = self.state.sim_hours
        self._cpa_checked_once = True
        try:
            from src.core.iceberg_tracker import closest_approach, predict_iceberg_drift
            from src.data.icebergs import bergs_near

            near = bergs_near(self._position[0], self._position[1], radius_nm=250.0)
            route_pts: List[Tuple[float, float, float]] = []
            cum = 0.0
            prev = self._position
            for pt in self._remaining_route()[:25]:
                cum += haversine_nm(prev[0], prev[1], pt[0], pt[1]) / max(speed, 1.0)
                route_pts.append((pt[0], pt[1], cum))
                prev = pt

            worst_cpa = None
            for berg in near[:3]:
                fc = predict_iceberg_drift(
                    berg, forecast_hours=72, time_step_hours=12,
                    t0_hours=self.state.sim_hours, environment=self.env,
                )
                cpa = closest_approach(fc, route_pts)
                if cpa.threat_level in {"HIGH", "CRITICAL"} and (
                    worst_cpa is None or cpa.distance_nm < worst_cpa.distance_nm
                ):
                    worst_cpa = cpa
            if worst_cpa is not None:
                self._raise(
                    "ICEBERG_CPA", "WARNING",
                    f"Tracked berg {worst_cpa.berg_id} closes to {worst_cpa.distance_nm:.1f} nm "
                    f"at +{worst_cpa.time_hours:.0f} h.",
                    worst_cpa.advisory,
                )
            else:
                self._clear("ICEBERG_CPA")
        except Exception:  # pragma: no cover - the catalogue is an optional layer
            pass

    # --------------------------------------------------------------- reroute
    def reroute(self) -> OptimizationSummary:
        """
        Re-plan from the present position.

        Called when the ship meets conditions the original plan did not anticipate. The new plan
        replaces the remaining route; the track already sailed is left untouched, so the diversion
        is visible on the chart rather than silently rewritten.
        """
        optimizer = PolarRouteOptimizer(
            vessel=self.vessel,
            ice_class=self.ice_class,
            weights=self.weights,
            installed_power_kw=self.vessel.installed_power_kw,
            sea_ice=self.sea_ice,
            environment=self.env,
        )
        plan = optimizer.optimize_route(
            self._position[0], self._position[1],
            self.state.destination[0], self.state.destination[1],
            departure_time_hours=self.state.sim_hours,
            avoid_icebergs=self.avoid_icebergs,
        )
        route = plan.optimized.waypoints if plan.optimized else plan.waypoints
        self.state.planned_route = list(route)
        self._leg_index = 0
        self.state.reroute_count += 1
        self._raise(
            "REROUTED", "INFO",
            f"Route re-planned from the present position at +{self.state.sim_hours:.0f} h.",
            f"New track: {plan.total_distance_nm:.0f} nm, {plan.total_transit_hours:.0f} h, "
            f"minimum RIO {plan.minimum_rio}.",
        )
        self._clear("REROUTED")
        return plan


def create_voyage(
    origin: Tuple[float, float],
    destination: Tuple[float, float],
    vessel: VesselParameters,
    ice_class: Optional[IceClass] = None,
    weights: Optional[RouteWeights] = None,
    origin_name: str = "",
    destination_name: str = "",
    vessel_key: str = "",
    departure: Optional[datetime] = None,
    avoid_icebergs: bool = True,
    grid_resolution_deg: float = 0.5,
) -> VoyageEngine:
    """Plan a passage and hand back an engine ready to sail it."""
    resolved_class = ice_class or vessel.ice_class
    optimizer = PolarRouteOptimizer(
        vessel=vessel,
        ice_class=resolved_class,
        weights=weights,
        installed_power_kw=vessel.installed_power_kw,
    )
    plan = optimizer.optimize_route(
        origin[0], origin[1], destination[0], destination[1],
        grid_resolution_deg=grid_resolution_deg,
        avoid_icebergs=avoid_icebergs,
    )
    return VoyageEngine(
        vessel=vessel,
        ice_class=resolved_class,
        plan=plan,
        origin_name=origin_name,
        destination_name=destination_name,
        vessel_key=vessel_key,
        departure=departure,
        weights=weights,
        avoid_icebergs=avoid_icebergs,
    )
