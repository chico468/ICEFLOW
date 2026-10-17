"""
Extended tests for the upgraded Lindqvist resistance and powering model.

These cover the properties the route optimiser depends on being true: resistance rises with
ice, total resistance is continuous through the ice edge, attainable speed is bounded and
falls as ice thickens, and a ship that cannot move is reported as beset rather than as slow.
The last test pins the formulation itself against published Lindqvist results, so an
accidental edit to a coefficient fails loudly instead of silently changing every fuel figure.
"""
from __future__ import annotations

import json
import math

import pytest

from src.core.constants import MGO_CO2_FACTOR, MS_PER_KNOT
from src.core.lindqvist_model import (
    VESSEL_PRESETS,
    VesselParameters,
    attainable_speed,
    calculate_ice_resistance,
    get_vessel_preset,
    ice_resistance_kn,
    open_water_resistance,
    open_water_speed_knots,
    speed_power_curve,
)
from src.core.polaris_risk import IceClass

VESSEL = VESSEL_PRESETS["vasiliy_golovnin"]


# --------------------------------------------------------------------------------------
# Monotonicity
# --------------------------------------------------------------------------------------
def test_resistance_increases_monotonically_with_thickness():
    """Thicker ice must never be cheaper. Any inversion here would let A* route into a ridge."""
    previous = -1.0
    for thickness in (0.0, 0.1, 0.3, 0.6, 1.0, 1.5, 2.0, 2.5, 3.0):
        result = calculate_ice_resistance(VESSEL, 6.0, thickness, 0.8)
        assert result.total_resistance_kn > previous
        previous = result.total_resistance_kn


def test_resistance_increases_monotonically_with_concentration():
    """More ice in the same water must cost more."""
    previous = -1.0
    for concentration in (0.0, 0.1, 0.25, 0.5, 0.7, 0.9, 1.0):
        result = calculate_ice_resistance(VESSEL, 6.0, 1.0, concentration)
        assert result.total_resistance_kn > previous
        previous = result.total_resistance_kn


def test_resistance_increases_monotonically_with_speed():
    """Both the open-water and the Lindqvist velocity terms grow with speed."""
    previous = -1.0
    for speed in (0.0, 2.0, 4.0, 8.0, 12.0):
        result = calculate_ice_resistance(VESSEL, speed, 0.8, 0.7)
        assert result.total_resistance_kn > previous
        previous = result.total_resistance_kn


def test_each_lindqvist_component_grows_with_thickness():
    """Crushing, bending and submergence must each be monotone, not just their sum."""
    thin = calculate_ice_resistance(VESSEL, 5.0, 0.5, 1.0)
    thick = calculate_ice_resistance(VESSEL, 5.0, 1.5, 1.0)
    assert thick.crushing_resistance_kn > thin.crushing_resistance_kn
    assert thick.bending_resistance_kn > thin.bending_resistance_kn
    assert thick.submergence_resistance_kn > thin.submergence_resistance_kn


# --------------------------------------------------------------------------------------
# Open water and continuity through the ice edge
# --------------------------------------------------------------------------------------
def test_open_water_resistance_is_positive_and_grows_with_speed():
    previous = -1.0
    for speed in (1.0, 4.0, 8.0, 12.0, 16.0):
        total = open_water_resistance(VESSEL, speed)["total_kn"]
        assert total > previous
        previous = total
    assert open_water_resistance(VESSEL, 0.0)["total_kn"] == 0.0


def test_total_resistance_is_continuous_as_thickness_goes_to_zero():
    """
    The whole point of adding an open-water branch: no step at the ice edge.

    As h -> 0 the ice component must vanish and the total must converge on the open-water
    value from above, with no jump. The v0.1 model failed this badly, snapping to a 10 kN floor.
    """
    speed = 8.0
    open_water = calculate_ice_resistance(VESSEL, speed, 0.0, 0.0).total_resistance_kn
    assert open_water > 0.0

    previous_gap = float("inf")
    for thickness in (0.2, 0.1, 0.05, 0.02, 0.01, 0.001):
        result = calculate_ice_resistance(VESSEL, speed, thickness, 0.8)
        gap = result.total_resistance_kn - open_water
        assert gap >= 0.0
        assert gap < previous_gap  # strictly shrinking as the ice thins
        previous_gap = gap

    assert previous_gap < 0.02 * open_water  # within 2 percent by 1 mm of ice


def test_ice_component_is_zero_in_open_water():
    result = calculate_ice_resistance(VESSEL, 12.0, 0.0, 0.0)
    assert result.crushing_resistance_kn == 0.0
    assert result.bending_resistance_kn == 0.0
    assert result.submergence_resistance_kn == 0.0
    assert result.ice_resistance_kn == 0.0
    assert result.open_water_resistance_kn == pytest.approx(result.total_resistance_kn)
    assert result.is_beset is False


