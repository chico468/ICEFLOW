import assert from 'node:assert/strict';
import test from 'node:test';
import { interpolateVesselPose, interpolateAlongRoute } from '../src/map/regionalVoyageAnimation.ts';

test('follows the great-circle arc and shortest-turn heading between shared voyage ticks', () => {
  const pose = interpolateVesselPose(
    { latitude: 0, longitude: 0, heading: 350 },
    { latitude: 60, longitude: 90, heading: 10 },
    0.5,
  );
  assert.ok(Math.abs(pose.latitude - 37.76124) < 0.0001);
  assert.ok(Math.abs(pose.longitude - 26.56505) < 0.0001);
  assert.equal(pose.heading, 0);
});

test('interpolates over the short path across the antimeridian', () => {
  const pose = interpolateVesselPose(
    { latitude: -60, longitude: 179, heading: 0 },
    { latitude: -60, longitude: -179, heading: 0 },
    0.5,
  );
  assert.ok(Math.abs(Math.abs(pose.longitude) - 180) < 0.0001);
  assert.ok(Math.abs(pose.latitude - -60.00378) < 0.0001);
});

test('interpolates position along a route geometry by distance with heading toward next point', () => {
  const route = [
    { latitude: 0, longitude: 0 },
    { latitude: 0, longitude: 10 },
    { latitude: 10, longitude: 10 },
  ];
  const pose = interpolateAlongRoute(route, 0.25);
  assert.ok(pose);
  assert.ok(Math.abs(pose.longitude) <= 5.001);
  assert.ok(Math.abs(pose.latitude) < 1);
  assert.equal(typeof pose.heading, 'number');
});
