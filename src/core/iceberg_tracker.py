"""
Physics-informed Lagrangian iceberg drift and deterioration.

The v0.1 module in this repository applied a single constant velocity for the whole forecast:
it added 2 percent of the wind to 90 percent of the current and extrapolated in a straight line.
That is a kinematic rule of thumb, not a momentum balance, and it cannot represent inertia, the
Coriolis turning that dominates large tabular bergs, or the way a berg lags a changing wind.

This module solves the actual equation of motion,

    (M + M_a) dv/dt = F_air + F_water + F_coriolis + F_pressure + F_wave

by fourth-order Runge-Kutta on an adaptive internal step, sampling time-varying forcing along
the track. Sub-stepping is not optional here: a berg's drag response timescale runs from many
hours for a giant tabular berg down to minutes for a growler, and integrating a small berg at a
large step diverges to NaN within a day. The step is therefore derived per berg from its own
response timescale.

Also modelled:

  deterioration   basal turbulent melt, buoyant convection and wave erosion shrink the berg,
                  and a berg that drops below the size thresholds is reclassified bergy bit
                  and then growler - which is when it becomes most dangerous, because it stops
                  being visible to satellites while still being able to hole a hull
  ensembles       perturbed drag coefficients and forcing give a spread of tracks, from which
                  50 and 90 percent positional uncertainty radii are derived per lead time
  CPA            closest point of approach against a planned route, driving collision warnings

References: Bigg et al. (1997), Rackow et al. (2017) for the momentum balance and drag
coefficients; El-Tahan et al. (1987) and Weeks & Campbell (1973) for the deterioration terms.
"""
from __future__ import annotations

import math
from typing import Dict, List, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from src.core.constants import (
    ENSEMBLE_SEED,
    GRAVITY,
    ICEBERG_ADDED_MASS_COEFF,
    ICEBERG_AIR_DRAG_COEFF,
    ICEBERG_WATER_DRAG_COEFF,
    KM_PER_NM,
    MELT_BUOYANT_CONVECTION_COEFF,
    RHO_AIR,
    RHO_GLACIAL_ICE,
    RHO_SEAWATER,
    SIZE_CLASS_THRESHOLDS_M,
)
from src.core.environment import EnvironmentModel, get_environment
from src.core.geo import coriolis_parameter, haversine_km, haversine_nm, meters_to_degrees

# A giant tabular berg has a drag response timescale of many hours, so a half-hour step is
# comfortably stable. A growler responds in minutes, and integrating it at the same step blows
# up: the velocity oscillates, diverges and goes to NaN within a day. The timestep is therefore
# derived from each berg's own response timescale, bounded by these limits.
MAX_INTERNAL_TIMESTEP_S = 1800.0
MIN_INTERNAL_TIMESTEP_S = 60.0
TIMESTEP_SAFETY_DIVISOR = 5.0
MAX_PHYSICAL_DRIFT_MS = 3.0  # a drifting berg faster than this is a numerical failure, not physics
# How often the atmosphere and ocean are re-sampled along the track, in simulated seconds.
FORCING_REFRESH_S = 1800.0


class IcebergProfile(BaseModel):
    """Geometry and identity of a tracked iceberg."""

    berg_id: str
    latitude: float
    longitude: float
    length_m: float = Field(default=800.0, description="Waterline length in metres")
    width_m: float = Field(default=400.0, description="Waterline width in metres")
    sail_height_m: float = Field(default=35.0, description="Freeboard above the waterline in metres")
    keel_depth_m: float = Field(default=180.0, description="Submerged draft in metres")
    mass_metric_tonnes: float = Field(default=5.0e7, description="Estimated mass in tonnes")
    origin: str = Field(default="", description="Calving source, where known")

    def size_class(self) -> str:
        length = self.length_m
        for name, bound in SIZE_CLASS_THRESHOLDS_M.items():
            if length < bound:
                return name
        return "giant"

    def consistent_mass_kg(self) -> float:
        """
        Mass implied by the geometry, used when the reported tonnage is missing or stale.

        Total draft is keel depth, so the submerged volume is length x width x keel depth, and
        the sail adds the freeboard slab on top.
        """
        volume = self.length_m * self.width_m * (self.keel_depth_m + self.sail_height_m)
        return volume * RHO_GLACIAL_ICE


