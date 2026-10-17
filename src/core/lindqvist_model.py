"""
Ice resistance and powering: Lindqvist (1989) plus an open-water baseline.

WHY THIS MODULE EXISTS
----------------------
Everything downstream of the route optimiser needs one number the optimiser is not allowed
to assume: how fast this hull can actually go, here, in this ice. Speed has to be an *output*
of the physics, because if it is an input then the fuel figure, the emissions figure and the
"savings" figure are all assertions rather than results (build spec P1). So this file computes
resistance, converts resistance into required power, and then inverts the balance to get
attainable speed.

WHAT IS MODELLED
----------------
    R_total(v, h, C) = R_open_water(v) + C^n * R_ice(v, h)

`R_ice` is Lindqvist's three-component level-ice method: crushing at the stem, bending the
sheet into cusps, and submerging and sliding the broken floes aft. Lindqvist is a level-ice
method, valid at 10/10 concentration, so a broken field is handled by scaling with
concentration raised to `ICE_CONCENTRATION_EXPONENT`. `R_open_water` is an ITTC-1957 friction
line over a Denny-Mumford wetted surface plus a residuary term, and it is what keeps total
resistance continuous as the ice thins to nothing. The v0.1 model jumped discontinuously
between an ice branch and a hard-coded 10 kN floor.

CHANGES MADE TO THE v0.1 FORMULATION, AND WHY
---------------------------------------------
The v0.1 file carried a garbled transcription of Lindqvist. Every term was checked against
the published form (Lindqvist, POAC'89, as reproduced in Fan T. et al., "Estimation of ice
resistance and sensitivity analysis for an icebreaker", Advances in Polar Science 30(4), 2019,
equations 1 to 4) and four errors were corrected.

1.  Crushing. v0.1 computed `0.5 sigma_b h^2 (tan(phi) + mu cos(phi)/sin(alpha)) / cos(alpha)`.
    The friction term is divided by `cos(psi)`, not `sin(alpha)`, and the whole expression is
    divided by `(1 - mu sin(phi)/cos(psi))`, a denominator v0.1 dropped entirely. That
    denominator is what makes a high-friction hull disproportionately expensive, which is
    precisely the effect an ice-navigation tool must not lose.

2.  Bending. v0.1 computed `0.003 E h^1.5 B tan(psi)/cos(phi)`. Two problems. It is
    dimensionally inconsistent, giving Pa m^2.5 rather than newtons, and it puts Young's
    modulus in the numerator, so a stiffer ice sheet comes out *harder* to break. Physically
    the opposite holds: a stiffer plate has a longer characteristic length on its elastic
    foundation, so the cusp that breaks off is larger and fails at a lower load for the same
    flexural strength. Lindqvist drives the term with flexural strength and divides by
    `sqrt(E / (12 (1 - nu^2) rho_w g))`, which is that length scale. Restored.

3.  Submergence. v0.1 used the shorthand `(1 + 2 mu L/B)` for the friction of floes sliding
    aft along the hull. Lindqvist writes that friction out over the actual wetted geometry,
    `0.7 L - T/tan(phi) - B/(4 tan(alpha)) + T cos(phi) cos(psi) sqrt(...)`, which is what
    makes the term respond to hull form at all. Restored.

4.  Velocity correction. v0.1 applied a single `(1 + 0.4 v / sqrt(g h))` to all three terms.
    Lindqvist applies `(1 + 1.4 v / sqrt(g h))` to crushing and bending and a much stronger
    `(1 + 9.4 v / sqrt(g L))` to submergence, because submergence is dominated by accelerating
    and clearing broken ice along the hull, a ship-scale rather than an ice-scale process.
    Using one factor for both gets the speed sensitivity of a long ship in thin ice badly
    wrong. Restored.

Two smaller corrections. The flare angle is not an independent input: Lindqvist fixes it by
`psi = arctan(tan(phi) / sin(alpha))`, so `VesselParameters.flare_angle_deg` is now carried
for reporting only and the formula uses the derived value (the presets store the derived value
so the two agree). And the inline densities 1025/917 were replaced by the project constants
1027/920.

One honest caveat on a coefficient. The leading constant on the bending term appears in the
literature both as 37/64 and as 27/64. We use 37/64, which is the value in the reference above
and the value that reproduces its published results.

VALIDATION
----------
Against Fan et al. (2019) Table 3, a 118 m x 21.5 m x 7.5 m icebreaker in 500.8 kPa ice, this
implementation reproduces their published Lindqvist column to within 1.5 to 3.4 percent at
1.6 m thickness and 10.5 percent at 0.95 m. Most of the residual comes from ice density: they
used 900 kg/m3 where the project constant is 920, which moves the submergence term by about
nine percent. That is inside the scatter of the method itself, quoted at roughly 13 percent
mean error against model tests. `tests/test_lindqvist_extended.py` pins this comparison so a
coefficient cannot drift unnoticed.

One further note on Young's modulus, because it changes the answer. The project constant is
2 GPa, an effective (static) modulus; Lindqvist's own calibration and most of the literature
use the dynamic modulus, 5 to 9 GPa. Since the bending term divides by sqrt(E), 2 GPa makes it
roughly twice as large. The model is therefore conservative on the default: it will under-
promise speed rather than over-promise it. We keep the project constant rather than tune it to
a friendlier answer, and the modulus stays a caller-supplied argument so this can be revisited
with a stated reason.

POWERING, AND WHY THERE ARE TWO SPEED LIMITS
--------------------------------------------
Required power is `R_total * v / eta_D`. That is the classical relation and it is what the API
reports, but on its own it over-predicts attainable speed in heavy ice, because it assumes the
propeller can deliver whatever thrust is asked of it. It cannot: as the ship slows the
propeller approaches bollard conditions and open-water efficiency collapses. So
`attainable_speed` binds two limits and takes the lower:

  * a power limit, `R_total(v) v / eta_D = P_available`, solved by bisection, and
  * a thrust limit, `C^n R_ice(v) = T_net(v)`, using the Finnish-Swedish Ice Class Rules net
    thrust relation `T = Ke (P_D D)^(2/3)` with the rules' speed decay
    `1 - (1/3)(v/v_ow) - (2/3)(v/v_ow)^2`. `T_net` is already net of open-water resistance,
    which is why it is balanced against the ice term alone.

If the net bollard thrust cannot push the ship through the ice fast enough to hold steerage
way, it cannot make way at all. That is besetting: `attainable_speed` returns 0.0 and
`ResistanceResult.is_beset` is set. It is a real operational state and the model has to be
able to say so, rather than always returning some small positive speed that would let a
planner route straight through a ridge field.

Propeller-ice interaction degrades both the quasi-propulsive coefficient and the delivered
thrust. Milling, blockage of the propeller inflow by broken floes, and ventilation cost a real
ship up to about a quarter of its open-water QPC in thick, close ice; one severity factor,
scaled by thickness and concentration, is applied to both.
"""
from __future__ import annotations

