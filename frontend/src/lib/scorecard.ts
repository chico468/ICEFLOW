import type { ScorecardResponse } from '../api/types';
import scorecardFixtureRaw from '../api/fixtures/scorecard.fixture.json' with { type: 'json' };

export const scorecardFixture = scorecardFixtureRaw as unknown as ScorecardResponse;

/**
 * Whether the scorecard being shown is sample data rather than a live result.
 * True when the endpoint errored, there is no payload, or the payload carries the fixture's
 * marker (data_source 'none' with the fixture git sha). Callers must render these numbers
 * with a prominent "not real results" banner.
 */
export function scorecardIsSampleData(scorecard: ScorecardResponse | null | undefined, isError: boolean): boolean {
  if (isError || !scorecard) return true;
  return scorecard.data_source === 'none' && scorecard.git_sha === scorecardFixture.git_sha;
}
