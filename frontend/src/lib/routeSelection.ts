import type { RouteAlternative, RouteProfileId } from '../api/types';

export function defaultRouteCandidate(candidates: RouteAlternative[]): RouteProfileId | null {
  return candidates.find((candidate) => candidate.id === 'balanced' && candidate.is_feasible)?.id
    ?? candidates.find((candidate) => candidate.is_feasible)?.id
    ?? null;
}

export function isSelectableRouteCandidate(candidates: RouteAlternative[], id: RouteProfileId): boolean {
  return candidates.some((candidate) => candidate.id === id && candidate.is_feasible);
}
