"""
Route optimiser tests.

The v0.1 version of this file asserted `fuel_saved_percentage > 10.0`. That assertion could only
ever pass, because the baseline was computed as `optimised * 1.22` — the test was checking a
constant, not the optimiser. It is replaced here with assertions about the properties that
actually have to hold: the route is navigable, it satisfies POLARIS, and the saving is derived by
differencing two real model runs rather than by applying a factor.
"""
from __future__ import annotations

import pytest

from src.core.polaris_risk import IceClass
from src.core.route_optimizer import PolarRouteOptimizer, RouteWeights
from src.data.landmask import is_land

# Planning is expensive, so the shared plan is computed once for the whole module.
START = (-58.0, 70.0)
DEST = (-69.0, 76.0)


@pytest.fixture(scope="module")
def summary():
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    return optimizer.optimize_route(
        start_lat=START[0], start_lon=START[1], dest_lat=DEST[0], dest_lon=DEST[1]
    )


def test_route_is_produced(summary):
    assert summary.total_distance_nm > 0.0
    assert summary.waypoints_count >= 2
    assert len(summary.waypoints) == summary.waypoints_count


def test_route_satisfies_polaris(summary):
    """The hard constraint. RIO below -10 means the operation is prohibited outright."""
    assert summary.minimum_rio >= -10
    for waypoint in summary.waypoints:
        assert waypoint.rio_score >= -10
        assert waypoint.is_safe


def test_route_never_crosses_land(summary):
    """A waypoint on the continent is the most basic possible failure, so it is pinned."""
    for waypoint in summary.waypoints:
        assert not is_land(waypoint.latitude, waypoint.longitude), (
            f"waypoint on land at ({waypoint.latitude}, {waypoint.longitude})"
        )


def test_route_endpoints_are_respected(summary):
    first, last = summary.waypoints[0], summary.waypoints[-1]
    assert first.latitude == pytest.approx(START[0], abs=0.6)
    assert first.longitude == pytest.approx(START[1], abs=1.2)
    assert last.latitude == pytest.approx(DEST[0], abs=0.6)
    assert last.longitude == pytest.approx(DEST[1], abs=1.2)


def test_both_routes_are_evaluated(summary):
    """The saving must come from two real evaluations, not from a multiplier."""
    assert summary.optimized is not None
    assert summary.baseline is not None
    assert summary.baseline.waypoints, "baseline route was not evaluated"
    assert summary.optimized.total_fuel_burn_tonnes > 0.0
    assert summary.baseline.total_fuel_burn_tonnes > 0.0
    assert "multiplier" in summary.savings_method


def test_saving_is_consistent_with_the_two_evaluations(summary):
    """
    Recompute the headline figure from the two route totals and require it to match.

    This is the test that would have caught the v0.1 defect: a hard-coded factor cannot satisfy
    it unless the factor happens to equal the true difference, which it never would.
    """
    baseline = summary.baseline.total_fuel_burn_tonnes
    optimised = summary.optimized.total_fuel_burn_tonnes
    expected = ((baseline - optimised) / baseline) * 100.0
    assert summary.fuel_saved_percentage == pytest.approx(expected, abs=0.05)
    assert summary.baseline_direct_fuel_tonnes == pytest.approx(baseline, abs=0.01)


def test_optimised_route_is_not_worse_on_risk(summary):
    """
    The optimiser may spend fuel or distance to buy safety, but it must not end up riskier than
    the ice-blind route. That would mean the risk term is wired up backwards.
    """
    assert summary.optimized.minimum_rio >= summary.baseline.minimum_rio


def test_derived_totals_are_coherent(summary):
    fuel_delta = summary.baseline.total_fuel_burn_tonnes - summary.optimized.total_fuel_burn_tonnes
    assert summary.co2_saved_tonnes == pytest.approx(fuel_delta * 3.206, abs=0.1)
    assert summary.time_saved_hours == pytest.approx(
        summary.baseline.total_transit_hours - summary.optimized.total_transit_hours, abs=0.2
    )


def test_waypoints_are_monotonic_in_cumulative_quantities(summary):
    for previous, current in zip(summary.waypoints, summary.waypoints[1:]):
        assert current.cumulative_hours >= previous.cumulative_hours
        assert current.cumulative_fuel_tonnes >= previous.cumulative_fuel_tonnes
        assert current.distance_from_start_nm >= previous.distance_from_start_nm


def test_search_diagnostics_are_reported(summary):
    diagnostics = summary.search
    assert diagnostics is not None
    assert diagnostics.nodes_expanded > 0
    assert diagnostics.lattice_cells > 0
    assert diagnostics.search_ms >= 0.0


def test_risk_weighting_changes_the_route():
    """
    A heavily risk-averse plan should not be identical to a fuel-only plan.

    If the weights made no difference, the multi-objective cost would be decorative.
    """
    fuel_only = PolarRouteOptimizer(
        ice_class=IceClass.PC5, weights=RouteWeights(fuel=1.0, time=0.35, risk=0.0)
    ).optimize_route(START[0], START[1], DEST[0], DEST[1])
    risk_averse = PolarRouteOptimizer(
        ice_class=IceClass.PC5, weights=RouteWeights(fuel=1.0, time=0.35, risk=6.0)
    ).optimize_route(START[0], START[1], DEST[0], DEST[1])

    differs = (
        fuel_only.total_distance_nm != risk_averse.total_distance_nm
        or fuel_only.minimum_rio != risk_averse.minimum_rio
        or fuel_only.waypoints_count != risk_averse.waypoints_count
    )
    assert differs, "objective weights had no effect on the plan"