import math
from typing import Callable, Dict, List, Optional

from pydantic import BaseModel, Field

from src.core.constants import (
    BOLLARD_PULL_COEFF_NOZZLE,
    BOLLARD_PULL_COEFF_OPEN_PROP,
    DEFAULT_BLOCK_COEFFICIENT,
    DENNY_MUMFORD_COEFF,
    GRAVITY,
    HULL_FORM_FACTOR,
    ICE_CONCENTRATION_EXPONENT,
    ICE_POISSON_RATIO,
    ICE_PROPULSION_EFFICIENCY_LOSS,
    ITTC57_NUMERATOR,
    LINDQVIST_BENDING_COEFF,
    LINDQVIST_SPEED_COEFF_BREAKING,
    LINDQVIST_SPEED_COEFF_SUBMERGENCE,
    MAX_SHIP_SPEED_KNOTS,
    MGO_CO2_FACTOR,
    MIN_PROPULSIVE_EFFICIENCY,
    MIN_STEERAGE_SPEED_KNOTS,
    MS_PER_KNOT,
    RESIDUARY_CR_AT_FN_REF,
    RESIDUARY_FN_EXPONENT,
    RESIDUARY_FN_REF,
    RHO_SEA_ICE,
    RHO_SEAWATER,
    SEAWATER_KINEMATIC_VISCOSITY,
    SHAFT_TRANSMISSION_EFFICIENCY,
)
from src.core.polaris_risk import IceClass

# Numerical guards. The friction line is undefined near Re = 100, and the Lindqvist speed
# correction carries a 1/sqrt(h), so both need a floor well below any real operating point.
_MIN_REYNOLDS = 1.0e5
_MIN_ICE_THICKNESS_M = 1.0e-4
_BISECTION_ITERATIONS = 80
_SPEED_TOLERANCE_KNOTS = 1.0e-4


