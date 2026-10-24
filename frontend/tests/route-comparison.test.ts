import assert from 'node:assert/strict';
import test from 'node:test';
import type { RouteAlternative, RouteEvaluation } from '../src/api/types.ts';
import { routeDeltas } from '../src/lib/routeComparison.ts';
import { defaultRouteCandidate, isSelectableRouteCandidate } from '../src/lib/routeSelection.ts';

function evaluation(overrides: Partial<RouteEvaluation> = {}): RouteEvaluation {
  return {
    label: 'fixture',
    waypoints: [],
    total_distance_nm: 1000,
    total_transit_hours: 100,
    total_fuel_burn_tonnes: 50,
    total_co2_tonnes: 160.3,
    minimum_rio: 0,
    mean_rio: 0,
    max_compression_index: 0.2,
    max_ice_thickness_m: 0.5,
    is_feasible: true,
    infeasible_reason: '',
    prohibited_waypoints: 0,
    ...overrides,
  };
}

test('route comparison deltas always use the supplied Balanced reference with explicit sign direction', () => {
  const balanced = evaluation();
  const other = evaluation({
    total_distance_nm: 1025,
    total_transit_hours: 94,
    total_fuel_burn_tonnes: 47.5,
    total_co2_tonnes: 152.285,
  });
  const result = routeDeltas(other, balanced);
  assert.equal(result.fuelSavedTonnes, 2.5);
  assert.equal(result.timeSavedHours, 6);
  assert.equal(result.distanceSavedNm, -25);
  assert.ok(Math.abs(result.co2SavedTonnes - 8.015) < 1e-9);
});

test('route selection defaults to feasible Balanced and refuses partial or infeasible candidates', () => {
  const candidate = (id: 'balanced' | 'fastest', is_feasible: boolean): RouteAlternative => ({
    id,
    name: id,
    description: '',
    weights: { fuel: 1, time: 1, risk: 1 },
    evaluation: evaluation(),
    is_feasible,
    goal_reached: is_feasible,
    warnings: [],
    search: {
      nodes_expanded: 1,
      nodes_rejected_land: 0,
      nodes_rejected_rio: 0,
      nodes_rejected_iceberg: 0,
      nodes_rejected_clearance: 0,
      search_ms: 1,
      lattice_cells: 1,
      forecast_slices: 1,
      goal_reached: is_feasible,
    },
    is_synthetic_environment: true,
  });
  const candidates = [candidate('balanced', true), candidate('fastest', false)];
  assert.equal(defaultRouteCandidate(candidates), 'balanced');
  assert.equal(isSelectableRouteCandidate(candidates, 'balanced'), true);
  assert.equal(isSelectableRouteCandidate(candidates, 'fastest'), false);
  assert.equal(defaultRouteCandidate([candidate('balanced', false), candidate('fastest', true)]), 'fastest');
  assert.equal(defaultRouteCandidate([candidate('balanced', false), candidate('fastest', false)]), null);
});