def test_zero_concentration_means_no_ice_resistance():
    """Thick ice at zero concentration is open water, not thick ice."""
    assert ice_resistance_kn(VESSEL, 8.0, 2.0, 0.0) == 0.0


# --------------------------------------------------------------------------------------
# Attainable speed
# --------------------------------------------------------------------------------------
def test_attainable_speed_is_bounded():
    for thickness in (0.0, 0.5, 1.0, 2.0):
        for concentration in (0.0, 0.5, 1.0):
            speed = attainable_speed(VESSEL, VESSEL.installed_power_kw, thickness, concentration)
            assert 0.0 <= speed <= 18.0


def test_attainable_speed_respects_the_max_speed_cap():
    capped = attainable_speed(VESSEL, VESSEL.installed_power_kw, 0.0, 0.0, max_speed_knots=9.0)
    assert capped == pytest.approx(9.0, abs=0.01)


def test_attainable_speed_in_open_water_matches_the_open_water_solution():
    power = VESSEL.installed_power_kw
    assert attainable_speed(VESSEL, power, 0.0, 0.0) == pytest.approx(
        open_water_speed_knots(VESSEL, power), abs=0.05
    )


def test_attainable_speed_falls_as_ice_thickens():
    power = VESSEL.installed_power_kw
    speeds = [attainable_speed(VESSEL, power, h, 0.8) for h in (0.0, 0.3, 0.6, 1.0, 1.5, 2.0)]
    assert all(later <= earlier for earlier, later in zip(speeds, speeds[1:]))
    assert speeds[0] > speeds[-1]


def test_attainable_speed_falls_as_concentration_rises():
    power = VESSEL.installed_power_kw
    speeds = [attainable_speed(VESSEL, power, 1.0, c) for c in (0.0, 0.3, 0.6, 0.9, 1.0)]
    assert all(later <= earlier for earlier, later in zip(speeds, speeds[1:]))


def test_attainable_speed_rises_with_available_power():
    low = attainable_speed(VESSEL, 4000.0, 0.8, 0.7)
    high = attainable_speed(VESSEL, 13500.0, 0.8, 0.7)
    assert high > low


def test_attainable_speed_is_zero_with_no_power():
    assert attainable_speed(VESSEL, 0.0, 0.5, 0.5) == 0.0


def test_besetting_returns_zero_speed_and_is_flagged():
    """
    Heavy multi-year ice at full concentration stops this ship, and the model must say so.

    A silent small positive speed here is the failure mode that matters: the planner would
    happily route a chartered resupply ship into ice it cannot leave.
    """
    thickness, concentration = 4.0, 1.0
    assert attainable_speed(VESSEL, VESSEL.installed_power_kw, thickness, concentration) == 0.0
    result = calculate_ice_resistance(VESSEL, 3.0, thickness, concentration)
    assert result.is_beset is True
    assert result.terms["static_ice_resistance_kn"] > result.terms["bollard_pull_kn"]


def test_is_beset_agrees_with_a_zero_attainable_speed():
    """
    The flag and the speed must never disagree.

    A result that says "not beset" next to a speed of zero, or the reverse, would put two
    contradictory statements on the same bridge display. Both are tested at the minimum
    steerage speed for exactly this reason.
    """
    power = VESSEL.installed_power_kw
    for thickness in (0.4, 0.8, 1.0, 1.4, 2.0, 2.5, 3.0):
        for concentration in (0.4, 0.7, 1.0):
            speed = attainable_speed(VESSEL, power, thickness, concentration)
            result = calculate_ice_resistance(VESSEL, max(speed, 0.01), thickness, concentration)
            assert (speed == 0.0) is result.is_beset


def test_the_ship_is_not_beset_in_ice_it_can_handle():
    result = calculate_ice_resistance(VESSEL, 5.0, 0.6, 0.6)
    assert result.is_beset is False
    assert attainable_speed(VESSEL, VESSEL.installed_power_kw, 0.6, 0.6) > 1.0


# --------------------------------------------------------------------------------------
# Powering, fuel and emissions
# --------------------------------------------------------------------------------------
def test_power_and_fuel_are_consistent_with_resistance():
    result = calculate_ice_resistance(VESSEL, 6.0, 1.0, 0.6)
    eta = result.terms["propulsive_efficiency"]
    expected_kw = result.total_resistance_kn * 6.0 * MS_PER_KNOT / eta
    assert result.required_power_kw == pytest.approx(expected_kw, rel=1e-3)
    assert result.fuel_burn_rate_kg_per_hour == pytest.approx(
        result.required_power_kw * VESSEL.sfoc_g_per_kwh / 1000.0, rel=1e-3
    )


