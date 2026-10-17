"""
Risk-constrained, multi-objective polar route optimiser.

WHAT WAS WRONG WITH v0.1
------------------------
The first prototype reported its fuel saving as `baseline = optimised * 1.22`. That is not a
comparison, it is a constant: it would report "22 percent saved" for any route, any ship and any
ice conditions, including a route that saved nothing. It also searched a lattice with no land
mask, so nothing stopped a waypoint being placed on the continent, and it assumed the ship's
speed rather than deriving it.

WHAT THIS DOES INSTEAD
----------------------
Two routes are planned and then sailed through identical physics:

  baseline    the shortest navigable track: it avoids land, because any master would, but it is
              planned with no ice information at all. This is the honest counterfactual for
              "what happens without this system".
  optimised   the same origin and destination, planned with the full ice, risk and fuel model.

The saving is the difference between what those two cost when sailed. If the optimised route is
not cheaper, the system says so. If the baseline would enter ice where POLARIS prohibits
operation, that is reported too, because avoiding a besetting is worth more than any fuel figure.

Both searches are A* over a latitude/longitude lattice with 16-way connectivity. Hard
constraints are land, coastal clearance, RIO below -10, and iceberg exclusion zones. The edge
cost is

    w_fuel * fuel_tonnes + w_time * hours + w_risk * risk_penalty

where the speed on every edge is min(POLARIS ceiling, Lindqvist attainable speed) - the ship's
speed is an output of the physics, never an input.

TIME DEPENDENCE
---------------
Ice and weather evolve while the ship is under way, so edge costs depend on when the ship
arrives. Treating time as part of the search state would multiply the state space; instead, as
is standard in operational weather routing, each node carries the arrival time of the best path
found to it so far. This is a label-correcting approximation, not a proof of optimality, and it
is documented as such rather than claimed otherwise.
"""
from __future__ import annotations

import heapq
import math
import time
from typing import Dict, List, NamedTuple, Optional, Sequence, Tuple

import numpy as np
from pydantic import BaseModel, Field

from src.core.constants import (
    ICEBERG_EXCLUSION_RADIUS_NM,
    MGO_CO2_FACTOR,
    MGO_PRICE_USD_PER_TONNE,
    MIN_COAST_CLEARANCE_NM,
    RIO_PROHIBITED_THRESHOLD,
    USD_TO_INR,
)
from src.core.environment import EnvironmentModel, get_environment
from src.core.geo import (
    great_circle_path,
    haversine_nm,
    initial_bearing_deg,
    lon_delta,
    normalize_lon,
)
from src.core.lindqvist_model import VesselParameters, attainable_speed, calculate_ice_resistance
from src.core.polaris_risk import (
    IceClass,
    IceType,
    classify_ice_type,
    rio_for_uniform_regime,
    speed_limit_for_rio,
)
from src.core.sea_ice import SeaIceModel, get_sea_ice_model
from src.data.landmask import get_coast_field

# Lattice resolution. Half a degree of latitude is 30 nm, which is a sensible waypoint spacing
# for ocean passage planning and fine enough to resolve a lead or a polynya.
DEFAULT_LAT_STEP = 0.5
DEFAULT_LON_STEP = 1.0
GOAL_RADIUS_NM = 20.0
# Ice and weather are cached on 48-hour forecast slices and interpolated between them. Finer
# slicing did not change any planned route materially but doubled the planning time.
FORECAST_SLICE_HOURS = 48.0
MAX_FORECAST_LEAD_HOURS = 240.0
BESET_SPEED_KNOTS = 0.5   # below this the ship is not making way


class RouteWeights(BaseModel):
    """Multi-objective weights. Larger risk weight buys safety with fuel and time."""

    fuel: float = Field(default=1.0, ge=0.0, le=10.0)
    time: float = Field(default=0.35, ge=0.0, le=10.0)
    risk: float = Field(default=1.0, ge=0.0, le=10.0)


class Waypoint(BaseModel):
    """One point on a planned route, with the full model state that produced it."""

    latitude: float
    longitude: float
    speed_knots: float
    ice_concentration: float
    ice_thickness_m: float
    rio_score: int
    is_safe: bool
    segment_fuel_tonnes: float
    cumulative_fuel_tonnes: float
    cumulative_hours: float
    # Added in v1.0
    ice_type: str = ""
    compression_index: float = 0.0
    besetting_risk: str = "LOW"
    distance_from_start_nm: float = 0.0
    heading_deg: float = 0.0
    required_power_kw: float = 0.0
    coast_clearance_nm: float = 0.0
    wind_speed_ms: float = 0.0
    wave_height_m: float = 0.0
    polaris_speed_cap_knots: float = 0.0
    attainable_speed_knots: float = 0.0


class RouteEvaluation(BaseModel):
    """The result of sailing one track through the physics."""

    label: str
    waypoints: List[Waypoint]
    total_distance_nm: float
    total_transit_hours: float
    total_fuel_burn_tonnes: float
    total_co2_tonnes: float
    minimum_rio: int
    mean_rio: float
    max_compression_index: float
    max_ice_thickness_m: float
    is_feasible: bool
    infeasible_reason: str = ""
    prohibited_waypoints: int = 0


class SearchDiagnostics(BaseModel):
    nodes_expanded: int
    nodes_rejected_land: int
    nodes_rejected_rio: int
    nodes_rejected_iceberg: int
    nodes_rejected_clearance: int
    search_ms: float
    lattice_cells: int
    forecast_slices: int
    goal_reached: bool