# --------------------------------------------------------------------------------------
# Vessel
# --------------------------------------------------------------------------------------
class VesselParameters(BaseModel):
    """
    Hull form and machinery, in the minimum set Lindqvist and the powering balance need.

    The defaults describe the MV Vasiliy Golovnin, the ship NCPOR actually charters for the
    Indian Antarctic Expedition, so an API caller who supplies nothing still gets a physically
    meaningful answer rather than a toy.
    """

    name: str = "MV Polar Explorer"
    display_name: str = Field(default="MV Polar Explorer", description="Label for the interface")
    ice_class: IceClass = Field(default=IceClass.PC5, description="POLARIS ice class of the hull")

    length_m: float = Field(default=167.0, description="Vessel length overall in meters")
    waterline_length_m: Optional[float] = Field(
        default=None, description="Waterline length; defaults to 0.96 * LOA when not supplied"
    )
    beam_m: float = Field(default=22.6, description="Vessel waterline breadth/beam in meters")
    draft_m: float = Field(default=8.5, description="Vessel design draft in meters")
    block_coefficient: float = Field(
        default=DEFAULT_BLOCK_COEFFICIENT, description="Cb, used for the wetted-surface estimate"
    )

    stem_angle_deg: float = Field(default=25.0, description="Stem inclination angle in degrees")
    waterline_angle_deg: float = Field(default=30.0, description="Waterline entrance angle in degrees")
    flare_angle_deg: float = Field(
        default=43.0,
        description=(
            "Reported flare angle. Lindqvist derives its own psi from the stem and waterline "
            "angles, so this field is carried for display and is not used in the formula."
        ),
    )
    hull_friction_coeff: float = Field(default=0.15, description="Friction coefficient between ice and hull")
    propulsion_efficiency: float = Field(
        default=0.65,
        description="Open-water quasi-propulsive coefficient. Degraded internally in ice.",
    )
    sfoc_g_per_kwh: float = Field(default=195.0, description="Specific fuel oil consumption in g/kWh")

    installed_power_kw: float = Field(default=13500.0, description="Total installed propulsion power")
    propeller_diameter_m: float = Field(default=5.2, description="Propeller diameter, for bollard pull")
    n_propellers: int = Field(default=1, description="Number of propellers")
    ducted_propeller: bool = Field(default=False, description="True if the propeller runs in a nozzle")

    # ---------------------------------------------------------------- derived geometry
    def lwl(self) -> float:
        """Waterline length, falling back to 0.96 of LOA, the usual ratio for this hull type."""
        return float(self.waterline_length_m or 0.96 * self.length_m)

    def wetted_surface_m2(self) -> float:
        """
        Wetted surface by the Denny-Mumford approximation, S = 1.7 L T + Cb L B.

        Chosen because it needs only main dimensions, which is all a decision-support tool can
        assume it has for a chartered ship. It is good to roughly 3 to 5 percent on full-form
        hulls, well inside the uncertainty of the residuary term it feeds.
        """
        lwl = self.lwl()
        return DENNY_MUMFORD_COEFF * lwl * self.draft_m + self.block_coefficient * lwl * self.beam_m

    def displacement_tonnes(self) -> float:
        """Moulded displacement from Cb. Reporting only; nothing in the physics uses it."""
        return self.block_coefficient * self.lwl() * self.beam_m * self.draft_m * RHO_SEAWATER / 1000.0

    def lindqvist_flare_angle_deg(self) -> float:
        """
        The flare angle Lindqvist actually uses: psi = arctan(tan(phi) / sin(alpha)).

        The three bow angles are not independent. Letting a caller set all three lets them
        describe a hull that cannot exist, and the resistance then responds to a parameter that
        is really a consequence of the other two.
        """
        phi = math.radians(self.stem_angle_deg)
        alpha = math.radians(max(1.0, self.waterline_angle_deg))
        return math.degrees(math.atan(math.tan(phi) / math.sin(alpha)))

    def bollard_pull_kn(self, power_kw: Optional[float] = None) -> float:
        """
        Net bollard pull from the Finnish-Swedish Ice Class Rules, T = Ke (P_D D)^(2/3).

        P_D is delivered power, so brake power is first reduced by the shaft transmission
        efficiency. Ke is 0.78 for an open propeller and 0.98 in a nozzle. For a 13.5 MW
        single-screw ship on a 5.2 m propeller this gives about 1300 kN, or 133 tonnes, the
        right order for a ship of this class.
        """
        p_brake = self.installed_power_kw if power_kw is None else max(0.0, power_kw)
        p_delivered = p_brake * SHAFT_TRANSMISSION_EFFICIENCY
        ke = BOLLARD_PULL_COEFF_NOZZLE if self.ducted_propeller else BOLLARD_PULL_COEFF_OPEN_PROP
        return ke * (p_delivered * self.propeller_diameter_m) ** (2.0 / 3.0)


class ResistanceResult(BaseModel):
    """
    One resistance and powering solution, with its working shown.

    `terms` carries every intermediate the interface needs to display the arithmetic, per build
    spec P6. Nothing on screen should be a number the user cannot trace back to an input.
    """

    velocity_knots: float
    ice_thickness_m: float
    ice_concentration: float

    crushing_resistance_kn: float
    bending_resistance_kn: float
    submergence_resistance_kn: float
    open_water_resistance_kn: float = 0.0
    ice_resistance_kn: float = 0.0
    total_resistance_kn: float

    required_power_kw: float
    fuel_burn_rate_kg_per_hour: float
    fuel_per_nm_kg: float = 0.0
    co2_kg_per_hour: float = 0.0

    is_beset: bool = False
    terms: Dict[str, float] = Field(default_factory=dict)


# --------------------------------------------------------------------------------------
# Open water
# --------------------------------------------------------------------------------------
def _friction_coefficient(reynolds: float) -> float:
    """ITTC-1957 model-ship correlation line, Cf = 0.075 / (log10(Re) - 2)^2."""
    re = max(_MIN_REYNOLDS, reynolds)
    return ITTC57_NUMERATOR / (math.log10(re) - 2.0) ** 2


def open_water_resistance(vessel: VesselParameters, velocity_knots: float) -> Dict[str, float]:
    """
    Calm-water resistance of the bare hull in kN, with its components exposed.

    Friction uses the ITTC-1957 line over a Denny-Mumford wetted surface, scaled by a form
    factor (1 + k). Icebreaking hulls sit at the high end of the usual range, because a sloping
    stem with no bulb and a wide, blunt forebody separates early, so 1.30 is used.

    The residuary term is a two-parameter fit, `Cr = Cr_ref (Fn / Fn_ref)^4`. Thin-ship theory
    gives wave resistance growing as Fn^4 well below the hump, which is where these ships live:
    a 167 m hull at 15 knots is only at Fn = 0.19. The reference coefficient is calibrated so
    that a 167 m, 13.5 MW ice-class hull needs about 7 MW at 15 knots and tops out near 16 to
    17 knots at full power, which matches published figures for the class. It is a calibration,
    not a first-principles result, and is labelled as such rather than dressed up.
    """
    v_ms = max(0.0, velocity_knots) * MS_PER_KNOT
    lwl = vessel.lwl()
    surface = vessel.wetted_surface_m2()

    if v_ms < 1.0e-6:
        return {
            "frictional_kn": 0.0,
            "residuary_kn": 0.0,
            "total_kn": 0.0,
            "reynolds": 0.0,
            "froude": 0.0,
            "cf": 0.0,
            "cr": 0.0,
            "wetted_surface_m2": surface,
        }

    reynolds = v_ms * lwl / SEAWATER_KINEMATIC_VISCOSITY
    cf = _friction_coefficient(reynolds)
    froude = v_ms / math.sqrt(GRAVITY * lwl)
    cr = RESIDUARY_CR_AT_FN_REF * (froude / RESIDUARY_FN_REF) ** RESIDUARY_FN_EXPONENT

    dynamic = 0.5 * RHO_SEAWATER * surface * v_ms * v_ms
    r_friction = dynamic * cf * HULL_FORM_FACTOR
    r_residuary = dynamic * cr

    return {
        "frictional_kn": r_friction / 1000.0,
        "residuary_kn": r_residuary / 1000.0,
        "total_kn": (r_friction + r_residuary) / 1000.0,
        "reynolds": reynolds,
        "froude": froude,
        "cf": cf,
        "cr": cr,
        "wetted_surface_m2": surface,
    }