def test_co2_uses_the_mgo_emission_factor():
    result = calculate_ice_resistance(VESSEL, 8.0, 0.8, 0.7)
    assert result.co2_kg_per_hour == pytest.approx(
        result.fuel_burn_rate_kg_per_hour * MGO_CO2_FACTOR, rel=1e-3
    )


def test_fuel_per_nm_is_hourly_burn_over_speed():
    result = calculate_ice_resistance(VESSEL, 10.0, 0.5, 0.5)
    assert result.fuel_per_nm_kg == pytest.approx(
        result.fuel_burn_rate_kg_per_hour / 10.0, rel=1e-3
    )


def test_propulsive_efficiency_degrades_in_ice():
    """Propeller-ice interaction must cost efficiency, or power in ice is under-reported."""
    clear = calculate_ice_resistance(VESSEL, 8.0, 0.0, 0.0).terms["propulsive_efficiency"]
    heavy = calculate_ice_resistance(VESSEL, 8.0, 1.5, 1.0).terms["propulsive_efficiency"]
    assert heavy < clear
    assert heavy >= 0.30


def test_terms_breakdown_is_populated():
    """P6: every displayed number must be traceable to an intermediate."""
    result = calculate_ice_resistance(VESSEL, 7.0, 1.0, 0.7)
    for key in (
        "frictional_resistance_kn",
        "residuary_resistance_kn",
        "wetted_surface_m2",
        "froude_number",
        "crushing_static_kn",
        "bending_static_kn",
        "submergence_static_kn",
        "breaking_speed_factor",
        "submergence_speed_factor",
        "concentration_factor",
        "flare_angle_deg",
        "propulsive_efficiency",
        "bollard_pull_kn",
    ):
        assert key in result.terms
    components = (
        result.crushing_resistance_kn
        + result.bending_resistance_kn
        + result.submergence_resistance_kn
    )
    assert components == pytest.approx(result.ice_resistance_kn, abs=0.05)


# --------------------------------------------------------------------------------------
# Sanity of the absolute numbers
# --------------------------------------------------------------------------------------
def test_a_pc5_hull_in_one_metre_ice_needs_a_plausible_power():
    """
    Order-of-magnitude guard on the headline case.

    A 167 m ice-class ship pushing through 1 m of ice at 6/10 concentration should be spending
    single-digit megawatts and making a few knots. Numbers far outside that mean a term has
    been mistyped, which is exactly the failure the v0.1 model had.
    """
    speed = attainable_speed(VESSEL, VESSEL.installed_power_kw, 1.0, 0.6)
    assert 2.0 < speed < 10.0
    result = calculate_ice_resistance(VESSEL, speed, 1.0, 0.6)
    assert 2.0e3 < result.required_power_kw < 12.0e3
    assert result.required_power_kw <= VESSEL.installed_power_kw


def test_open_water_speed_and_power_are_plausible_for_the_class():
    """About 16 to 17 knots at full power, and roughly 7 MW at 15 knots."""
    assert 14.0 < open_water_speed_knots(VESSEL, VESSEL.installed_power_kw) < 18.0
    at_fifteen = calculate_ice_resistance(VESSEL, 15.0, 0.0, 0.0).required_power_kw
    assert 4.0e3 < at_fifteen < 11.0e3


def test_matches_published_lindqvist_results():
    """
    Pin the formulation against Fan et al. (2019) Table 3, the Lindqvist column.

    Their vessel is 118 m waterline, 21.5 m beam, 7.5 m draft, stem angle 21 degrees, waterline
    entrance angle 33 degrees, friction 0.1, ice 500.8 kPa flexural and about 9 GPa. We use the
    project ice density of 920 kg/m3 where they used 900, which accounts for most of the
    residual difference. Anything worse than 15 percent means a coefficient has drifted.
    """
    vessel = VesselParameters(
        name="Fan 2019 reference polar vessel",
        length_m=121.0,
        waterline_length_m=118.0,
        beam_m=21.5,
        draft_m=7.5,
        stem_angle_deg=21.0,
        waterline_angle_deg=33.0,
        hull_friction_coeff=0.10,
    )
    published = [
        (1.92, 1.59, 1599.1),
        (1.45, 1.62, 1429.0),
        (0.72, 1.65, 1223.9),
        (3.77, 0.95, 1250.6),
        (3.21, 0.95, 1145.7),
        (2.51, 0.95, 1014.5),
    ]
    for v_ms, thickness, reference_kn in published:
        computed = ice_resistance_kn(
            vessel,
            v_ms / MS_PER_KNOT,
            thickness,
            1.0,
            flexural_strength_kpa=500.8,
            elastic_modulus_mpa=9000.0,
        )
        assert computed == pytest.approx(reference_kn, rel=0.15)