class TrajectoryPoint(BaseModel):
    """One output step of a drift forecast."""

    hour: int
    latitude: float
    longitude: float
    speed_knots: float
    heading_deg: float
    distance_from_origin_km: float
    # Added in v1.0
    u_ms: float = 0.0
    v_ms: float = 0.0
    length_m: float = 0.0
    mass_metric_tonnes: float = 0.0
    size_class: str = ""
    uncertainty_radius_50_km: float = 0.0
    uncertainty_radius_90_km: float = 0.0


class ForceBudget(BaseModel):
    """
    Force magnitudes in meganewtons, so the physics can be inspected rather than trusted.

    Sampled a quarter of the way through the forecast rather than at t = 0, because the berg is
    initialised moving with the current and the water drag is identically zero there.
    """

    air_drag_mn: float
    water_drag_mn: float
    coriolis_mn: float
    pressure_gradient_mn: float
    wave_radiation_mn: float
    response_timescale_hours: float


class IcebergForecastResult(BaseModel):
    berg_id: str
    forecast_horizon_hours: int
    trajectory: List[TrajectoryPoint]
    net_displacement_km: float
    # Added in v1.0
    mean_speed_knots: float = 0.0
    initial_size_class: str = ""
    final_size_class: str = ""
    mass_lost_percent: float = 0.0
    final_length_m: float = 0.0
    ensemble_members: int = 1
    force_budget: Optional[ForceBudget] = None
    integration_scheme: str = "RK4, adaptive internal step from the berg drag response timescale"
    is_synthetic: bool = True
    source: str = "USNIC-seeded position; drift computed from synthetic ERA5/CMEMS-equivalent forcing"


class ClosestApproach(BaseModel):
    """Result of testing a berg track against a planned route."""

    berg_id: str
    distance_nm: float
    time_hours: float
    waypoint_index: int
    berg_position: Tuple[float, float]
    route_position: Tuple[float, float]
    threat_level: str
    advisory: str


# --------------------------------------------------------------------------------------
# Forcing
#
# Every forcing function takes arrays of positions and returns arrays, because the ensemble is
# integrated as a single vectorised state. Running eight members one at a time, sampling the
# environment at every Runge-Kutta stage, took nearly two minutes for a 72-hour forecast; the
# vectorised form does the same work in about a second, which is what an interactive console
# needs.
# --------------------------------------------------------------------------------------
def _uniform_forcing(
    wind_speed_ms: float,
    wind_direction_from_deg: float,
    current_speed_ms: float,
    current_direction_to_deg: float,
    n: int,
) -> Dict[str, np.ndarray]:
    """Constant forcing, matching the v0.1 call signature."""
    wind_to = math.radians((wind_direction_from_deg + 180.0) % 360.0)
    cur_to = math.radians(current_direction_to_deg)
    ones = np.ones(n, dtype=np.float64)
    return {
        "ua": ones * wind_speed_ms * math.sin(wind_to),
        "va": ones * wind_speed_ms * math.cos(wind_to),
        "uo": ones * current_speed_ms * math.sin(cur_to),
        "vo": ones * current_speed_ms * math.cos(cur_to),
        "hs": ones * min(13.0, 0.0246 * wind_speed_ms ** 2),
        "sst": ones * 0.5,
    }


def _field_forcing(env: EnvironmentModel, lat: np.ndarray, lon: np.ndarray, t_hours: float) -> Dict[str, np.ndarray]:
    """Forcing sampled from the environment fields at these positions and this time."""
    ua, va, _ = env.wind_uv(lat, lon, t_hours)
    uo, vo = env.current_uv(lat, lon, t_hours)
    scal = env.scalars(lat, lon, t_hours, np.hypot(ua, va), 0.0)
    return {"ua": ua, "va": va, "uo": uo, "vo": vo, "hs": scal["sig_wave_height_m"], "sst": scal["sst_c"]}


