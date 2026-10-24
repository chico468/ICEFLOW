from __future__ import annotations

from types import SimpleNamespace
from typing import Tuple

from src.core.polaris_risk import IceClass
from src.core.route_optimizer import (
    FieldCache,
    PolarRouteOptimizer,
    RouteWeights,
    SearchDiagnostics,
)
from src.api.routers import navigation, voyages
from src.api.routers.navigation import RouteRequest
from src.api.routers.voyages import CreateVoyageRequest


class _SharedCache:
    lat_min = -80.0
    lat_step = 1.0
    lon_min = -180.0
    lon_step = 1.0
    n_lat = 100
    n_lon = 360

    @staticmethod
    def at(_i: int, _j: int, _hours: float):
        return {
            "rio": 10,
            "comp": 0.2,
            "thick": 0.4,
            "speed": 8.0,
            "fuel_rate": 1000.0,
            "conc": 0.2,
            "coast_nm": 100.0,
            "wind": 5.0,
            "wave": 1.0,
            "cap": 12.0,
            "attainable": 12.0,
        }


def test_alternatives_share_cache_and_evaluate_distinct_weighted_routes(monkeypatch):
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5, weights=RouteWeights(fuel=1.2, time=0.4, risk=1.5))
    cache = _SharedCache()
    exclusions = [object()]
    searches = []
    monkeypatch.setattr(optimizer, "_build_cache", lambda *_args: (cache, 72.0))
    monkeypatch.setattr(optimizer, "_node_of", lambda *_args: (0, 0))
    monkeypatch.setattr(optimizer, "_build_exclusions", lambda *_args: exclusions)

    def search(_cache, _start, _goal, _pos, ice_aware, exclusions, t0_hours, weights=None):
        searches.append((exclusions, weights))
        code = 0
        if ice_aware and weights:
            if weights == RouteWeights(fuel=1.2, time=0.4, risk=1.5):
                code = 1
            elif weights == RouteWeights(fuel=1.0, time=0.2, risk=6.0):
                code = 2
            elif weights == RouteWeights(fuel=4.0, time=0.05, risk=1.5):
                code = 3
            else:
                code = 4
        diagnostics = SearchDiagnostics(
            nodes_expanded=10,
            nodes_rejected_land=1,
            nodes_rejected_rio=2,
            nodes_rejected_iceberg=3,
            nodes_rejected_clearance=4,
            search_ms=5,
            lattice_cells=100,
            forecast_slices=6,
            goal_reached=True,
        )
        return [(code, 0), (code, 1)], diagnostics

    monkeypatch.setattr(optimizer, "_search", search)
    def points(_cache, path, start, dest, include_destination=True):
        code = path[0][0]
        if code == 0:
            return [start, dest]
        middle = ((start[0] + dest[0]) / 2, start[1] + code * 0.1)
        return [start, middle, dest] if include_destination else [start, middle]
    monkeypatch.setattr(optimizer, "_path_to_points", points)

    result = optimizer.optimize_alternatives(
        -58.0, 70.0, -69.0, 76.0, grid_resolution_deg=0.5,
        departure_time_hours=24.0, avoid_icebergs=True,
    )

    assert [candidate.id for candidate in result.candidates] == [
        "balanced", "safety-first", "fuel-efficient", "fastest",
    ]
    assert result.candidates[0].weights == RouteWeights(fuel=1.2, time=0.4, risk=1.5)
    assert all(candidate.is_feasible and candidate.goal_reached for candidate in result.candidates)
    assert len({tuple((w.latitude, w.longitude) for w in c.evaluation.waypoints) for c in result.candidates}) == 4
    assert result.balanced_summary is not None
    assert result.balanced_summary.optimized is not None
    assert result.balanced_summary.optimized.total_fuel_burn_tonnes == result.candidates[0].evaluation.total_fuel_burn_tonnes
    assert result.distinct_alternatives_found == 4
    assert set(result.environment_provenance) == {
        "sea_ice_field", "atmosphere_ocean", "iceberg_catalogue", "coastline",
    }
    assert result.is_synthetic_environment
    assert len(searches) == 5  # one baseline plus four objective profiles
    assert all(entry[0] is exclusions for entry in searches[1:])


def test_duplicate_route_geometry_is_reported_as_omitted(monkeypatch):
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    cache = _SharedCache()
    monkeypatch.setattr(optimizer, "_build_cache", lambda *_args: (cache, 72.0))
    monkeypatch.setattr(optimizer, "_node_of", lambda *_args: (0, 0))
    monkeypatch.setattr(optimizer, "_build_exclusions", lambda *_args: [])
    diagnostics = SearchDiagnostics(
        nodes_expanded=1,
        nodes_rejected_land=0,
        nodes_rejected_rio=0,
        nodes_rejected_iceberg=0,
        nodes_rejected_clearance=0,
        search_ms=1,
        lattice_cells=1,
        forecast_slices=1,
        goal_reached=True,
    )
    monkeypatch.setattr(optimizer, "_search", lambda *_args, **_kwargs: ([(0, 0)], diagnostics))
    monkeypatch.setattr(
        optimizer, "_path_to_points",
        lambda _cache, _path, start, dest, include_destination=True: [start, dest],
    )

    result = optimizer.optimize_alternatives(-58.0, 70.0, -69.0, 76.0, avoid_icebergs=False)

    assert [candidate.id for candidate in result.candidates] == ["balanced"]
    assert {item["profile_id"] for item in result.omitted_profiles} == {
        "safety-first", "fuel-efficient", "fastest",
    }
    assert result.distinct_alternatives_found == 1