# --------------------------------------------------------------------------------------
# Lindqvist level-ice resistance
# --------------------------------------------------------------------------------------
def _lindqvist_static_terms(
    vessel: VesselParameters,
    ice_thickness_m: float,
    flexural_strength_kpa: float,
    elastic_modulus_mpa: float,
) -> Dict[str, float]:
    """
    The three Lindqvist components at zero speed, in newtons.

    Separating the static terms from the velocity correction matters, because the correction
    differs between breaking and submergence, and because `attainable_speed` needs the
    zero-speed resistance on its own to test for besetting.
    """
    h = ice_thickness_m
    if h <= _MIN_ICE_THICKNESS_M:
        return {"crushing_n": 0.0, "bending_n": 0.0, "submergence_n": 0.0}

    phi = math.radians(vessel.stem_angle_deg)
    alpha = math.radians(max(1.0, vessel.waterline_angle_deg))
    psi = math.radians(vessel.lindqvist_flare_angle_deg())
    mu = vessel.hull_friction_coeff

    b = vessel.beam_m
    t = vessel.draft_m
    lwl = vessel.lwl()
    sigma_f = flexural_strength_kpa * 1000.0
    e_mod = elastic_modulus_mpa * 1.0e6
    nu = ICE_POISSON_RATIO
    delta_rho = RHO_SEAWATER - RHO_SEA_ICE

    # Crushing at the stem. The denominator grows the answer as friction rises, because a rough
    # hull cannot slide up onto the sheet and has to crush more of it instead.
    crush_denominator = max(0.05, 1.0 - mu * math.sin(phi) / math.cos(psi))
    crushing = (
        0.5
        * sigma_f
        * h * h
        * (math.tan(phi) + mu * math.cos(phi) / math.cos(psi))
        / crush_denominator
    )

    # Bending the sheet into cusps. The divisor is the elastic-foundation length scale: a
    # stiffer sheet breaks off a longer cusp and so resists less per unit flexural strength.
    foundation_length = math.sqrt(e_mod / (12.0 * (1.0 - nu * nu) * RHO_SEAWATER * GRAVITY))
    bending = (
        LINDQVIST_BENDING_COEFF
        * sigma_f
        * b
        * (h ** 1.5)
        / foundation_length
        * ((math.tan(psi) + mu * math.cos(phi)) / (math.cos(psi) * math.sin(alpha)))
        * (1.0 + 1.0 / math.cos(psi))
    )

    # Pushing the broken floes under and sliding them aft. The bracket is buoyancy plus the
    # friction of those floes over the actual wetted geometry of the bow and parallel body.
    buoyant = t * (b + t) / (b + 2.0 * t)
    friction_path = (
        0.7 * lwl
        - t / math.tan(phi)
        - b / (4.0 * math.tan(alpha))
        + t
        * math.cos(phi)
        * math.cos(psi)
        * math.sqrt(1.0 / math.sin(phi) ** 2 + 1.0 / math.tan(alpha) ** 2)
    )
    submergence = delta_rho * GRAVITY * h * b * (buoyant + mu * friction_path)

    return {
        "crushing_n": max(0.0, crushing),
        "bending_n": max(0.0, bending),
        "submergence_n": max(0.0, submergence),
    }


def _velocity_factors(
    vessel: VesselParameters, velocity_knots: float, ice_thickness_m: float
) -> Dict[str, float]:
    """
    Lindqvist's two speed corrections.

    Breaking scales with `v / sqrt(g h)`, a Froude number on ice thickness, because faster
    contact crushes a larger area before the sheet fails. Submergence scales with
    `v / sqrt(g L)`, the ship-length Froude number, because clearing broken ice along the hull
    is a ship-scale process. Using one factor for both, as v0.1 did, gets the speed sensitivity
    of a long ship in thin ice badly wrong.
    """
    v_ms = max(0.0, velocity_knots) * MS_PER_KNOT
    h = max(_MIN_ICE_THICKNESS_M, ice_thickness_m)
    breaking = 1.0 + LINDQVIST_SPEED_COEFF_BREAKING * v_ms / math.sqrt(GRAVITY * h)
    submergence = 1.0 + LINDQVIST_SPEED_COEFF_SUBMERGENCE * v_ms / math.sqrt(GRAVITY * vessel.lwl())
    return {"breaking_factor": breaking, "submergence_factor": submergence}


def ice_resistance_kn(
    vessel: VesselParameters,
    velocity_knots: float,
    ice_thickness_m: float,
    ice_concentration: float = 1.0,
    flexural_strength_kpa: float = 500.0,
    elastic_modulus_mpa: float = 2000.0,
) -> float:
    """Concentration-scaled Lindqvist resistance in kN. The ice component only."""
    if ice_thickness_m <= _MIN_ICE_THICKNESS_M or ice_concentration <= 0.0:
        return 0.0
    static = _lindqvist_static_terms(
        vessel, ice_thickness_m, flexural_strength_kpa, elastic_modulus_mpa
    )
    factors = _velocity_factors(vessel, velocity_knots, ice_thickness_m)
    conc = min(1.0, max(0.0, ice_concentration)) ** ICE_CONCENTRATION_EXPONENT
    total_n = (static["crushing_n"] + static["bending_n"]) * factors["breaking_factor"] + static[
        "submergence_n"
    ] * factors["submergence_factor"]
    return conc * total_n / 1000.0