# --------------------------------------------------------------------------------------
# Momentum balance
# --------------------------------------------------------------------------------------
def _acceleration(
    u: np.ndarray,
    v: np.ndarray,
    lat: np.ndarray,
    forcing: Dict[str, np.ndarray],
    mass_kg: np.ndarray,
    sail_area_m2: np.ndarray,
    keel_area_m2: np.ndarray,
    length_m: np.ndarray,
    c_air: np.ndarray,
    c_water: np.ndarray,
) -> Tuple[np.ndarray, np.ndarray, Dict[str, float]]:
    """Sum the forces and divide by the virtual mass. Returns (du/dt, dv/dt, diagnostics)."""
    m_virtual = mass_kg * (1.0 + ICEBERG_ADDED_MASS_COEFF)
    f = 2.0 * 7.2921159e-5 * np.sin(np.radians(lat))

    # Air drag on the sail.
    dua, dva = forcing["ua"] - u, forcing["va"] - v
    spd_a = np.hypot(dua, dva)
    fa_x = 0.5 * RHO_AIR * c_air * sail_area_m2 * spd_a * dua
    fa_y = 0.5 * RHO_AIR * c_air * sail_area_m2 * spd_a * dva

    # Water drag on the keel. This is the dominant term for a tabular berg.
    duo, dvo = forcing["uo"] - u, forcing["vo"] - v
    spd_w = np.hypot(duo, dvo)
    fw_x = 0.5 * RHO_SEAWATER * c_water * keel_area_m2 * spd_w * duo
    fw_y = 0.5 * RHO_SEAWATER * c_water * keel_area_m2 * spd_w * dvo

    # Coriolis on the berg.
    fc_x = m_virtual * f * v
    fc_y = -m_virtual * f * u

    # Sea-surface slope. Written so that a berg moving exactly with the geostrophic current
    # feels no net rotational force, which is the physically correct equilibrium.
    fp_x = -m_virtual * f * forcing["vo"]
    fp_y = m_virtual * f * forcing["uo"]

    # Wave radiation stress, directed along wave propagation, taken as the wind direction.
    amplitude = forcing["hs"] / 2.0
    fr_mag = 0.5 * RHO_SEAWATER * GRAVITY * amplitude ** 2 * length_m
    wind_spd = np.hypot(forcing["ua"], forcing["va"]) + 1e-9
    fr_x = fr_mag * forcing["ua"] / wind_spd
    fr_y = fr_mag * forcing["va"] / wind_spd

    ax = (fa_x + fw_x + fc_x + fp_x + fr_x) / m_virtual
    ay = (fa_y + fw_y + fc_y + fp_y + fr_y) / m_virtual

    diag = {
        "air": float(np.mean(np.hypot(fa_x, fa_y))),
        "water": float(np.mean(np.hypot(fw_x, fw_y))),
        "coriolis": float(np.mean(np.hypot(fc_x, fc_y))),
        "pressure": float(np.mean(np.hypot(fp_x, fp_y))),
        "wave": float(np.mean(np.hypot(fr_x, fr_y))),
    }
    return ax, ay, diag


def _deterioration_rates(
    forcing: Dict[str, np.ndarray],
    rel_speed_ms: np.ndarray,
    length_m: np.ndarray,
    ice_concentration: float,
) -> Tuple[np.ndarray, np.ndarray]:
    """
    Melt rates in metres per day, returned as (lateral, basal).

    Three mechanisms matter. Buoyant convection and wave erosion attack the sides; forced
    convection under the keel attacks the base. Wave erosion is strongly damped by surrounding
    sea ice, which is why bergs locked in the pack survive far longer than those in open water.
    """
    t_w = np.maximum(-1.9, forcing["sst"])

    # Buoyant convection along the sides (El-Tahan et al. 1987).
    m_buoyant = MELT_BUOYANT_CONVECTION_COEFF * t_w + 1.29e-3 * t_w * t_w

    # Wave erosion at the waterline, damped by sea-ice cover (Bigg et al. 1997).
    sea_state = np.minimum(6.0, forcing["hs"])
    damping = 0.5 * (1.0 + math.cos(math.pi * (ice_concentration ** 3)))
    m_wave = 0.42 * sea_state * damping

    # Forced convection at the base (Weeks & Campbell 1973).
    m_basal = 0.58 * (np.maximum(rel_speed_ms, 0.0) ** 0.8) * (t_w + 1.9) / (np.maximum(length_m, 1.0) ** 0.2)

    return np.maximum(0.0, m_buoyant + m_wave), np.maximum(0.0, m_basal)


