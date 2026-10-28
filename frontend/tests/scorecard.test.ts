import assert from 'node:assert/strict';
import { test } from 'node:test';
import { scorecardIsSampleData } from '../src/lib/scorecard.ts';
import scorecardFixtureRaw from '../src/api/fixtures/scorecard.fixture.json' with { type: 'json' };
import type { ScorecardResponse } from '../src/api/types.ts';

const fixture = scorecardFixtureRaw as unknown as ScorecardResponse;

const liveScorecard: ScorecardResponse = {
  ...fixture,
  git_sha: '0000000000000000000000000000000000000000',
  data_source: 'real',
};

test('scorecardIsSampleData flags the fixture and API failures as sample data', () => {
  assert.equal(scorecardIsSampleData(null, false), true);
  assert.equal(scorecardIsSampleData(undefined, false), true);
  assert.equal(scorecardIsSampleData(fixture, false), true);
  assert.equal(scorecardIsSampleData(fixture, true), true);
  assert.equal(scorecardIsSampleData(liveScorecard, false), false);
  assert.equal(scorecardIsSampleData(liveScorecard, true), true);
});