class OptimizationSummary(BaseModel):
    """Complete planning result. The v0.1 field names are preserved."""

    origin: Tuple[float, float]
    destination: Tuple[float, float]
    total_distance_nm: float
    total_transit_hours: float
    total_fuel_burn_tonnes: float
    baseline_direct_fuel_tonnes: float
    fuel_saved_percentage: float
    minimum_rio: int
    waypoints_count: int
    waypoints: List[Waypoint]
    # Added in v1.0
    optimized: Optional[RouteEvaluation] = None
    baseline: Optional[RouteEvaluation] = None
    time_saved_hours: float = 0.0
    distance_delta_nm: float = 0.0
    co2_saved_tonnes: float = 0.0
    cost_saved_usd: float = 0.0
    cost_saved_inr: float = 0.0
    baseline_would_be_prohibited: bool = False
    vessel_name: str = ""
    ice_class: str = ""
    weights: Optional[RouteWeights] = None
    departure_time_hours: float = 0.0
    search: Optional[SearchDiagnostics] = None
    warnings: List[str] = Field(default_factory=list)
    savings_method: str = (
        "Both routes are sailed through the same ice, POLARIS and Lindqvist models; the saving is "
        "the difference. No fixed multiplier is applied."
    )
    is_synthetic_environment: bool = True


# --------------------------------------------------------------------------------------
# Vessel performance lookup tables
# --------------------------------------------------------------------------------------
class VesselPerformance:
    """
    Precomputed speed and fuel tables for one ship.

    The A* search evaluates hundreds of thousands of edges. Running a bisection on the power
    balance at every one of them would take tens of seconds. Both attainable speed and fuel rate
    are smooth functions of (thickness, concentration, speed), so they are tabulated once and
    interpolated, which is numerically indistinguishable and roughly a thousand times faster.
    """

    H_GRID = np.linspace(0.0, 3.0, 31)
    C_GRID = np.linspace(0.0, 1.0, 21)
    V_GRID = np.linspace(0.5, 18.0, 24)

    def __init__(self, vessel: VesselParameters, installed_power_kw: float) -> None:
        self.vessel = vessel
        self.installed_power_kw = installed_power_kw

        self._fuel = np.zeros((self.V_GRID.size, self.H_GRID.size, self.C_GRID.size))
        self._power = np.zeros_like(self._fuel)
        for vi, v in enumerate(self.V_GRID):
            for hi, h in enumerate(self.H_GRID):
                for ci, c in enumerate(self.C_GRID):
                    res = calculate_ice_resistance(vessel, float(v), float(h), float(c))
                    self._fuel[vi, hi, ci] = res.fuel_burn_rate_kg_per_hour
                    self._power[vi, hi, ci] = res.required_power_kw

        # Attainable speed comes from the same solver the voyage engine uses.
        #
        # An earlier version inverted the power curve here directly, which ignored the propeller
        # thrust limit that binds in heavy ice. The planner was therefore more optimistic than the
        # simulator, and a route it certified as safe could beset the ship when actually sailed.
        # Two components disagreeing about the same physics is worse than either being wrong, so
        # both now call one function.
        self._attainable = np.zeros((self.H_GRID.size, self.C_GRID.size))
        for hi, h in enumerate(self.H_GRID):
            for ci, c in enumerate(self.C_GRID):
                self._attainable[hi, ci] = attainable_speed(
                    vessel, installed_power_kw, float(h), float(c)
                )

        # Best possible fuel per nautical mile, used to keep the A* heuristic admissible.
        open_water = calculate_ice_resistance(vessel, float(self.V_GRID[-1]), 0.0, 0.0)
        self.max_speed_knots = float(self.V_GRID[-1])
        self.min_fuel_per_nm_tonnes = (
            open_water.fuel_burn_rate_kg_per_hour / self.max_speed_knots
        ) / 1000.0

    @staticmethod
    def _interp_index(grid: np.ndarray, values: np.ndarray) -> Tuple[np.ndarray, np.ndarray]:
        pos = np.interp(values, grid, np.arange(grid.size))
        low = np.clip(np.floor(pos).astype(np.int64), 0, grid.size - 1)
        high = np.clip(low + 1, 0, grid.size - 1)
        return low, high, (pos - low)  # type: ignore[return-value]

    def attainable_speed(self, thickness, concentration) -> np.ndarray:
        h = np.clip(np.asarray(thickness, dtype=np.float64), 0.0, self.H_GRID[-1])
        c = np.clip(np.asarray(concentration, dtype=np.float64), 0.0, 1.0)
        hl, hh, hf = self._interp_index(self.H_GRID, h)
        cl, ch, cf = self._interp_index(self.C_GRID, c)
        a = self._attainable
        return (
            a[hl, cl] * (1 - hf) * (1 - cf)
            + a[hh, cl] * hf * (1 - cf)
            + a[hl, ch] * (1 - hf) * cf
            + a[hh, ch] * hf * cf
        )

    def fuel_rate(self, speed, thickness, concentration) -> np.ndarray:
        v = np.clip(np.asarray(speed, dtype=np.float64), self.V_GRID[0], self.V_GRID[-1])
        h = np.clip(np.asarray(thickness, dtype=np.float64), 0.0, self.H_GRID[-1])
        c = np.clip(np.asarray(concentration, dtype=np.float64), 0.0, 1.0)
        vl, vh, vf = self._interp_index(self.V_GRID, v)
        hl, hh, hf = self._interp_index(self.H_GRID, h)
        cl, ch, cf = self._interp_index(self.C_GRID, c)
        f = self._fuel
        lo = (
            f[vl, hl, cl] * (1 - hf) * (1 - cf)
            + f[vl, hh, cl] * hf * (1 - cf)
            + f[vl, hl, ch] * (1 - hf) * cf
            + f[vl, hh, ch] * hf * cf
        )
        hi = (
            f[vh, hl, cl] * (1 - hf) * (1 - cf)
            + f[vh, hh, cl] * hf * (1 - cf)
            + f[vh, hl, ch] * (1 - hf) * cf
            + f[vh, hh, ch] * hf * cf
        )
        return lo * (1 - vf) + hi * vf

    def power(self, speed, thickness, concentration) -> np.ndarray:
        v = np.clip(np.asarray(speed, dtype=np.float64), self.V_GRID[0], self.V_GRID[-1])
        h = np.clip(np.asarray(thickness, dtype=np.float64), 0.0, self.H_GRID[-1])
        c = np.clip(np.asarray(concentration, dtype=np.float64), 0.0, 1.0)
        vl, vh, vf = self._interp_index(self.V_GRID, v)
        hl, _, _ = self._interp_index(self.H_GRID, h)
        cl, _, _ = self._interp_index(self.C_GRID, c)
        return self._power[vl, hl, cl] * (1 - vf) + self._power[vh, hl, cl] * vf