# --------------------------------------------------------------------------------------
# Integration
# --------------------------------------------------------------------------------------
def _stable_timestep(berg: IcebergProfile, c_water: float) -> float:
    """
    Largest integration step that keeps the velocity equation stable for this berg.

    The drag response timescale is the virtual mass divided by the linearised water-drag
    coefficient. Stepping at a fraction of that keeps RK4 well inside its stability region, which
    is what stops small bergs from diverging.
    """
    m_virtual = berg.consistent_mass_kg() * (1.0 + ICEBERG_ADDED_MASS_COEFF)
    keel_area = max(1.0, berg.length_m * berg.keel_depth_m)
    # Linearise about a representative relative speed between berg and water.
    drag = 0.5 * RHO_SEAWATER * c_water * keel_area * 0.15
    tau = m_virtual / max(drag, 1.0)
    return float(np.clip(tau / TIMESTEP_SAFETY_DIVISOR, MIN_INTERNAL_TIMESTEP_S, MAX_INTERNAL_TIMESTEP_S))


def _integrate_ensemble(
    berg: IcebergProfile,
    forecast_hours: int,
    time_step_hours: int,
    forcing_fn,
    t0_hours: float,
    c_air: np.ndarray,
    c_water: np.ndarray,
    wind_bias: np.ndarray,
    veer_rad: np.ndarray,
    ice_concentration: float,
    apply_melt: bool,
) -> Tuple[List[Dict[str, np.ndarray]], Dict[str, float]]:
    """
    RK4 integration of the whole ensemble at once. Member 0 is always the unperturbed control.

    Forcing is evaluated once per step, at the step midpoint, and held constant across the four
    Runge-Kutta stages. Over half an hour the wind and current fields barely change, whereas the
    velocity response is the stiff part of the system, so this keeps fourth-order accuracy where
    it matters and cuts the environment sampling cost by a factor of four.
    """
    n = c_air.size
    lat = np.full(n, berg.latitude, dtype=np.float64)
    lon = np.full(n, berg.longitude, dtype=np.float64)
    length = np.full(n, berg.length_m, dtype=np.float64)
    width = np.full(n, berg.width_m, dtype=np.float64)
    keel = np.full(n, berg.keel_depth_m, dtype=np.float64)
    sail = np.full(n, berg.sail_height_m, dtype=np.float64)

    # Mass is taken from the geometry so that melt accounting stays self-consistent. Catalogue
    # tonnage is a rough estimate and is often inconsistent with the reported dimensions; mixing
    # the two would make a shrinking berg appear to gain mass.
    mass_kg = np.full(n, berg.consistent_mass_kg(), dtype=np.float64)

    def apply_perturbation(f: Dict[str, np.ndarray]) -> Dict[str, np.ndarray]:
        ua, va = f["ua"] * wind_bias, f["va"] * wind_bias
        out = dict(f)
        out["ua"] = ua * np.cos(veer_rad) - va * np.sin(veer_rad)
        out["va"] = ua * np.sin(veer_rad) + va * np.cos(veer_rad)
        return out

    # Start in equilibrium with the local current, which is where a tracked berg actually is.
    f0 = apply_perturbation(forcing_fn(lat, lon, t0_hours))
    u, v = f0["uo"].copy(), f0["vo"].copy()

    samples: List[Dict[str, np.ndarray]] = []
    budget: Dict[str, float] = {}

    # Pick a timestep short enough for this berg's drag response, then round it so that output
    # steps land exactly on the requested interval.
    dt_target = _stable_timestep(berg, float(np.max(c_water)))
    output_interval_s = max(1.0, time_step_hours * 3600.0)
    output_every = max(1, int(math.ceil(output_interval_s / dt_target)))
    dt = output_interval_s / output_every
    total_steps = int(round(forecast_hours * 3600.0 / dt))
    # Sample the force budget once the berg has spun up, not at t = 0 where it is moving exactly
    # with the current and the water drag is identically zero by construction.
    budget_step = max(1, total_steps // 4)

    def record(step: int) -> None:
        samples.append(
            {
                "hour": int(round(step * dt / 3600.0)),
                "lat": lat.copy(),
                "lon": lon.copy(),
                "u": u.copy(),
                "v": v.copy(),
                "length": length.copy(),
                "mass_t": mass_kg / 1000.0,
            }
        )

    record(0)

    # Small bergs force a short integration step, but the atmosphere and ocean do not change on
    # that timescale. Refreshing the forcing every half hour of simulated time rather than every
    # step cuts the environment sampling cost by an order of magnitude with no visible effect on
    # the track.
    forcing_every = max(1, int(round(FORCING_REFRESH_S / dt)))
    fc: Dict[str, np.ndarray] = {}

    for step in range(total_steps):
        if step % forcing_every == 0:
            t_mid = t0_hours + (step + 0.5 * forcing_every) * dt / 3600.0
            fc = apply_perturbation(forcing_fn(lat, lon, t_mid))
        sail_area = length * sail
        keel_area = length * keel

        def deriv(su: np.ndarray, sv: np.ndarray):
            return _acceleration(su, sv, lat, fc, mass_kg, sail_area, keel_area, length, c_air, c_water)

        k1u, k1v, diag = deriv(u, v)
        k2u, k2v, _ = deriv(u + 0.5 * dt * k1u, v + 0.5 * dt * k1v)
        k3u, k3v, _ = deriv(u + 0.5 * dt * k2u, v + 0.5 * dt * k2v)
        k4u, k4v, _ = deriv(u + dt * k3u, v + dt * k3v)

        if step == budget_step:
            rel = np.hypot(fc["uo"] - u, fc["vo"] - v)
            m_virtual = float(np.mean(mass_kg)) * (1.0 + ICEBERG_ADDED_MASS_COEFF)
            drag = 0.5 * RHO_SEAWATER * float(np.mean(c_water)) * float(np.mean(keel_area)) * max(
                0.01, float(np.mean(rel))
            )
            budget = {
                "air": diag["air"] / 1e6,
                "water": diag["water"] / 1e6,
                "coriolis": diag["coriolis"] / 1e6,
                "pressure": diag["pressure"] / 1e6,
                "wave": diag["wave"] / 1e6,
                "tau_h": (m_virtual / max(drag, 1.0)) / 3600.0,
            }

        u = u + (dt / 6.0) * (k1u + 2.0 * k2u + 2.0 * k3u + k4u)
        v = v + (dt / 6.0) * (k1v + 2.0 * k2v + 2.0 * k3v + k4v)

        # Guard rail. With an adaptive timestep this should never trigger, but a silent NaN
        # propagating into the map layers is far worse than a clamped velocity.
        u = np.clip(np.nan_to_num(u, nan=0.0), -MAX_PHYSICAL_DRIFT_MS, MAX_PHYSICAL_DRIFT_MS)
        v = np.clip(np.nan_to_num(v, nan=0.0), -MAX_PHYSICAL_DRIFT_MS, MAX_PHYSICAL_DRIFT_MS)

        cos_lat = np.maximum(0.02, np.cos(np.radians(lat)))
        lat = np.clip(lat + (v * dt) / 111_132.0, -89.5, -30.0)
        lon = ((lon + (u * dt) / (111_320.0 * cos_lat) + 180.0) % 360.0) - 180.0

        if apply_melt:
            rel = np.hypot(fc["uo"] - u, fc["vo"] - v)
            lateral_per_day, basal_per_day = _deterioration_rates(fc, rel, length, ice_concentration)
            day_fraction = dt / 86400.0
            shrink = lateral_per_day * day_fraction
            length = np.maximum(1.0, length - 2.0 * shrink)
            width = np.maximum(1.0, width - 2.0 * shrink)
            keel = np.maximum(0.5, keel - basal_per_day * day_fraction)
            sail = keel * (berg.sail_height_m / max(berg.keel_depth_m, 1e-6))
            mass_kg = length * width * (keel + sail) * RHO_GLACIAL_ICE

        if (step + 1) % output_every == 0:
            record(step + 1)

    return samples, budget


def predict_iceberg_drift(
    berg: IcebergProfile,
    wind_speed_ms: Optional[float] = None,
    wind_direction_from_deg: Optional[float] = None,
    current_speed_ms: Optional[float] = None,
    current_direction_to_deg: Optional[float] = None,
    forecast_hours: int = 72,
    time_step_hours: int = 6,
    ensemble_members: int = 1,
    t0_hours: float = 0.0,
    ice_concentration: float = 0.0,
    apply_melt: bool = True,
    environment: Optional[EnvironmentModel] = None,
    seed: int = ENSEMBLE_SEED,
) -> IcebergForecastResult:
    """
    Forecast an iceberg track.

    Two forcing modes. Supplying wind and current explicitly gives the v0.1 behaviour of uniform
    forcing, which keeps existing API clients working. Leaving them as None samples the
    time-varying environment fields along the track, which is what the system does in practice.

    Setting ensemble_members above 1 perturbs the drag coefficients and the forcing to produce a
    spread of tracks, from which positional uncertainty radii are derived. Member 0 is always the
    unperturbed control, and it is the track that gets reported.
    """
    env = environment or get_environment()
    n = max(1, int(ensemble_members))
    uniform = wind_speed_ms is not None and current_speed_ms is not None

    if uniform:
        const = _uniform_forcing(
            wind_speed_ms or 0.0,
            wind_direction_from_deg or 0.0,
            current_speed_ms or 0.0,
            current_direction_to_deg or 0.0,
            n,
        )

        def forcing_fn(la: np.ndarray, lo: np.ndarray, t: float) -> Dict[str, np.ndarray]:
            return const
    else:
        def forcing_fn(la: np.ndarray, lo: np.ndarray, t: float) -> Dict[str, np.ndarray]:
            return _field_forcing(env, la, lo, t)

    # Member 0 is the control; the rest carry perturbed drag and forcing.
    c_air = np.full(n, ICEBERG_AIR_DRAG_COEFF)
    c_water = np.full(n, ICEBERG_WATER_DRAG_COEFF)
    wind_bias = np.ones(n)
    veer = np.zeros(n)
    if n > 1:
        rng = np.random.default_rng(seed)
        c_air[1:] = np.maximum(0.2, ICEBERG_AIR_DRAG_COEFF * rng.normal(1.0, 0.18, n - 1))
        c_water[1:] = np.maximum(0.2, ICEBERG_WATER_DRAG_COEFF * rng.normal(1.0, 0.18, n - 1))
        wind_bias[1:] = rng.normal(1.0, 0.15, n - 1)
        veer[1:] = np.radians(rng.normal(0.0, 12.0, n - 1))

    samples, budget = _integrate_ensemble(
        berg, forecast_hours, time_step_hours, forcing_fn, t0_hours,
        c_air, c_water, wind_bias, veer, ice_concentration, apply_melt,
    )

    points: List[TrajectoryPoint] = []
    speeds: List[float] = []
    for s in samples:
        u0, v0 = float(s["u"][0]), float(s["v"][0])
        lat0, lon0 = float(s["lat"][0]), float(s["lon"][0])
        speed_ms = math.hypot(u0, v0)
        speeds.append(speed_ms)

        r50 = r90 = 0.0
        if n > 1:
            dists = [
                haversine_km(lat0, lon0, float(s["lat"][m]), float(s["lon"][m]))
                for m in range(1, n)
            ]
            r50 = float(np.percentile(dists, 50))
            r90 = float(np.percentile(dists, 90))

        length0 = float(s["length"][0])
        points.append(
            TrajectoryPoint(
                hour=int(s["hour"]),
                latitude=round(lat0, 5),
                longitude=round(lon0, 5),
                speed_knots=round(speed_ms * 1.94384, 3),
                heading_deg=round((math.degrees(math.atan2(u0, v0)) + 360.0) % 360.0, 1),
                distance_from_origin_km=round(haversine_km(berg.latitude, berg.longitude, lat0, lon0), 3),
                u_ms=round(u0, 4),
                v_ms=round(v0, 4),
                length_m=round(length0, 1),
                mass_metric_tonnes=round(float(s["mass_t"][0]), 1),
                size_class=berg.model_copy(update={"length_m": length0}).size_class(),
                uncertainty_radius_50_km=round(r50, 2),
                uncertainty_radius_90_km=round(r90, 2),
            )
        )

    initial_mass = float(samples[0]["mass_t"][0])
    final_mass = float(samples[-1]["mass_t"][0])

    return IcebergForecastResult(
        berg_id=berg.berg_id,
        forecast_horizon_hours=forecast_hours,
        trajectory=points,
        net_displacement_km=round(points[-1].distance_from_origin_km, 2) if points else 0.0,
        mean_speed_knots=round(float(np.mean(speeds)) * 1.94384, 3) if speeds else 0.0,
        initial_size_class=berg.size_class(),
        final_size_class=points[-1].size_class if points else berg.size_class(),
        mass_lost_percent=round(100.0 * (1.0 - final_mass / max(initial_mass, 1e-9)), 3),
        final_length_m=round(float(samples[-1]["length"][0]), 1),
        ensemble_members=n,
        force_budget=ForceBudget(
            air_drag_mn=round(budget.get("air", 0.0), 4),
            water_drag_mn=round(budget.get("water", 0.0), 4),
            coriolis_mn=round(budget.get("coriolis", 0.0), 4),
            pressure_gradient_mn=round(budget.get("pressure", 0.0), 4),
            wave_radiation_mn=round(budget.get("wave", 0.0), 4),
            response_timescale_hours=round(budget.get("tau_h", 0.0), 2),
        )
        if budget
        else None,
    )


# --------------------------------------------------------------------------------------
# Collision assessment
# --------------------------------------------------------------------------------------
def closest_approach(
    forecast: IcebergForecastResult,
    route_points: Sequence[Tuple[float, float, float]],
) -> ClosestApproach:
    """
    Closest point of approach between a berg track and a planned route.

    `route_points` is a sequence of (lat, lon, cumulative_hours). Both objects are moving, so the
    comparison is made in time: the berg position is interpolated to each waypoint's arrival
    time, rather than comparing static geometries, which would badly understate the risk.
    """
    best = {"dist": float("inf"), "time": 0.0, "idx": 0, "berg": (0.0, 0.0), "route": (0.0, 0.0)}
    if not forecast.trajectory or not route_points:
        return ClosestApproach(
            berg_id=forecast.berg_id,
            distance_nm=999.0,
            time_hours=0.0,
            waypoint_index=0,
            berg_position=(0.0, 0.0),
            route_position=(0.0, 0.0),
            threat_level="NONE",
            advisory="No overlap between the berg forecast and the planned route.",
        )

    hours = [p.hour for p in forecast.trajectory]
    lats = [p.latitude for p in forecast.trajectory]
    lons = [p.longitude for p in forecast.trajectory]

    for idx, (rlat, rlon, rhours) in enumerate(route_points):
        if rhours < hours[0] or rhours > hours[-1]:
            continue
        blat = float(np.interp(rhours, hours, lats))
        blon = float(np.interp(rhours, hours, lons))
        d = haversine_nm(rlat, rlon, blat, blon)
        if d < best["dist"]:
            best = {"dist": d, "time": rhours, "idx": idx, "berg": (blat, blon), "route": (rlat, rlon)}

    d = best["dist"]
    if d == float("inf"):
        level, advisory = "NONE", "Berg forecast does not overlap the route in time."
        d = 999.0
    elif d < 5.0:
        level = "CRITICAL"
        advisory = f"Berg {forecast.berg_id} passes within {d:.1f} nm. Alter course now."
    elif d < 12.0:
        level = "HIGH"
        advisory = f"Berg {forecast.berg_id} closes to {d:.1f} nm. Plan a diversion and post an extra lookout."
    elif d < 25.0:
        level = "MODERATE"
        advisory = f"Berg {forecast.berg_id} within {d:.1f} nm. Monitor and re-check on the next forecast cycle."
    else:
        level = "LOW"
        advisory = f"Berg {forecast.berg_id} remains {d:.1f} nm clear of the track."

    return ClosestApproach(
        berg_id=forecast.berg_id,
        distance_nm=round(d, 2),
        time_hours=round(best["time"], 1),
        waypoint_index=int(best["idx"]),
        berg_position=(round(best["berg"][0], 4), round(best["berg"][1], 4)),
        route_position=(round(best["route"][0], 4), round(best["route"][1], 4)),
        threat_level=level,
        advisory=advisory,
    )


def exclusion_zones(
    bergs: Sequence[IcebergProfile], radius_nm: float
) -> List[Tuple[float, float, float]]:
    """(lat, lon, radius_nm) circles the route optimiser treats as hard obstacles."""
    return [(b.latitude, b.longitude, radius_nm * (1.6 if b.length_m > 2000.0 else 1.0)) for b in bergs]