# --------------------------------------------------------------------------------------
# Propulsion
# --------------------------------------------------------------------------------------
def ice_propulsion_penalty(ice_thickness_m: float, ice_concentration: float) -> float:
    """
    Fractional loss of thrust and quasi-propulsive coefficient from propeller-ice work.

    A propeller working in broken ice mills floes, runs in an inflow partly blocked by ice and
    occasionally ventilates. Full-scale trials put the cost at 15 to 30 percent of the
    open-water QPC in thick, close ice. We ramp linearly to the full penalty at 1 m of ice and
    9/10 concentration and hold it there. That is deliberately simple: the point is to stop the
    model claiming open-water propulsive efficiency inside the pack, not to resolve
    blade-by-blade interaction.
    """
    severity = min(1.0, max(0.0, ice_thickness_m) / 1.0) * min(1.0, max(0.0, ice_concentration) / 0.9)
    return ICE_PROPULSION_EFFICIENCY_LOSS * severity


def propulsive_efficiency(
    vessel: VesselParameters, ice_thickness_m: float, ice_concentration: float
) -> float:
    """Quasi-propulsive coefficient actually available in the given ice."""
    eta = vessel.propulsion_efficiency * (
        1.0 - ice_propulsion_penalty(ice_thickness_m, ice_concentration)
    )
    return max(MIN_PROPULSIVE_EFFICIENCY, eta)


def open_water_speed_knots(
    vessel: VesselParameters,
    available_power_kw: float,
    max_speed_knots: float = MAX_SHIP_SPEED_KNOTS,
) -> float:
    """
    Speed the ship makes in open water on the given power, by bisection.

    Wanted in its own right, and also as the reference speed of the net-thrust curve, which is
    expressed as a fraction of open-water speed.
    """
    power = max(0.0, available_power_kw)
    if power <= 0.0:
        return 0.0
    eta = max(MIN_PROPULSIVE_EFFICIENCY, vessel.propulsion_efficiency)

    def excess(v_knots: float) -> float:
        r_kn = open_water_resistance(vessel, v_knots)["total_kn"]
        return r_kn * v_knots * MS_PER_KNOT / eta - power

    if excess(max_speed_knots) <= 0.0:
        return max_speed_knots
    return _bisect(excess, 0.0, max_speed_knots)


def net_thrust_kn(
    vessel: VesselParameters,
    available_power_kw: float,
    velocity_knots: float,
    open_water_speed: float,
    ice_penalty: float = 0.0,
) -> float:
    """
    Thrust left over for breaking ice, from the Finnish-Swedish Ice Class Rules curve.

    `T = Ke (P_D D)^(2/3) * (1 - v/(3 v_ow) - 2 (v/v_ow)^2 / 3)`. The bracket falls to zero at
    open-water speed, which is the statement that at that speed the whole thrust is already
    spent on open-water resistance. That is why this is balanced against ice resistance alone
    and not against total resistance: open-water drag is already inside the curve.
    """
    if open_water_speed <= 0.0:
        return 0.0
    x = min(1.0, max(0.0, velocity_knots / open_water_speed))
    decay = 1.0 - x / 3.0 - 2.0 * x * x / 3.0
    pull = vessel.bollard_pull_kn(available_power_kw)
    return max(0.0, pull * decay * (1.0 - ice_penalty))