_PERF_CACHE: Dict[str, VesselPerformance] = {}

#: Cached iceberg drift tracks, keyed by (berg id, departure time, horizon).
_BERG_TRACK_CACHE: Dict[Tuple[str, float, int], Tuple[Tuple[float, ...], Tuple[float, ...], Tuple[float, ...]]] = {}


def get_performance(vessel: VesselParameters, installed_power_kw: float) -> VesselPerformance:
    key = f"{vessel.model_dump_json()}|{installed_power_kw}"
    if key not in _PERF_CACHE:
        _PERF_CACHE[key] = VesselPerformance(vessel, installed_power_kw)
    return _PERF_CACHE[key]


# --------------------------------------------------------------------------------------
# Gridded field cache
# --------------------------------------------------------------------------------------
class FieldCache:
    """
    Ice, risk and weather precomputed on the search lattice at several forecast lead times.

    Sampling the ice model per edge would dominate the runtime. Instead every field is evaluated
    once, vectorised over the whole lattice, at 24-hour forecast slices, and the search
    interpolates between slices by arrival time.
    """

    def __init__(
        self,
        lat_min: float,
        lat_max: float,
        lon_min: float,
        lon_max: float,
        lat_step: float,
        lon_step: float,
        ice_class: IceClass,
        perf: VesselPerformance,
        max_hours: float,
        t0_hours: float,
        sea_ice: SeaIceModel,
        environment: EnvironmentModel,
    ) -> None:
        self.lat_min, self.lon_min = lat_min, lon_min
        self.lat_step, self.lon_step = lat_step, lon_step
        self.n_lat = int(round((lat_max - lat_min) / lat_step)) + 1
        self.n_lon = int(round((lon_max - lon_min) / lon_step)) + 1
        self.t0 = t0_hours

        lats = lat_min + np.arange(self.n_lat) * lat_step
        lons_unwrapped = lon_min + np.arange(self.n_lon) * lon_step
        lon_g, lat_g = np.meshgrid(lons_unwrapped, lats)
        lon_wrapped = ((lon_g + 180.0) % 360.0) - 180.0

        self.lats = lats
        self.lons = lons_unwrapped

        # Static layers.
        coast = get_coast_field().sample(lat_g, lon_wrapped)
        self.coast_nm = coast
        self.is_land = coast < 0.0

        # Forecast slices out to the expected passage duration.
        horizon = float(np.clip(max_hours, FORECAST_SLICE_HOURS, MAX_FORECAST_LEAD_HOURS))
        self.slice_hours = np.arange(0.0, horizon + FORECAST_SLICE_HOURS, FORECAST_SLICE_HOURS)
        n_slices = self.slice_hours.size

        shape = (n_slices, self.n_lat, self.n_lon)
        self.conc = np.zeros(shape)
        self.thick = np.zeros(shape)
        self.comp = np.zeros(shape)
        self.rio = np.zeros(shape, dtype=np.int32)
        self.speed = np.zeros(shape)
        self.polaris_cap = np.zeros(shape)
        self.attainable = np.zeros(shape)
        self.fuel_rate = np.zeros(shape)
        self.wind = np.zeros(shape)
        self.wave = np.zeros(shape)

        for si, lead in enumerate(self.slice_hours):
            conc, _ = sea_ice._advected_concentration(lat_g, lon_wrapped, t0_hours, float(lead))
            valid = t0_hours + float(lead)
            div = sea_ice.divergence(lat_g, lon_wrapped, valid)
            comp = sea_ice.compression_index(div)
            thick, _ = sea_ice.thickness(lat_g, lon_wrapped, valid, conc, comp)

            self.conc[si] = conc
            self.comp[si] = comp
            self.thick[si] = thick

            rio = _vectorised_rio(ice_class, thick, conc)
            self.rio[si] = rio
            cap = _vectorised_speed_cap(ice_class, rio)
            att = perf.attainable_speed(thick, conc)
            spd = np.minimum(cap, att)
            self.polaris_cap[si] = cap
            self.attainable[si] = att
            self.speed[si] = spd
            self.fuel_rate[si] = perf.fuel_rate(np.maximum(spd, 0.5), thick, conc)

            u, v, _ = environment.wind_uv(lat_g, lon_wrapped, valid)
            self.wind[si] = np.hypot(u, v)
            scal = environment.scalars(lat_g, lon_wrapped, valid, self.wind[si], conc)
            self.wave[si] = scal["sig_wave_height_m"]

    @property
    def cells(self) -> int:
        return self.n_lat * self.n_lon

    def in_bounds(self, i: int, j: int) -> bool:
        return 0 <= i < self.n_lat and 0 <= j < self.n_lon

    def position(self, i: int, j: int) -> Tuple[float, float]:
        return self.lat_min + i * self.lat_step, self.lon_min + j * self.lon_step

    def _slice_weights(self, hours_since_departure: float) -> Tuple[int, int, float]:
        pos = float(np.clip(hours_since_departure / FORECAST_SLICE_HOURS, 0.0, self.slice_hours.size - 1.0))
        lo = int(math.floor(pos))
        hi = min(lo + 1, self.slice_hours.size - 1)
        return lo, hi, pos - lo

    def at(self, i: int, j: int, hours: float) -> Dict[str, float]:
        """Interpolated model state in cell (i, j) at a given time since departure."""
        lo, hi, f = self._slice_weights(hours)
        g = 1.0 - f
        return {
            "conc": self.conc[lo, i, j] * g + self.conc[hi, i, j] * f,
            "thick": self.thick[lo, i, j] * g + self.thick[hi, i, j] * f,
            "comp": self.comp[lo, i, j] * g + self.comp[hi, i, j] * f,
            "rio": int(round(self.rio[lo, i, j] * g + self.rio[hi, i, j] * f)),
            "speed": self.speed[lo, i, j] * g + self.speed[hi, i, j] * f,
            "cap": self.polaris_cap[lo, i, j] * g + self.polaris_cap[hi, i, j] * f,
            "attainable": self.attainable[lo, i, j] * g + self.attainable[hi, i, j] * f,
            "fuel_rate": self.fuel_rate[lo, i, j] * g + self.fuel_rate[hi, i, j] * f,
            "wind": self.wind[lo, i, j] * g + self.wind[hi, i, j] * f,
            "wave": self.wave[lo, i, j] * g + self.wave[hi, i, j] * f,
            "coast_nm": self.coast_nm[i, j],
            "land": bool(self.is_land[i, j]),
        }