def test_partial_search_is_explicitly_infeasible_and_not_counted_as_selectable(monkeypatch):
    optimizer = PolarRouteOptimizer(ice_class=IceClass.PC5)
    cache = _SharedCache()
    monkeypatch.setattr(optimizer, "_build_cache", lambda *_args: (cache, 72.0))
    monkeypatch.setattr(optimizer, "_node_of", lambda *_args: (0, 0))
    monkeypatch.setattr(optimizer, "_build_exclusions", lambda *_args: [])
    diagnostics = SearchDiagnostics(
        nodes_expanded=1,
        nodes_rejected_land=0,
        nodes_rejected_rio=0,
        nodes_rejected_iceberg=0,
        nodes_rejected_clearance=0,
        search_ms=1,
        lattice_cells=1,
        forecast_slices=1,
        goal_reached=False,
    )
    call_count = 0

    def search(*_args, **_kwargs):
        nonlocal call_count
        call_count += 1
        diag = diagnostics if call_count > 1 else diagnostics.model_copy(update={"goal_reached": True})
        return [(0, 0)], diag

    monkeypatch.setattr(optimizer, "_search", search)
    monkeypatch.setattr(
        optimizer, "_path_to_points",
        lambda _cache, _path, start, dest, include_destination=True: [start, dest] if include_destination else [start],
    )

    result = optimizer.optimize_alternatives(-58.0, 70.0, -69.0, 76.0, avoid_icebergs=False)

    balanced = result.candidates[0]
    assert not balanced.goal_reached
    assert not balanced.is_feasible
    assert any("partial" in warning.lower() for warning in balanced.warnings)
    assert result.distinct_alternatives_found == 0


def test_partial_path_does_not_append_unreached_destination():
    class PathCache(FieldCache):
        def __init__(self):
            pass

        def position(self, _i: int, _j: int) -> Tuple[float, float]:
            return (-60.0, 70.0)

    cache = PathCache()
    start = (-61.0, 69.0)
    destination = (-65.0, 75.0)

    partial = PolarRouteOptimizer._path_to_points(
        cache, [(0, 0), (1, 1)], start, destination, include_destination=False,
    )
    complete = PolarRouteOptimizer._path_to_points(
        cache, [(0, 0), (1, 1)], start, destination, include_destination=True,
    )

    assert partial == [start, (-60.0, 70.0)]
    assert complete[-1] == destination


def test_alternatives_endpoint_forwards_one_resolved_voyage_request(monkeypatch):
    seen = {}
    response = SimpleNamespace(candidates=[], balanced_summary=None)

    class FakeOptimizer:
        def __init__(self, **kwargs):
            seen["optimizer"] = kwargs

        def optimize_alternatives(self, *args, **kwargs):
            seen["search"] = (args, kwargs)
            return response

    vessel = SimpleNamespace(installed_power_kw=1.0)
    monkeypatch.setattr(navigation, "_resolve_request", lambda _req: ((-58.0, 70.0), (-69.0, 76.0), vessel))
    monkeypatch.setattr(navigation, "PolarRouteOptimizer", FakeOptimizer)
    result = navigation.alternatives(RouteRequest(
        origin_id="origin",
        destination_id="destination",
        departure_time_hours=36.0,
        grid_resolution_deg=0.75,
        avoid_icebergs=False,
    ))

    assert result is response
    assert seen["search"] == (
        (-58.0, 70.0, -69.0, 76.0),
        {"grid_resolution_deg": 0.75, "departure_time_hours": 36.0, "avoid_icebergs": False},
    )


def test_voyage_creation_receives_selected_profile_weights_and_departure(monkeypatch):
    expected_weights = RouteWeights(fuel=4.0, time=0.05, risk=1.0)
    seen = {}
    state = object()
    engine = SimpleNamespace(state=state)

    monkeypatch.setattr(voyages, "_endpoint", lambda explicit, identifier, _label: ((-58.0, 70.0), identifier or ""))
    monkeypatch.setattr(voyages, "get_vessel_preset", lambda _key: object())
    monkeypatch.setattr(voyages, "create_voyage", lambda **kwargs: seen.update(kwargs) or engine)

    class FakeStore:
        def register(self, value):
            assert value is engine

    monkeypatch.setattr(voyages, "get_store", lambda: FakeStore())
    result = voyages.create(CreateVoyageRequest(
        origin_id="cape_town",
        destination_id="bharati",
        vessel_key="vasiliy_golovnin",
        weights=expected_weights,
        route_profile_id="fuel-efficient",
        departure_time_hours=42.0,
    ))

    assert result is state
    assert seen["weights"] == expected_weights
    assert seen["route_profile_id"] == "fuel-efficient"
    assert seen["departure_time_hours"] == 42.0
