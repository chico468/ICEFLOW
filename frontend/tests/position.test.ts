import assert from 'node:assert/strict';
import { test } from 'node:test';
import { SimulatedPositionSource } from '../src/lib/position.ts';
import { SPEED_LABELS } from '../src/store/useSimClock.ts';

function makePoint(index: number, sim_hours: number, lat: number, lon: number): any {
  return {
    index, t_utc: `2022-01-15T${String(12 + index).padStart(2, '0')}:00:00+00:00`,
    sim_hours, lat, lon, sog_kn: 10, cog: 140, heading: 140,
    ice_conc: 0.1, ice_thick_m: 0.5, wind_speed_ms: 5, wind_dir_from_deg: 90,
    hs_m: 2.0, visibility_km: 10, nearest_contact_nm: null, active_alerts: [],
    provenance_by_variable: {},
  };
}

test('SimulatedPositionSource returns first point at time zero', () => {
  const tl = [makePoint(0, 0, -34.0, 18.0), makePoint(1, 6, -33.0, 19.0)];
  const src = new SimulatedPositionSource({ timeline: tl });
  const fix = src.now();
  assert.ok(fix);
  assert.equal(fix.lat, -34.0);
  assert.equal(fix.lon, 18.0);
});

test('SimulatedPositionSource interpolates between steps', () => {
  const tl = [makePoint(0, 0, -34.0, 18.0), makePoint(1, 6, -33.0, 19.0)];
  const src = new SimulatedPositionSource({ timeline: tl });
  src.seek(3);
  const fix = src.now();
  assert.ok(fix);
  assert.equal(fix.lat, -33.5);
  assert.equal(fix.lon, 18.5);
});

test('SimulatedPositionSource clamps to last point beyond timeline', () => {
  const tl = [makePoint(0, 0, -34.0, 18.0), makePoint(1, 6, -33.0, 19.0)];
  const src = new SimulatedPositionSource({ timeline: tl });
  src.seek(100);
  const fix = src.now();
  assert.ok(fix);
  assert.equal(fix.lat, -33.0);
  assert.equal(fix.lon, 19.0);
});

test('SimulatedPositionSource subscribe invokes callback immediately', () => {
  const tl = [makePoint(0, 0, -34.0, 18.0)];
  const src = new SimulatedPositionSource({ timeline: tl });
  const received: any[] = [];
  const unsub = src.subscribe((fix) => received.push(fix));
  assert.equal(received.length, 1);
  assert.equal(received[0].lat, -34.0);
  unsub();
});

test('SPEED_LABELS maps speeds to labels', () => {
  assert.equal(SPEED_LABELS[1], '1×');
  assert.equal(SPEED_LABELS[60], '60×');
  assert.equal(SPEED_LABELS[600], '600×');
  assert.equal(SPEED_LABELS[3600], '3600×');
});