def _vectorised_rio(ice_class: IceClass, thickness: np.ndarray, concentration: np.ndarray) -> np.ndarray:
    """
    RIO over a whole grid.

    Thickness maps to a WMO stage of development, each stage has one risk value for this ship,
    and RIO is the concentration-weighted sum with the remainder treated as ice free.
    """
    from src.core.polaris_risk import ICE_TYPE_THICKNESS_BOUNDS_M, _TABLE_ORDER, risk_value

    tenths = np.clip(np.round(concentration * 10.0), 0, 10).astype(np.int32)
    rv_free = risk_value(ice_class, IceType.ICE_FREE)

    # Build a step function over thickness, in the official table order.
    rv_grid = np.full(thickness.shape, rv_free, dtype=np.int32)
    for ice_type in _TABLE_ORDER[1:]:
        rv_grid = np.where(thickness > _lower_bound_of(ice_type), risk_value(ice_class, ice_type), rv_grid)

    # Below the ice-free concentration threshold there is effectively no ice regime.
    rv_grid = np.where(tenths < 1, rv_free, rv_grid)
    return tenths * rv_grid + (10 - tenths) * rv_free


def _lower_bound_of(ice_type: IceType) -> float:
    from src.core.polaris_risk import ICE_TYPE_THICKNESS_BOUNDS_M, _TABLE_ORDER

    idx = _TABLE_ORDER.index(ice_type)
    if idx <= 1:
        return 0.0
    return ICE_TYPE_THICKNESS_BOUNDS_M[_TABLE_ORDER[idx - 1]]


def _vectorised_speed_cap(ice_class: IceClass, rio: np.ndarray) -> np.ndarray:
    """POLARIS speed ceiling across a grid of RIO values."""
    unique = np.unique(rio)
    cap = np.zeros(rio.shape)
    for value in unique:
        cap = np.where(rio == value, speed_limit_for_rio(ice_class, int(value)), cap)
    return cap


# --------------------------------------------------------------------------------------
# The optimiser
# --------------------------------------------------------------------------------------
class DriftingExclusion(NamedTuple):
    """
    A tracked berg as a keep-out circle that moves along its forecast track.

    Testing against the berg's departure position is wrong for a passage lasting days. A first
    attempt extrapolated a constant drift velocity, which was cheap but diverged badly from the
    real track over 200-plus hours and still let a route pass 3 nm from the centre of a 32 km
    berg. The exclusion now follows the actual RK4 forecast, sampled at coarse steps and
    interpolated, and the radius grows with lead time to reflect forecast uncertainty.
    """

    berg_id: str
    hours: Tuple[float, ...]
    lats: Tuple[float, ...]
    lons: Tuple[float, ...]
    base_radius_nm: float
    uncertainty_growth_nm_per_day: float

    def position_at(self, hours: float) -> Tuple[float, float]:
        clamped = min(max(hours, self.hours[0]), self.hours[-1])
        lat = float(np.interp(clamped, self.hours, self.lats))
        lon = float(np.interp(clamped, self.hours, self.lons))
        return lat, lon

    def radius_at(self, hours: float) -> float:
        return self.base_radius_nm + self.uncertainty_growth_nm_per_day * (max(0.0, hours) / 24.0)


def _intersects_iceberg(exclusions: Sequence[DriftingExclusion], lat: float, lon: float, hours: float) -> bool:
    for berg in exclusions:
        blat, blon = berg.position_at(hours)
        if haversine_nm(lat, lon, blat, blon) < berg.radius_at(hours):
            return True
    return False