def _bisect(fn: Callable[[float], float], low: float, high: float) -> float:
    """
    Root of a monotonically increasing function on [low, high].

    Bisection rather than Newton, because the resistance curve is only piecewise smooth once
    the ice terms switch on, and because a demo must never fail to converge on stage.
    """
    if fn(low) > 0.0:
        return low
    if fn(high) < 0.0:
        return high
    for _ in range(_BISECTION_ITERATIONS):
        mid = 0.5 * (low + high)
        if fn(mid) > 0.0:
            high = mid
        else:
            low = mid
        if high - low < _SPEED_TOLERANCE_KNOTS:
            break
    return 0.5 * (low + high)


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def calculate_ice_resistance(
    vessel: VesselParameters,
    velocity_knots: float,
    ice_thickness_m: float,
    ice_concentration: float = 1.0,
    flexural_strength_kpa: float = 500.0,
    elastic_modulus_mpa: float = 2000.0,
) -> ResistanceResult:
    """
    Total resistance, power, fuel and CO2 at a demanded speed.

    Total resistance is open water plus concentration-scaled Lindqvist, so the answer stays
    continuous through the ice edge. Required power is `R v / eta_D`, which assumes the
    propeller can deliver the thrust asked of it; `attainable_speed` is the function that
    checks whether it can.

    The signature is unchanged from v0.1 so existing API clients and the route optimiser keep
    working. Every new quantity is an added field on the result.
    """
    velocity_knots = max(0.0, float(velocity_knots))
    ice_thickness_m = max(0.0, float(ice_thickness_m))
    ice_concentration = min(1.0, max(0.0, float(ice_concentration)))

    has_ice = ice_thickness_m > _MIN_ICE_THICKNESS_M and ice_concentration > 0.0

    ow = open_water_resistance(vessel, velocity_knots)
    static = _lindqvist_static_terms(
        vessel,
        ice_thickness_m if has_ice else 0.0,
        flexural_strength_kpa,
        elastic_modulus_mpa,
    )
    factors = _velocity_factors(vessel, velocity_knots, ice_thickness_m)
    conc_factor = ice_concentration ** ICE_CONCENTRATION_EXPONENT if has_ice else 0.0

    crushing_kn = static["crushing_n"] * factors["breaking_factor"] * conc_factor / 1000.0
    bending_kn = static["bending_n"] * factors["breaking_factor"] * conc_factor / 1000.0
    submergence_kn = static["submergence_n"] * factors["submergence_factor"] * conc_factor / 1000.0
    ice_kn = crushing_kn + bending_kn + submergence_kn
    total_kn = ow["total_kn"] + ice_kn

    eta = propulsive_efficiency(vessel, ice_thickness_m, ice_concentration)
    power_kw = total_kn * velocity_knots * MS_PER_KNOT / eta
    fuel_kg_per_hour = power_kw * vessel.sfoc_g_per_kwh / 1000.0
    co2_kg_per_hour = fuel_kg_per_hour * MGO_CO2_FACTOR
    # Fuel per mile is undefined at rest. Dividing by a 0.1 knot floor turns it into a very
    # large number rather than a divide-by-zero, which is the right signal to a cost function.
    fuel_per_nm = fuel_kg_per_hour / max(0.1, velocity_knots)

    # Besetting test: can the installed plant push this ship through this ice fast enough to
    # keep steerage way? The comparison is made at the minimum steerage speed rather than at
    # rest, so that this flag agrees with `attainable_speed`, which reports anything slower as
    # zero. A ship that can inch forward but cannot steer is beset in every practical sense.
    penalty = ice_propulsion_penalty(ice_thickness_m, ice_concentration)
    static_ice_kn = (
        (static["crushing_n"] + static["bending_n"] + static["submergence_n"]) * conc_factor / 1000.0
    )
    steerage = _velocity_factors(vessel, MIN_STEERAGE_SPEED_KNOTS, ice_thickness_m)
    steerage_ice_kn = (
        (static["crushing_n"] + static["bending_n"]) * steerage["breaking_factor"]
        + static["submergence_n"] * steerage["submergence_factor"]
    ) * conc_factor / 1000.0
    bollard_kn = vessel.bollard_pull_kn() * (1.0 - penalty)
    is_beset = bool(has_ice and steerage_ice_kn > bollard_kn)

    return ResistanceResult(
        velocity_knots=velocity_knots,
        ice_thickness_m=ice_thickness_m if has_ice else 0.0,
        ice_concentration=ice_concentration if has_ice else 0.0,
        crushing_resistance_kn=round(crushing_kn, 2),
        bending_resistance_kn=round(bending_kn, 2),
        submergence_resistance_kn=round(submergence_kn, 2),
        open_water_resistance_kn=round(ow["total_kn"], 2),
        ice_resistance_kn=round(ice_kn, 2),
        total_resistance_kn=round(total_kn, 2),
        required_power_kw=round(power_kw, 2),
        fuel_burn_rate_kg_per_hour=round(fuel_kg_per_hour, 2),
        fuel_per_nm_kg=round(fuel_per_nm, 3),
        co2_kg_per_hour=round(co2_kg_per_hour, 2),
        is_beset=is_beset,
        terms={
            "frictional_resistance_kn": round(ow["frictional_kn"], 2),
            "residuary_resistance_kn": round(ow["residuary_kn"], 2),
            "wetted_surface_m2": round(ow["wetted_surface_m2"], 1),
            "reynolds_number": float(f"{ow['reynolds']:.4g}"),
            "froude_number": round(ow["froude"], 4),
            "friction_coefficient": float(f"{ow['cf']:.5g}"),
            "residuary_coefficient": float(f"{ow['cr']:.5g}"),
            "crushing_static_kn": round(static["crushing_n"] / 1000.0, 2),
            "bending_static_kn": round(static["bending_n"] / 1000.0, 2),
            "submergence_static_kn": round(static["submergence_n"] / 1000.0, 2),
            "breaking_speed_factor": round(factors["breaking_factor"], 4),
            "submergence_speed_factor": round(factors["submergence_factor"], 4),
            "concentration_factor": round(conc_factor, 4),
            "flare_angle_deg": round(vessel.lindqvist_flare_angle_deg(), 2),
            "propulsive_efficiency": round(eta, 4),
            "propeller_ice_penalty": round(penalty, 4),
            "bollard_pull_kn": round(bollard_kn, 1),
            "static_ice_resistance_kn": round(static_ice_kn, 2),
            "steerage_ice_resistance_kn": round(steerage_ice_kn, 2),
            "installed_power_kw": round(vessel.installed_power_kw, 1),
            "power_margin_fraction": (
                round(1.0 - power_kw / vessel.installed_power_kw, 4)
                if vessel.installed_power_kw > 0
                else 0.0
            ),
        },
    )


