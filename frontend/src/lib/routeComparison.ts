import type { RouteEvaluation } from '../api/types';

export interface RouteDeltas {
  fuelSavedTonnes: number;
  timeSavedHours: number;
  distanceSavedNm: number;
  co2SavedTonnes: number;
}

/** Positive values mean the candidate uses/needs less than the fixed Balanced reference. */
export function routeDeltas(candidate: RouteEvaluation, reference: RouteEvaluation): RouteDeltas {
  return {
    fuelSavedTonnes: reference.total_fuel_burn_tonnes - candidate.total_fuel_burn_tonnes,
    timeSavedHours: reference.total_transit_hours - candidate.total_transit_hours,
    distanceSavedNm: reference.total_distance_nm - candidate.total_distance_nm,
    co2SavedTonnes: reference.total_co2_tonnes - candidate.total_co2_tonnes,
  };
}