_NEIGHBOURS: List[Tuple[int, int]] = [
    (1, 0), (-1, 0), (0, 1), (0, -1),
    (1, 1), (1, -1), (-1, 1), (-1, -1),
    (2, 1), (2, -1), (-2, 1), (-2, -1),
    (1, 2), (1, -2), (-1, 2), (-1, -2),
]


class PolarRouteOptimizer:
    """Plans a passage, then measures it against the route a ship would sail without ice data."""

    def __init__(
        self,
        vessel: Optional[VesselParameters] = None,
        ice_class: IceClass = IceClass.PC5,
        weights: Optional[RouteWeights] = None,
        installed_power_kw: float = 13_500.0,
        sea_ice: Optional[SeaIceModel] = None,
        environment: Optional[EnvironmentModel] = None,
    ) -> None:
        self.vessel = vessel or VesselParameters()
        self.ice_class = ice_class
        self.weights = weights or RouteWeights()
        self.installed_power_kw = getattr(self.vessel, "installed_power_kw", None) or installed_power_kw
        self.sea_ice = sea_ice or get_sea_ice_model()
        self.env = environment or get_environment()
        self.perf = get_performance(self.vessel, self.installed_power_kw)

    # ---------------------------------------------------------------- helpers
    def _build_cache(
        self, start: Tuple[float, float], dest: Tuple[float, float], t0_hours: float,
        lat_step: float, lon_step: float,
    ) -> Tuple[FieldCache, float]:
        """Bounding box around the passage, generous enough to allow a real diversion."""
        lon_ref = start[1]
        dest_lon_unwrapped = lon_ref + lon_delta(lon_ref, dest[1])

        lat_lo = min(start[0], dest[0]) - 4.0
        lat_hi = max(start[0], dest[0]) + 4.0
        lat_lo = max(-78.0, lat_lo)
        lat_hi = min(20.0, lat_hi)

        lon_lo = min(lon_ref, dest_lon_unwrapped) - 9.0
        lon_hi = max(lon_ref, dest_lon_unwrapped) + 9.0

        # Snap the box so the origin lands exactly on a lattice node.
        lat_lo = start[0] - math.ceil((start[0] - lat_lo) / lat_step) * lat_step
        lon_lo = lon_ref - math.ceil((lon_ref - lon_lo) / lon_step) * lon_step

        gc_nm = haversine_nm(start[0], start[1], dest[0], dest[1])
        expected_hours = (gc_nm / 8.0) * 1.4  # pessimistic average speed, generous margin

        cache = FieldCache(
            lat_lo, lat_hi, lon_lo, lon_hi, lat_step, lon_step,
            self.ice_class, self.perf, expected_hours, t0_hours, self.sea_ice, self.env,
        )
        return cache, dest_lon_unwrapped

    def _node_of(self, cache: FieldCache, lat: float, lon_unwrapped: float) -> Tuple[int, int]:
        i = int(round((lat - cache.lat_min) / cache.lat_step))
        j = int(round((lon_unwrapped - cache.lon_min) / cache.lon_step))
        return (
            max(0, min(cache.n_lat - 1, i)),
            max(0, min(cache.n_lon - 1, j)),
        )

    # ------------------------------------------------------------------ A*
    def _search(
        self,
        cache: FieldCache,
        start_node: Tuple[int, int],
        goal_node: Tuple[int, int],
        goal_pos: Tuple[float, float],
        ice_aware: bool,
        exclusions: Sequence["DriftingExclusion"],
        t0_hours: float,
    ) -> Tuple[List[Tuple[int, int]], SearchDiagnostics]:
        """
        A* over the lattice.

        With ice_aware False this is a pure shortest-distance search subject only to land and
        coastal clearance: the baseline a ship would sail with no ice information. With it True
        the full multi-objective cost and every hard constraint apply.
        """
        started = time.perf_counter()
        w = self.weights

        # Admissible heuristic: the cheapest conceivable cost per nautical mile is open water at
        # the ship's maximum speed with no risk penalty. This never over-estimates, so A* stays
        # optimal with respect to the cost model.
        if ice_aware:
            per_nm = w.fuel * self.perf.min_fuel_per_nm_tonnes + w.time / self.perf.max_speed_knots
        else:
            per_nm = 1.0

        def heuristic(i: int, j: int) -> float:
            lat, lon = cache.position(i, j)
            return haversine_nm(lat, normalize_lon(lon), goal_pos[0], goal_pos[1]) * per_nm

        goal_lat, goal_lon = goal_pos
        rejected = {"land": 0, "rio": 0, "iceberg": 0, "clearance": 0}
        expanded = 0

        best_cost: Dict[Tuple[int, int], float] = {start_node: 0.0}
        arrival: Dict[Tuple[int, int], float] = {start_node: 0.0}
        came_from: Dict[Tuple[int, int], Tuple[int, int]] = {}

        open_heap: List[Tuple[float, float, Tuple[int, int]]] = []
        heapq.heappush(open_heap, (heuristic(*start_node), 0.0, start_node))
        closed: set = set()
        goal_reached = False
        final_node = start_node

        while open_heap:
            f_score, g_score, node = heapq.heappop(open_heap)
            if node in closed:
                continue
            closed.add(node)
            expanded += 1

            lat, lon_unwrapped = cache.position(*node)
            lon = normalize_lon(lon_unwrapped)

            if haversine_nm(lat, lon, goal_lat, goal_lon) <= GOAL_RADIUS_NM:
                goal_reached = True
                final_node = node
                break

            if expanded > 400_000:
                break

            t_here = arrival.get(node, 0.0)

            for di, dj in _NEIGHBOURS:
                ni, nj = node[0] + di, node[1] + dj
                if not cache.in_bounds(ni, nj) or (ni, nj) in closed:
                    continue

                state = cache.at(ni, nj, t_here)
                if state["land"]:
                    rejected["land"] += 1
                    continue

                nlat, nlon_unwrapped = cache.position(ni, nj)
                nlon = normalize_lon(nlon_unwrapped)
                dist_to_goal = haversine_nm(nlat, nlon, goal_lat, goal_lon)

                # Coastal clearance is relaxed on the final approach, because the destination is
                # an anchorage close inshore by definition.
                if state["coast_nm"] < MIN_COAST_CLEARANCE_NM and dist_to_goal > GOAL_RADIUS_NM * 2.0:
                    rejected["clearance"] += 1
                    continue

                step_nm = haversine_nm(lat, lon, nlat, nlon)

                if ice_aware:
                    if state["rio"] < RIO_PROHIBITED_THRESHOLD:
                        rejected["rio"] += 1
                        continue
                    # Iceberg exclusion, evaluated at the time the ship would arrive.
                    #
                    # Testing against the berg's departure position is wrong for a passage that
                    # takes days: a tabular berg drifts tens of kilometres a day, so a route
                    # planned clear of it at t=0 can pass within a few miles of it on arrival.
                    # Each berg therefore carries a drift velocity and the test is made against
                    # its extrapolated position.
                    if _intersects_iceberg(exclusions, nlat, nlon, t_here):
                        rejected["iceberg"] += 1
                        continue

                    speed = state["speed"]
                    if speed < BESET_SPEED_KNOTS:
                        rejected["rio"] += 1
                        continue

                    hours = step_nm / speed
                    fuel_t = state["fuel_rate"] * hours / 1000.0
                    penalty = (
                        max(0, -state["rio"]) * 0.6
                        + state["comp"] * 6.0
                        + max(0.0, (MIN_COAST_CLEARANCE_NM * 2.0 - state["coast_nm"])) * 0.05
                    )
                    step_cost = w.fuel * fuel_t + w.time * hours + w.risk * penalty
                    new_time = t_here + hours
                else:
                    step_cost = step_nm
                    new_time = t_here + step_nm / max(self.perf.max_speed_knots, 1.0)

                tentative = g_score + step_cost
                if tentative < best_cost.get((ni, nj), float("inf")):
                    best_cost[(ni, nj)] = tentative
                    arrival[(ni, nj)] = new_time
                    came_from[(ni, nj)] = node
                    heapq.heappush(open_heap, (tentative + heuristic(ni, nj), tentative, (ni, nj)))

        path: List[Tuple[int, int]] = []
        if goal_reached or final_node != start_node:
            cursor = final_node
            while cursor in came_from:
                path.append(cursor)
                cursor = came_from[cursor]
            path.append(start_node)
            path.reverse()

        diagnostics = SearchDiagnostics(
            nodes_expanded=expanded,
            nodes_rejected_land=rejected["land"],
            nodes_rejected_rio=rejected["rio"],
            nodes_rejected_iceberg=rejected["iceberg"],
            nodes_rejected_clearance=rejected["clearance"],
            search_ms=round((time.perf_counter() - started) * 1000.0, 1),
            lattice_cells=cache.cells,
            forecast_slices=int(cache.slice_hours.size),
            goal_reached=goal_reached,
        )
        return path, diagnostics

    # ------------------------------------------------------------ evaluation
    def evaluate(
        self,
        cache: FieldCache,
        points: Sequence[Tuple[float, float]],
        label: str,
        t0_hours: float,
    ) -> RouteEvaluation:
        """
        Sail a track through the physics and account for it.

        This is the single place fuel, time and risk are computed, and both the optimised and the
        baseline route go through it unchanged. That is what makes the comparison meaningful.
        """
        waypoints: List[Waypoint] = []
        cum_fuel = cum_hours = cum_dist = 0.0
        rios: List[int] = []
        max_comp = max_thick = 0.0
        prohibited = 0
        infeasible_reason = ""

        for idx, (lat, lon) in enumerate(points):
            i, j = self._nearest_cell(cache, lat, lon)
            state = cache.at(i, j, cum_hours)

            rio = state["rio"]
            rios.append(rio)
            max_comp = max(max_comp, state["comp"])
            max_thick = max(max_thick, state["thick"])
            if rio < RIO_PROHIBITED_THRESHOLD:
                prohibited += 1
                if not infeasible_reason:
                    infeasible_reason = (
                        f"POLARIS prohibits operation at waypoint {idx} "
                        f"({lat:.2f}, {lon:.2f}): RIO {rio} is below {RIO_PROHIBITED_THRESHOLD}."
                    )

            seg_fuel = 0.0
            seg_hours = 0.0
            heading = 0.0
            speed = max(state["speed"], BESET_SPEED_KNOTS)
            if idx > 0:
                plat, plon = points[idx - 1]
                seg_nm = haversine_nm(plat, plon, lat, lon)
                heading = initial_bearing_deg(plat, plon, lat, lon)
                seg_hours = seg_nm / speed
                seg_fuel = state["fuel_rate"] * seg_hours / 1000.0
                cum_dist += seg_nm
                cum_hours += seg_hours
                cum_fuel += seg_fuel

            waypoints.append(
                Waypoint(
                    latitude=round(lat, 4),
                    longitude=round(lon, 4),
                    speed_knots=round(speed, 2),
                    ice_concentration=round(state["conc"], 3),
                    ice_thickness_m=round(state["thick"], 3),
                    rio_score=rio,
                    is_safe=rio >= RIO_PROHIBITED_THRESHOLD,
                    segment_fuel_tonnes=round(seg_fuel, 3),
                    cumulative_fuel_tonnes=round(cum_fuel, 2),
                    cumulative_hours=round(cum_hours, 2),
                    ice_type=classify_ice_type(state["thick"], state["conc"]).value,
                    compression_index=round(state["comp"], 3),
                    besetting_risk="HIGH" if state["comp"] >= 0.6 and state["conc"] >= 0.7
                    else ("MODERATE" if state["comp"] >= 0.35 and state["conc"] >= 0.5 else "LOW"),
                    distance_from_start_nm=round(cum_dist, 1),
                    heading_deg=round(heading, 1),
                    required_power_kw=round(float(self.perf.power(speed, state["thick"], state["conc"])), 1),
                    coast_clearance_nm=round(float(state["coast_nm"]), 1),
                    wind_speed_ms=round(state["wind"], 1),
                    wave_height_m=round(state["wave"], 2),
                    polaris_speed_cap_knots=round(state["cap"], 2),
                    attainable_speed_knots=round(state["attainable"], 2),
                )
            )

        return RouteEvaluation(
            label=label,
            waypoints=waypoints,
            total_distance_nm=round(cum_dist, 1),
            total_transit_hours=round(cum_hours, 1),
            total_fuel_burn_tonnes=round(cum_fuel, 2),
            total_co2_tonnes=round(cum_fuel * MGO_CO2_FACTOR, 2),
            minimum_rio=int(min(rios)) if rios else 0,
            mean_rio=round(float(np.mean(rios)), 2) if rios else 0.0,
            max_compression_index=round(max_comp, 3),
            max_ice_thickness_m=round(max_thick, 3),
            is_feasible=prohibited == 0,
            infeasible_reason=infeasible_reason,
            prohibited_waypoints=prohibited,
        )

    def _build_exclusions(
        self,
        start: Tuple[float, float],
        dest: Tuple[float, float],
        cache: FieldCache,
        t0_hours: float,
    ) -> List[DriftingExclusion]:
        """
        Build moving keep-out zones from the tracked iceberg catalogue.

        Only bergs whose start position lies near the corridor are integrated, because running
        the drift model over the whole catalogue would add more time to a plan than the search
        itself takes, and a berg a thousand miles away cannot reach the track.
        """
        try:
            from src.core.iceberg_tracker import predict_iceberg_drift
            from src.data.icebergs import get_iceberg_profiles
        except Exception:  # pragma: no cover - the catalogue is an optional layer
            return []

        corridor = great_circle_path(start[0], start[1], dest[0], dest[1], 24)
        horizon = float(np.clip(cache.slice_hours[-1], 24.0, MAX_FORECAST_LEAD_HOURS))
        exclusions: List[DriftingExclusion] = []

        for berg in get_iceberg_profiles():
            # A berg can only matter if it starts within reach of the corridor. The screening
            # distance allows for several hundred miles of drift over a long passage.
            if min(haversine_nm(berg.latitude, berg.longitude, lat, lon) for lat, lon in corridor) > 500.0:
                continue

            # Berg tracks depend only on the berg and the departure time, not on the route, so
            # they are cached across plans. Without this, integrating the catalogue doubled the
            # time to produce a plan every single time.
            key = (berg.berg_id, round(t0_hours, 1), int(horizon))
            track = _BERG_TRACK_CACHE.get(key)
            if track is None:
                forecast = predict_iceberg_drift(
                    berg,
                    forecast_hours=int(horizon),
                    time_step_hours=24,
                    t0_hours=t0_hours,
                    ensemble_members=1,
                    environment=self.env,
                )
                track = (
                    tuple(float(p.hour) for p in forecast.trajectory),
                    tuple(p.latitude for p in forecast.trajectory),
                    tuple(p.longitude for p in forecast.trajectory),
                )
                if len(_BERG_TRACK_CACHE) > 256:
                    _BERG_TRACK_CACHE.clear()
                _BERG_TRACK_CACHE[key] = track
            hours, lats, lons = track
            if len(hours) < 2:
                continue

            # The berg's own half-length, plus the standing clearance. A 32 km berg is 8.6 nm
            # across, so a flat 12 nm keep-out would put a ship inside it.
            half_length_nm = (berg.length_m / 1852.0) * 0.5
            exclusions.append(
                DriftingExclusion(
                    berg_id=berg.berg_id,
                    hours=hours,
                    lats=lats,
                    lons=lons,
                    base_radius_nm=ICEBERG_EXCLUSION_RADIUS_NM + half_length_nm,
                    # Positional uncertainty grows with lead time; the ensemble spread for a
                    # tabular berg is a few kilometres a day.
                    uncertainty_growth_nm_per_day=1.5,
                )
            )
        return exclusions

    @staticmethod
    def _nearest_cell(cache: FieldCache, lat: float, lon: float) -> Tuple[int, int]:
        i = int(round((lat - cache.lat_min) / cache.lat_step))
        # Unwrap the longitude into the cache frame before indexing.
        base = normalize_lon(cache.lon_min)
        j = int(round((cache.lon_min + lon_delta(base, lon) - cache.lon_min) / cache.lon_step))
        return max(0, min(cache.n_lat - 1, i)), max(0, min(cache.n_lon - 1, j))

    # --------------------------------------------------------------- planning
    def optimize_route(
        self,
        start_lat: float,
        start_lon: float,
        dest_lat: float,
        dest_lon: float,
        grid_resolution_deg: float = DEFAULT_LAT_STEP,
        departure_time_hours: float = 0.0,
        avoid_icebergs: bool = True,
    ) -> OptimizationSummary:
        """Plan the passage and measure it against the ice-blind baseline."""
        lat_step = float(np.clip(grid_resolution_deg, 0.25, 2.0))
        lon_step = lat_step * 2.0
        start = (start_lat, start_lon)
        dest = (dest_lat, dest_lon)
        warnings: List[str] = []

        cache, dest_lon_unwrapped = self._build_cache(start, dest, departure_time_hours, lat_step, lon_step)
        start_node = self._node_of(cache, start_lat, cache.lon_min + lon_delta(normalize_lon(cache.lon_min), start_lon))
        goal_node = self._node_of(cache, dest_lat, dest_lon_unwrapped)

        exclusions: List[DriftingExclusion] = []
        if avoid_icebergs:
            exclusions = self._build_exclusions(start, dest, cache, departure_time_hours)

        # 1. The ice-blind baseline: shortest navigable track, land and clearance only.
        base_path, base_diag = self._search(
            cache, start_node, goal_node, dest, ice_aware=False, exclusions=(), t0_hours=departure_time_hours
        )
        # 2. The ice-aware optimised route.
        opt_path, opt_diag = self._search(
            cache, start_node, goal_node, dest, ice_aware=True, exclusions=exclusions,
            t0_hours=departure_time_hours,
        )

        if not opt_diag.goal_reached:
            warnings.append(
                "The risk-constrained search could not reach the destination without violating a hard "
                "constraint. The reported route is the best partial path found."
            )
        if not base_diag.goal_reached:
            warnings.append("The unconstrained baseline search did not reach the destination.")

        base_points = self._path_to_points(cache, base_path, start, dest)
        opt_points = self._path_to_points(cache, opt_path, start, dest)
        if len(base_points) < 2:
            base_points = great_circle_path(start_lat, start_lon, dest_lat, dest_lon, 40)
            warnings.append("Baseline fell back to the great-circle track.")
        if len(opt_points) < 2:
            opt_points = base_points
            warnings.append("Optimised route fell back to the baseline track.")

        baseline = self.evaluate(cache, base_points, "Ice-blind shortest navigable route", departure_time_hours)
        optimized = self.evaluate(cache, opt_points, "POLARIS-constrained optimised route", departure_time_hours)

        # The saving is a difference between two model runs, never a multiplier.
        fuel_saved_pct = 0.0
        if baseline.total_fuel_burn_tonnes > 1e-9:
            fuel_saved_pct = (
                (baseline.total_fuel_burn_tonnes - optimized.total_fuel_burn_tonnes)
                / baseline.total_fuel_burn_tonnes
            ) * 100.0

        if fuel_saved_pct < 0:
            warnings.append(
                "The optimised route burns more fuel than the ice-blind baseline. It is being "
                "recommended because it is safer, not cheaper: check the RIO and compression figures."
            )
        if not baseline.is_feasible:
            warnings.append(
                "The ice-blind baseline enters ice where POLARIS prohibits operation. Sailing it would "
                "risk besetting or structural damage, so its fuel figure is what the passage would cost "
                "if it were survivable."
            )

        fuel_delta = baseline.total_fuel_burn_tonnes - optimized.total_fuel_burn_tonnes

        return OptimizationSummary(
            origin=(start_lat, start_lon),
            destination=(dest_lat, dest_lon),
            total_distance_nm=optimized.total_distance_nm,
            total_transit_hours=optimized.total_transit_hours,
            total_fuel_burn_tonnes=optimized.total_fuel_burn_tonnes,
            baseline_direct_fuel_tonnes=baseline.total_fuel_burn_tonnes,
            fuel_saved_percentage=round(fuel_saved_pct, 2),
            minimum_rio=optimized.minimum_rio,
            waypoints_count=len(optimized.waypoints),
            waypoints=optimized.waypoints,
            optimized=optimized,
            baseline=baseline,
            time_saved_hours=round(baseline.total_transit_hours - optimized.total_transit_hours, 1),
            distance_delta_nm=round(optimized.total_distance_nm - baseline.total_distance_nm, 1),
            co2_saved_tonnes=round(fuel_delta * MGO_CO2_FACTOR, 2),
            cost_saved_usd=round(fuel_delta * MGO_PRICE_USD_PER_TONNE, 2),
            cost_saved_inr=round(fuel_delta * MGO_PRICE_USD_PER_TONNE * USD_TO_INR, 2),
            baseline_would_be_prohibited=not baseline.is_feasible,
            vessel_name=self.vessel.name,
            ice_class=self.ice_class.value,
            weights=self.weights,
            departure_time_hours=departure_time_hours,
            search=opt_diag,
            warnings=warnings,
        )

    @staticmethod
    def _path_to_points(
        cache: FieldCache,
        path: Sequence[Tuple[int, int]],
        start: Tuple[float, float],
        dest: Tuple[float, float],
    ) -> List[Tuple[float, float]]:
        if not path:
            return []
        points = [start]
        for i, j in path[1:]:
            lat, lon_unwrapped = cache.position(i, j)
            points.append((lat, normalize_lon(lon_unwrapped)))
        if haversine_nm(points[-1][0], points[-1][1], dest[0], dest[1]) > 1.0:
            points.append(dest)
        return points
