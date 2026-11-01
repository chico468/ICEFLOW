import assert from 'node:assert/strict';
import { test } from 'node:test';
import { normalizeProvenance, PROVENANCE_KINDS } from '../src/lib/provenance.ts';

test('PROVENANCE_KINDS contains the six canonical kinds', () => {
  assert.deepEqual(PROVENANCE_KINDS, [
    'observed',
    'reanalysis',
    'forecast',
    'derived',
    'simulated',
    'real-seed',
  ]);
});

test('normalizeProvenance returns null for null/undefined input', () => {
  assert.equal(normalizeProvenance(null), null);
  assert.equal(normalizeProvenance(undefined), null);
});

test('normalizeProvenance passes through shape 1 (status/note/age_days) unchanged', () => {
  const out = normalizeProvenance({
    status: 'observed',
    source: 'NOAA/NSIDC CDR G02202',
    note: 'G02202 daily Antarctic sea-ice concentration',
    observed_date: '2022-01-15',
    age_days: 2,
  });
  assert.equal(out?.status, 'observed');
  assert.equal(out?.source, 'NOAA/NSIDC CDR G02202');
  assert.equal(out?.note, 'G02202 daily Antarctic sea-ice concentration');
  assert.equal(out?.observed_date, '2022-01-15');
  assert.equal(out?.age_days, 2);
});

test('normalizeProvenance maps shape 2 (kind/age_hours) to shape 1', () => {
  const out = normalizeProvenance({
    kind: 'simulated',
    source: 'synthetic Southern Ocean forcing',
    product: undefined,
    valid_time: '2022-01-15',
    age_hours: 48,
  });
  assert.equal(out?.status, 'simulated');
  assert.equal(out?.source, 'synthetic Southern Ocean forcing');
  assert.equal(out?.note, '');
  assert.equal(out?.observed_date, '2022-01-15');
  assert.equal(out?.age_days, 2); // 48h / 24
});

test('normalizeProvenance maps legacy kinds to canonical', () => {
  assert.equal(normalizeProvenance({ status: 'real', source: 'x' })?.status, 'observed');
  assert.equal(normalizeProvenance({ status: 'real-observation', source: 'x' })?.status, 'observed');
  assert.equal(normalizeProvenance({ status: 'synthetic', source: 'x' })?.status, 'simulated');
  assert.equal(normalizeProvenance({ kind: 'synthetic', source: 'x' })?.status, 'simulated');
});

test('normalizeProvenance keeps canonical kinds as-is', () => {
  for (const kind of PROVENANCE_KINDS) {
    const out = normalizeProvenance({ status: kind as any, source: 'x' });
    assert.equal(out?.status, kind);
  }
});

test('normalizeProvenance passes unknown kinds through', () => {
  const out = normalizeProvenance({ status: 'experimental_ml', source: 'x' });
  assert.equal(out?.status, 'experimental_ml');
});

test('normalizeProvenance returns null when no status/kind and no source', () => {
  assert.equal(normalizeProvenance({ status: '', source: '' }), null);
  assert.equal(normalizeProvenance({ kind: '', source: '' }), null);
});

test('normalizeProvenance omits optional fields when absent', () => {
  const out = normalizeProvenance({ status: 'forecast', source: 'GFS' });
  assert.equal(out?.observed_date, undefined);
  assert.equal(out?.age_days, undefined);
  assert.equal(out?.note, '');
});
