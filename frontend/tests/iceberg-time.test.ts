import test from 'node:test';
import assert from 'node:assert/strict';
import { resolveIcebergTargetTime } from '../src/lib/icebergTime.ts';
import {
  parseUtcDatetime,
  resolveActiveVoyageTime,
  resolvePlanningTime,
} from '../src/lib/environmentTime.ts';

test('resolveIcebergTargetTime maps integer hours up to 240 to resolved target', () => {
  const res = resolveIcebergTargetTime(18);
  assert.equal(res.status, 'resolved');
  assert.equal(res.target_model_hours, 18);
  assert.equal(res.forecast_lead_hours, 18);
  assert.equal(res.forcing_start_hours, 0);
  assert.equal(res.reason, null);
});

test('resolveIcebergTargetTime rejects fractional hours with explanation', () => {
  const res = resolveIcebergTargetTime(18.5);
  assert.equal(res.status, 'unavailable');
  assert.ok(res.reason?.includes('whole-hour'));
});

test('resolveIcebergTargetTime rejects out-of-horizon and negative values', () => {
  const beyond = resolveIcebergTargetTime(241);
  assert.equal(beyond.status, 'unavailable');
  assert.ok(beyond.reason?.includes('240 hours'));

  const negative = resolveIcebergTargetTime(-1);
  assert.equal(negative.status, 'unavailable');
  assert.ok(negative.reason?.includes('non-negative'));

  const nanVal = resolveIcebergTargetTime(Number.NaN);
  assert.equal(nanVal.status, 'unavailable');
});

test('environmentTime parseUtcDatetime enforces valid timezone offset', () => {
  assert.throws(() => parseUtcDatetime('2026-10-24T12:00:00'), /timezone offset/);
  const valid = parseUtcDatetime('2026-10-24T12:00:00Z');
  assert.equal(valid.toISOString(), '2026-10-24T12:00:00.000Z');
});

test('resolvePlanningTime keeps model departure and planning reference separated', () => {
  const missingRef = resolvePlanningTime(null, 12, 36);
  assert.equal(missingRef.status, 'unavailable');
  assert.equal(missingRef.model_departure_time_hours, 36);
  assert.ok(missingRef.reason?.includes('planning_reference_iso'));

  const resolved = resolvePlanningTime('2026-10-24T07:00:00+05:30', 18, 42);
  assert.equal(resolved.status, 'resolved');
  assert.equal(resolved.target_time_utc, '2026-10-24T19:30:00.000Z');
  assert.equal(resolved.lead_hours, 18);
  assert.equal(resolved.model_departure_time_hours, 42);
});

test('time resolvers reject negative or overflowing offsets explicitly', () => {
  assert.throws(() => resolvePlanningTime('2026-10-24T07:00:00Z', 0, -1), /cannot be negative/);
  assert.throws(() => resolveActiveVoyageTime('2026-10-24T07:00:00Z', 0, null, -1), /non-negative/);
  assert.throws(() => resolvePlanningTime('2026-10-24T07:00:00Z', 1e300), /datetime range/);
  assert.throws(() => resolveActiveVoyageTime('2026-10-24T07:00:00Z', 1e300), /datetime range/);
});

test('resolveActiveVoyageTime aligns simulation tick with UTC target', () => {
  const res = resolveActiveVoyageTime('2026-10-24T07:00:00+05:30', 12, '2026-10-24T13:30:00Z', 36);
  assert.equal(res.status, 'resolved');
  assert.equal(res.target_time_utc, '2026-10-24T13:30:00.000Z');
  assert.equal(res.elapsed_sim_hours, 12);
  assert.equal(res.model_departure_time_hours, 36);
});
