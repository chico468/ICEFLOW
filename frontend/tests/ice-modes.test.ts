import assert from 'node:assert/strict';
import { test } from 'node:test';
import { countMissing, hasFinite, isMissing, modeAvailability, sameGrid, type IceFieldLike } from '../src/map/iceModes.ts';

const field = (over: Partial<IceFieldLike> = {}): IceFieldLike => ({
  lats: [-70, -69, -68],
  lons: [10, 12, 14],
  concentration: [[0, 0.2, 0.5], [0.6, 0.8, 0.95], [0.1, 0.4, 0.9]],
  thickness_m: [[0, 0.3, 0.6], [0.8, 1.2, 1.5], [0.1, 0.5, 1.0]],
  ...over,
});
const noBase = { field: null, loading: false, error: null };

test('zero is a measurement; null, undefined, NaN and non-numbers are missing', () => {
  assert.equal(isMissing(0), false, 'zero concentration is open water, not missing data');
  for (const v of [null, undefined, Number.NaN, Infinity, '0.3', {}]) assert.equal(isMissing(v), true, String(v));
});

test('counting missing cells, and detecting an all-missing grid', () => {
  assert.deepEqual(countMissing([[0, null], [Number.NaN, 0.4]]), { missing: 2, total: 4 });
  assert.deepEqual(countMissing(undefined), { missing: 0, total: 0 });
  assert.equal(hasFinite([[null, null], [undefined, Number.NaN]]), false);
  assert.equal(hasFinite([[null, 0]]), true, 'a real zero counts as data');
});

test('with no field every mode is unavailable and says why', () => {
  const a = modeAvailability(null, 0, noBase);
  for (const m of Object.values(a)) assert.deepEqual([m.available, m.reason], [false, 'No ice field is loaded.']);
});

test('concentration and classes are available whenever concentration exists; thickness only when it exists', () => {
  const full = modeAvailability(field(), 0, noBase);
  assert.equal(full.concentration.available && full.classes.available && full.thickness.available, true);
  const noThickness = modeAvailability(field({ thickness_m: undefined }), 0, noBase);
  assert.equal(noThickness.thickness.available, false);
  assert.match(noThickness.thickness.reason!, /no thickness data/);
  assert.equal(noThickness.concentration.available, true, 'losing thickness does not take concentration with it');
  const allNull = modeAvailability(field({ thickness_m: [[null, null], [null, null]] }), 0, noBase);
  assert.equal(allNull.thickness.available, false);
});

test('change needs a later forecast time AND a +0 h field on the very same grid', () => {
  const f = field();
  assert.match(modeAvailability(f, 0, noBase).change.reason!, /after \+0 h/);
  assert.match(modeAvailability(f, 24, { field: null, loading: true, error: null }).change.reason!, /Loading the \+0 h field/);
  assert.match(modeAvailability(f, 24, { field: null, loading: false, error: 'HTTP 500' }).change.reason!, /could not be loaded: HTTP 500/);
  assert.match(modeAvailability(f, 24, noBase).change.reason!, /No \+0 h field is available/);
  const otherGrid = field({ lats: [-70, -69] });
  assert.match(modeAvailability(f, 24, { field: otherGrid, loading: false, error: null }).change.reason!, /different grid/);
  assert.equal(modeAvailability(f, 24, { field: field(), loading: false, error: null }).change.available, true);
  assert.equal(modeAvailability(f, 24, { field: field({ concentration: [[null]] }), loading: false, error: null }).change.available, false);
});

test('an error outranks a loading flag, so a failed comparison is never reported as "loading"', () => {
  const r = modeAvailability(field(), 24, { field: null, loading: true, error: 'timeout' }).change;
  assert.match(r.reason!, /could not be loaded/);
});

test('sameGrid compares size and both corners', () => {
  assert.equal(sameGrid(field(), field()), true);
  assert.equal(sameGrid(field(), field({ lons: [10, 12, 15] })), false);
  assert.equal(sameGrid(field(), field({ lats: [-71, -69, -68] })), false);
});

// ---------------------------------------------------------------- malformed responses
import { isUsableIceField } from '../src/map/iceModes.ts';

test('isUsableIceField accepts a real grid and rejects everything else without throwing', () => {
  assert.equal(isUsableIceField(field()), true);
  for (const bad of [null, undefined, 0, 'x', {}, { lats: [1], lons: [1, 2] }, { lats: [1, 2], lons: 'x' }, { lats: [1, Number.NaN], lons: [1, 2] }, { lats: [1, '2'], lons: [1, 2] }]) {
    assert.equal(isUsableIceField(bad), false, JSON.stringify(bad));
  }
});

test('counting and detection tolerate non-array grids and ragged rows', () => {
  assert.deepEqual(countMissing(3 as never), { missing: 0, total: 0 });
  assert.deepEqual(countMissing([[1], null, 'x', [null]] as never), { missing: 1, total: 2 });
  assert.equal(hasFinite('nope' as never), false);
});

test('a malformed field makes every mode unavailable with a clear reason (not an exception)', () => {
  const a = modeAvailability({ lats: 5, lons: 'x' } as never, 24, noBase);
  for (const m of Object.values(a)) assert.match(m.reason!, /malformed/);
  const b = modeAvailability(field(), 24, { field: { lats: 5 } as never, loading: false, error: null });
  assert.equal(b.change.available, false);
});