def test_flare_angle_is_derived_from_stem_and_waterline_angles():
    vessel = VesselParameters(stem_angle_deg=25.0, waterline_angle_deg=30.0)
    expected = math.degrees(math.atan(math.tan(math.radians(25.0)) / math.sin(math.radians(30.0))))
    assert vessel.lindqvist_flare_angle_deg() == pytest.approx(expected)


# --------------------------------------------------------------------------------------
# Presets and the charting helper
# --------------------------------------------------------------------------------------
def test_presets_are_complete_and_distinct():
    """
    The fleet is the Indian Antarctic programme's fleet.

    An earlier version carried an invented "RV Himadri-class" preset, which was doubly wrong:
    India does not operate that ship, and Himadri is the Indian *Arctic* station, not a vessel.
    It was replaced by ORV Sagar Nidhi, which is real, and by an explicitly notional Polar
    Research Vessel standing in for the ship India has planned but not built.
    """
    assert set(VESSEL_PRESETS) == {
        "vasiliy_golovnin",
        "arc7_resupply",
        "sagar_nidhi",
        "polar_research_vessel",
    }
    for preset in VESSEL_PRESETS.values():
        assert isinstance(preset.ice_class, IceClass)
        assert preset.installed_power_kw > 0.0
        assert preset.display_name and preset.display_name != preset.name.lower()
        # The stored flare angle must agree with the one Lindqvist derives, or the interface
        # would display a hull geometry the physics does not use.
        assert preset.flare_angle_deg == pytest.approx(preset.lindqvist_flare_angle_deg(), abs=0.6)
        assert preset.bollard_pull_kn() > 200.0


def test_notional_hulls_are_labelled_as_notional():
    """
    Anything that is not a real ship must say so in its display name.

    This is the guard against the exact mistake that was made once already: presenting an
    invented vessel alongside real ones with nothing to distinguish them.
    """
    for key in ("polar_research_vessel",):
        assert "notional" in VESSEL_PRESETS[key].display_name.lower()
    for key in ("vasiliy_golovnin", "sagar_nidhi"):
        assert "notional" not in VESSEL_PRESETS[key].display_name.lower()


def test_indian_fleet_capability_gap_is_reproduced():
    """
    The comparison that makes the case for a dedicated Indian polar vessel.

    In heavy ice the ice-strengthened Sagar Nidhi cannot make way, the chartered PC5 manages a
    crawl, and a PC4 polar research vessel keeps going. If this ordering ever breaks, the
    argument the README and the slide deck make from it is no longer supported by the model.
    """
    heavy_ice_m, concentration = 1.5, 0.6

    def speed(key: str) -> float:
        v = VESSEL_PRESETS[key]
        return attainable_speed(v, v.installed_power_kw, heavy_ice_m, concentration)

    sagar = speed("sagar_nidhi")
    golovnin = speed("vasiliy_golovnin")
    prv = speed("polar_research_vessel")

    assert sagar == 0.0, "Sagar Nidhi should be beset in 1.5 m ice; she is ice-strengthened, not an icebreaker"
    assert golovnin > sagar
    assert prv > golovnin, "a PC4 polar research vessel must outperform the PC5 charter in heavy ice"


def test_preset_lookup_copies_and_falls_back():
    original = VESSEL_PRESETS["arc7_resupply"]
    copy = get_vessel_preset("arc7_resupply")
    copy.beam_m = 1.0
    assert original.beam_m != 1.0
    assert get_vessel_preset("no_such_ship").name == "MV Vasiliy Golovnin"


def test_arc7_outperforms_the_pc5_charter_in_the_same_ice():
    """A heavier ice class with more bollard pull must do better, or the model is not reading
    the hull at all."""
    arc7 = VESSEL_PRESETS["arc7_resupply"]
    power = min(arc7.installed_power_kw, VESSEL.installed_power_kw)
    assert attainable_speed(arc7, power, 1.2, 0.9) > attainable_speed(VESSEL, power, 1.2, 0.9)


def test_speed_power_curve_is_serialisable_and_shaped_for_charting():
    curve = speed_power_curve(VESSEL, [0.0, 0.5, 1.0], [2.0, 4.0, 6.0, 8.0])
    assert curve["speeds_knots"] == [2.0, 4.0, 6.0, 8.0]
    assert len(curve["series"]) == 3
    for series in curve["series"]:
        assert len(series["required_power_kw"]) == 4
        assert len(series["resistance_kn"]) == 4
        assert len(series["co2_kg_per_hour"]) == 4
        assert series["required_power_kw"] == sorted(series["required_power_kw"])
        assert 0.0 <= series["attainable_speed_knots"] <= 18.0
    json.dumps(curve)  # must round-trip to the API without a custom encoder
