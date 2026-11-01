import assert from 'node:assert/strict';
import { test } from 'node:test';
import { readFileSync } from 'node:fs';
import { dirname, join } from 'node:path';
import { fileURLToPath } from 'node:url';
import { RecordedTimelineSource } from '../src/lib/timeline.ts';

const FIXTURE_PATH = join(dirname(fileURLToPath(import.meta.url)), '..', 'e2e', 'fixtures', 'golden-voyage-timeline.json');
const fixture = JSON.parse(readFileSync(FIXTURE_PATH, 'utf8'));
const steps = fixture.steps as Array<Record<string, unknown>>;

test('RecordedTimelineSource kind is recorded', () => {
  const src = new RecordedTimelineSource();
  assert.equal(src.kind, 'recorded');
});

test('RecordedTimelineSource label', () => {
  const src = new RecordedTimelineSource();
  assert.equal(src.label, 'Recorded replay — real data, departure 2022-01-15');
  assert.equal(src.error, null);
});

test('Fixture has expected structure', () => {
  assert.ok(steps.length > 0);
  assert.equal(steps[0].t_utc, '2022-01-15T12:30:00+00:00');
  assert.ok(Array.isArray(steps[0].nearby_bergs));
  assert.ok(typeof steps[0].provenance_by_variable === 'object');
  assert.equal(steps[0].provenance_by_variable['ice_conc'].kind, 'observed');
  assert.equal(steps[0].provenance_by_variable['ice_conc'].source, 'NOAA/NSIDC CDR G02202 Version 6');
});