def attainable_speed(
    vessel: VesselParameters,
    available_power_kw: float,
    ice_thickness_m: float,
    ice_concentration: float = 1.0,
    max_speed_knots: float = MAX_SHIP_SPEED_KNOTS,
    flexural_strength_kpa: float = 500.0,
    elastic_modulus_mpa: float = 2000.0,
) -> float:
    """
    Speed the ship can actually make, in knots. Returns 0.0 when it cannot make way at all.

    This is the function the route optimiser must call on every edge, so that speed is an
    output of the physics rather than a planner assumption. That is what turns a fuel saving
    into a measurement instead of a claim.

    Two limits are solved and the lower is returned. The power limit is
    `R_total(v) v / eta_D = P_available`. The thrust limit is `R_ice(v) = T_net(v)` from the
    net-thrust curve, and it is the binding one in heavy ice, because a constant
    quasi-propulsive coefficient silently assumes a propeller that keeps open-water efficiency
    right down to bollard conditions, which no propeller does.

    Besetting is tested first. If the ice resistance at zero speed exceeds the net bollard
    thrust the ship is stuck, and the honest answer is zero rather than a small positive number
    that would let the planner route straight through a ridge field.
    """
    power = max(0.0, float(available_power_kw))
    max_speed_knots = max(0.1, float(max_speed_knots))
    if power <= 0.0:
        return 0.0

    thickness = max(0.0, float(ice_thickness_m))
    concentration = min(1.0, max(0.0, float(ice_concentration)))
    has_ice = thickness > _MIN_ICE_THICKNESS_M and concentration > 0.0

    penalty = ice_propulsion_penalty(thickness, concentration)
    eta = propulsive_efficiency(vessel, thickness, concentration)
    v_ow = open_water_speed_knots(vessel, power, max_speed_knots)

    if has_ice:
        static_kn = ice_resistance_kn(
            vessel, 0.0, thickness, concentration, flexural_strength_kpa, elastic_modulus_mpa
        )
        if static_kn >= net_thrust_kn(vessel, power, 0.0, max(v_ow, 1.0e-6), penalty):
            return 0.0

    def power_excess(v_knots: float) -> float:
        r_kn = open_water_resistance(vessel, v_knots)["total_kn"] + ice_resistance_kn(
            vessel, v_knots, thickness, concentration, flexural_strength_kpa, elastic_modulus_mpa
        )
        return r_kn * v_knots * MS_PER_KNOT / eta - power

    v_power = _bisect(power_excess, 0.0, max_speed_knots)
    if not has_ice:
        return round(min(v_power, max_speed_knots), 3)

    def thrust_deficit(v_knots: float) -> float:
        r_ice = ice_resistance_kn(
            vessel, v_knots, thickness, concentration, flexural_strength_kpa, elastic_modulus_mpa
        )
        return r_ice - net_thrust_kn(vessel, power, v_knots, v_ow, penalty)

    v_thrust = _bisect(thrust_deficit, 0.0, max(v_ow, _SPEED_TOLERANCE_KNOTS))
    speed = max(0.0, min(v_power, v_thrust, max_speed_knots))
    # A ship crawling at a tenth of a knot is beset in every sense that matters: it has no
    # steerage way and the resistance model is well outside the range it was calibrated in.
    # Reporting 0.0 keeps the route optimiser from treating a stuck ship as a slow one.
    if speed < MIN_STEERAGE_SPEED_KNOTS:
        return 0.0
    return round(speed, 3)


def speed_power_curve(
    vessel: VesselParameters,
    thicknesses_m: List[float],
    speeds_knots: List[float],
    ice_concentration: float = 1.0,
) -> Dict[str, object]:
    """
    Resistance, power, fuel and CO2 over a grid of ice thicknesses and speeds.

    Returned as plain lists so it serialises straight to JSON for the analytics chart. Each
    series also carries the attainable speed on installed power, which is the point on the
    curve the ship can actually reach. Without it a reader sees a smooth line and assumes the
    whole of it is available.
    """
    thicknesses = [max(0.0, float(h)) for h in thicknesses_m]
    speeds = [max(0.0, float(v)) for v in speeds_knots]

    series: List[Dict[str, object]] = []
    for h in thicknesses:
        resistance: List[float] = []
        power: List[float] = []
        fuel: List[float] = []
        co2: List[float] = []
        feasible: List[bool] = []
        for v in speeds:
            res = calculate_ice_resistance(vessel, v, h, ice_concentration)
            resistance.append(res.total_resistance_kn)
            power.append(res.required_power_kw)
            fuel.append(res.fuel_burn_rate_kg_per_hour)
            co2.append(res.co2_kg_per_hour)
            feasible.append(res.required_power_kw <= vessel.installed_power_kw)
        series.append(
            {
                "ice_thickness_m": h,
                "resistance_kn": resistance,
                "required_power_kw": power,
                "fuel_kg_per_hour": fuel,
                "co2_kg_per_hour": co2,
                "within_installed_power": feasible,
                "attainable_speed_knots": attainable_speed(
                    vessel, vessel.installed_power_kw, h, ice_concentration
                ),
            }
        )

    return {
        "vessel": {
            "name": vessel.name,
            "display_name": vessel.display_name,
            "ice_class": vessel.ice_class.value,
            "length_m": vessel.length_m,
            "beam_m": vessel.beam_m,
            "draft_m": vessel.draft_m,
            "installed_power_kw": vessel.installed_power_kw,
            "bollard_pull_kn": round(vessel.bollard_pull_kn(), 1),
        },
        "ice_concentration": ice_concentration,
        "speeds_knots": speeds,
        "series": series,
        "model": "Lindqvist (1989) level ice + ITTC-1957 open water",
        "notes": (
            "Ice resistance is Lindqvist level ice scaled by concentration raised to "
            f"{ICE_CONCENTRATION_EXPONENT}. Required power assumes the propeller can deliver "
            "the thrust; attainable_speed additionally applies the net-thrust limit."
        ),
    }


