import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveWindBand } from '../src/map/windBandMatch.ts';

const BANDS = [
  '2026-10-24T00:00:00Z',
  '2026-10-24T03:00:00Z',
  '2026-10-24T06:00:00Z',
  '2026-10-24T09:00:00Z',
  '2026-10-24T12:00:00Z',
];

test('exact match returns the matching band with zero offset', () => {
  const result = resolveWindBand('2026-10-24T06:00:00Z', BANDS);
  assert.equal(result.band, '2026-10-24T06:00:00Z');
  assert.equal(result.exact, true);
  assert.equal(result.offsetHours, 0);
  assert.equal(result.reason, null);
});

test('no reference time returns unavailable', () => {
  const result = resolveWindBand(null, BANDS);
  assert.equal(result.band, null);
  assert.equal(result.exact, false);
  assert.match(result.reason ?? '', /No reference time/);
});

test('empty band list returns unavailable', () => {
  const result = resolveWindBand('2026-10-24T06:00:00Z', []);
  assert.equal(result.band, null);
  assert.match(result.reason ?? '', /No wind bands/);
});

test('closest band is selected when no exact match exists within tolerance', () => {
  const result = resolveWindBand('2026-10-24T07:30:00Z', BANDS);
  assert.equal(result.band, '2026-10-24T06:00:00Z');
  assert.equal(result.exact, false);
  assert.equal(result.offsetHours, -1.5);
  assert.match(result.reason ?? '', /closest available band/);
});

test('a band beyond the tolerance is refused', () => {
  const result = resolveWindBand('2026-10-25T00:00:00Z', BANDS, 6);
  assert.equal(result.band, null);
  assert.match(result.reason ?? '', /beyond the 6h tolerance/);
});

test('nearest band is chosen on both sides of the reference', () => {
  const before = resolveWindBand('2026-10-24T04:30:00Z', BANDS);
  assert.equal(before.band, '2026-10-24T03:00:00Z');
  assert.equal(before.offsetHours, -1.5);
  const after = resolveWindBand('2026-10-24T10:30:00Z', BANDS);
  assert.equal(after.band, '2026-10-24T09:00:00Z');
  assert.equal(after.offsetHours, -1.5);
});

test('invalid reference timestamp is refused', () => {
  const result = resolveWindBand('not-a-date', BANDS);
  assert.equal(result.band, null);
  assert.match(result.reason ?? '', /valid ISO-8601/);
});

test('bands that are not parseable timestamps are ignored', () => {
  const result = resolveWindBand('2026-10-24T06:00:00Z', ['gfs-0', '2026-10-24T06:00:00Z']);
  assert.equal(result.band, '2026-10-24T06:00:00Z');
  assert.equal(result.exact, true);
});