# --------------------------------------------------------------------------------------
# Vessel presets
#
# Principal dimensions are the published figures where a published figure exists. Hull angles,
# block coefficient, propeller diameter and SFOC are NOT published for these ships and are
# engineering estimates typical of the hull type; each is marked below. Anyone using this for a
# real voyage must replace them with the ship's own data.
# --------------------------------------------------------------------------------------
VESSEL_PRESETS: Dict[str, VesselParameters] = {
    # The ship NCPOR actually charters for the Indian Antarctic Expedition. Length, beam and
    # draft are the published figures, and installed power is the published 2 x 6750 kW. Her
    # Russian Register notation is roughly UL / Arc4, but the build spec asks for her to be
    # treated as PC5-equivalent for POLARIS purposes. That is the optimistic end of the range
    # and is stated here rather than buried.
    "vasiliy_golovnin": VesselParameters(
        name="MV Vasiliy Golovnin",
        display_name="MV Vasiliy Golovnin (NCPOR charter)",
        ice_class=IceClass.PC5,
        length_m=167.0,
        waterline_length_m=160.0,       # approximate
        beam_m=22.6,
        draft_m=8.5,
        block_coefficient=0.65,         # approximate, ice-strengthened cargo hull
        stem_angle_deg=25.0,            # approximate
        waterline_angle_deg=30.0,       # approximate
        flare_angle_deg=43.0,           # derived from the two angles above
        hull_friction_coeff=0.15,       # bare steel against saline polar ice
        propulsion_efficiency=0.65,
        sfoc_g_per_kwh=195.0,
        installed_power_kw=13500.0,
        propeller_diameter_m=5.2,       # approximate
        n_propellers=2,
        ducted_propeller=False,
    ),
    # Generic Arc7 resupply ship, dimensioned on the Norilskiy Nickel class of Arc7 cargo
    # vessels: a true icebreaking bow, azimuthing propulsion in a nozzle, and a far heavier
    # ice-class hull than the Golovnin. Not a specific ship, hence "generic".
    "arc7_resupply": VesselParameters(
        name="Generic Arc7 Resupply Vessel",
        display_name="Arc7 resupply vessel (generic)",
        ice_class=IceClass.ARC7,
        length_m=169.0,
        waterline_length_m=161.0,       # approximate
        beam_m=26.5,
        draft_m=10.0,
        block_coefficient=0.70,         # approximate
        stem_angle_deg=22.0,            # approximate, icebreaking bow
        waterline_angle_deg=26.0,       # approximate
        flare_angle_deg=42.7,           # derived
        hull_friction_coeff=0.10,       # ice-friendly coating, Inerta type
        propulsion_efficiency=0.62,
        sfoc_g_per_kwh=190.0,
        installed_power_kw=13000.0,
        propeller_diameter_m=6.0,       # approximate
        n_propellers=1,
        ducted_propeller=True,
    ),
    # ORV Sagar Nidhi: India's own ice-strengthened research vessel, operated by the National
    # Institute of Ocean Technology under MoES and built by Fincantieri in 2008. In 2010 she
    # became the first Indian-owned vessel to reach Antarctica, which is why she belongs in this
    # list: she is the reference point for what an Indian hull can and cannot do down there.
    #
    # Her published capability is navigation in roughly 40 cm of ice. That is thin first-year
    # ice, so PC7 is the right POLARIS row - and the comparison this preset exists to make is a
    # blunt one. Run the same passage with her and with the chartered Golovnin and the planner
    # will refuse ice she cannot enter. That is the argument for a dedicated polar vessel,
    # expressed as physics rather than as a slide.
    "sagar_nidhi": VesselParameters(
        name="ORV Sagar Nidhi",
        display_name="ORV Sagar Nidhi (NIOT / MoES)",
        ice_class=IceClass.PC7,
        length_m=103.6,
        waterline_length_m=95.0,        # approximate
        beam_m=18.0,
        draft_m=5.6,
        block_coefficient=0.56,         # approximate, fine research hull
        stem_angle_deg=28.0,            # approximate; ice-strengthened, not an icebreaking bow
        waterline_angle_deg=30.0,       # approximate
        flare_angle_deg=46.7,           # derived from the two angles above
        hull_friction_coeff=0.15,
        propulsion_efficiency=0.60,
        sfoc_g_per_kwh=200.0,
        installed_power_kw=5600.0,      # diesel-electric, approximate total propulsion power
        propeller_diameter_m=3.6,       # approximate
        n_propellers=2,
        ducted_propeller=True,
    ),
    # The dedicated Polar Research Vessel that NCPOR has long planned and India does not yet
    # operate. Every figure is NOTIONAL, sized on comparable new-build polar research ships such
    # as RRS Sir David Attenborough and RV Kronprins Haakon. It is here so the value of the
    # capability can be quantified before the ship exists: plan the same passage with her and
    # with the current fleet, and the difference is the business case.
    "polar_research_vessel": VesselParameters(
        name="Indian Polar Research Vessel (notional)",
        display_name="Indian Polar Research Vessel (planned, notional design)",
        ice_class=IceClass.PC4,
        length_m=129.0,
        waterline_length_m=120.0,       # notional
        beam_m=24.0,
        draft_m=7.5,
        block_coefficient=0.60,         # notional
        stem_angle_deg=21.0,            # notional, true icebreaking bow
        waterline_angle_deg=25.0,       # notional
        flare_angle_deg=42.4,           # derived
        hull_friction_coeff=0.10,       # ice-friendly coating
        propulsion_efficiency=0.62,
        sfoc_g_per_kwh=190.0,
        installed_power_kw=12000.0,     # notional
        propeller_diameter_m=4.8,       # notional
        n_propellers=2,
        ducted_propeller=True,
    ),
}


def get_vessel_preset(key: str) -> VesselParameters:
    """Look up a preset by key, defaulting to the ship NCPOR actually charters."""
    return VESSEL_PRESETS.get(key, VESSEL_PRESETS["vasiliy_golovnin"]).model_copy(deep=True)
