// Run with: npm run test:unit   (Node 22.18+ strips the types; no dependency is involved.)
import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  FLOW_KINDS,
  ParticleField,
  advanceStep,
  insideGrid,
  isLandAt,
  makeFlowGrid,
  mulberry32,
  particleCountFor,
  sampleFlow,
  speedBucket,
} from '../src/map/flow.ts';
import { toEpsg3031 } from '../src/map/projection.ts';

const DEG = Math.PI / 180;

/** The real polar projection, at 1 px = 1 km, y down. */
const polar = (lat: number, lon: number) => {
  const p = toEpsg3031(lat, lon);
  return { x: p.x / 1000, y: -p.y / 1000 };
};

const grid3x3 = () =>
  makeFlowGrid(
    [-60, -59, -58],
    [10, 11, 12],
    [
      [1, 2, 3],
      [4, 5, 6],
      [7, 8, 9],
    ],
    [
      [0, 0, 0],
      [0, 0, 0],
      [10, 10, 10],
    ],
  )!;

test('makeFlowGrid refuses grids that are not regular, ascending and complete', () => {
  assert.equal(makeFlowGrid([-60], [10, 11], [[1, 2]], [[1, 2]]), null, 'too few rows');
  assert.equal(makeFlowGrid([-59, -60], [10, 11], [[1, 2], [3, 4]], [[1, 2], [3, 4]]), null, 'descending latitudes');
  assert.equal(makeFlowGrid([-60, -59], [10, 11], [[1, 2]], [[1, 2], [3, 4]]), null, 'row count mismatch');
  assert.equal(makeFlowGrid([-60, -59], [10, 11], [[1], [3, 4]], [[1, 2], [3, 4]]), null, 'ragged row');
  assert.ok(grid3x3());
});

test('sampleFlow is exact at nodes and bilinear between them', () => {
  const g = grid3x3();
  const out: [number, number] = [0, 0];
  assert.ok(sampleFlow(g, -60, 10, out));
  assert.deepEqual(out, [1, 0]);
  assert.ok(sampleFlow(g, -58, 12, out));
  assert.deepEqual(out, [9, 10]);
  assert.ok(sampleFlow(g, -59.5, 10.5, out)); // centre of the first cell: mean of 1,2,4,5
  assert.ok(Math.abs(out[0] - 3) < 1e-12 && Math.abs(out[1]) < 1e-12);
});

test('sampleFlow reports outside-the-grid and non-finite nodes instead of inventing a value', () => {
  const g = grid3x3();
  const out: [number, number] = [99, 99];
  assert.equal(sampleFlow(g, -61, 10.5, out), false);
  assert.equal(sampleFlow(g, -59, 12.01, out), false);
  assert.deepEqual(out, [99, 99], 'output untouched on failure');
  g.u[1][1] = Number.NaN;
  assert.equal(sampleFlow(g, -59.5, 10.5, out), false, 'a NaN corner makes the cell unusable');
  assert.ok(insideGrid(g, -59, 11));
  assert.ok(!insideGrid(g, -57, 11));
});

test('land comes from the field itself: zero wave height marks a cell as not ocean', () => {
  const g = makeFlowGrid([0, 1], [0, 1], [[1, 1], [1, 1]], [[1, 1], [1, 1]], [[0, 0.4], [0.4, 0.4]])!;
  assert.equal(isLandAt(g, 0.1, 0.1), true);
  assert.equal(isLandAt(g, 0.9, 0.9), false);
  assert.equal(isLandAt(grid3x3(), -59, 11), false, 'no mask, no land claim');
});

/** Ground bearing of a small geographic displacement, degrees clockwise from north. */
const bearing = (lat0: number, lon0: number, lat1: number, lon1: number): number => {
  const dn = (lat1 - lat0) * DEG;
  const de = (lon1 - lon0) * DEG * Math.cos(((lat0 + lat1) / 2) * DEG);
  return ((Math.atan2(de, dn) / DEG) + 360) % 360;
};

test('advanceStep follows the GEOGRAPHIC direction on the polar chart, not the screen axes', () => {
  // A wind blowing toward a given ground bearing must move a particle along that bearing wherever it is.
  const cases: [string, number, number, number][] = [
    ['east', 5, 0, 90],
    ['north', 0, 5, 0],
    ['north-east', 5, 5, 45],
    ['south-west', -4, -4, 225],
  ];
  for (const [name, u, v, expected] of cases) {
    for (const lon of [0, 45, 90, 135, -120]) {
      const next = advanceStep(polar, -62, lon, u, v, 3)!;
      assert.ok(next, `${name} @ ${lon}`);
      const got = bearing(-62, lon, next.lat, next.lon);
      const diff = Math.abs(((got - expected + 540) % 360) - 180);
      assert.ok(diff < 1.0, `${name} at lon ${lon}: expected ${expected}°, got ${got.toFixed(2)}°`);
    }
  }
});

test('advanceStep moves exactly the requested number of screen pixels', () => {
  for (const px of [0.5, 2, 6]) {
    const start = polar(-65, 30);
    const next = advanceStep(polar, -65, 30, 3, 2, px)!;
    const end = polar(next.lat, next.lon);
    const travelled = Math.hypot(end.x - start.x, end.y - start.y);
    assert.ok(Math.abs(travelled - px) / px < 0.02, `${px} px requested, ${travelled.toFixed(3)} moved`);
  }
});

test('the same east wind points a different way on screen at different longitudes (the naive method cannot do this)', () => {
  const dir = (lon: number): number => {
    const a = polar(-62, lon);
    const n = advanceStep(polar, -62, lon, 5, 0, 1)!;
    const b = polar(n.lat, n.lon);
    return Math.atan2(b.y - a.y, b.x - a.x) / DEG;
  };
  const rotation = Math.abs(((dir(90) - dir(0) + 540) % 360) - 180);
  assert.ok(Math.abs(rotation - 90) < 2, `expected about 90° of rotation between lon 0 and 90, got ${rotation.toFixed(1)}`);
});

test('advanceStep returns null for calm air, zero distance, or the pole', () => {
  assert.equal(advanceStep(polar, -60, 0, 0, 0, 2), null);
  assert.equal(advanceStep(polar, -60, 0, 5, 0, 0), null);
  assert.equal(advanceStep(polar, -89.95, 0, 0, -5, 50), null);
});

const flat = (lat: number, lon: number) => ({ x: lon * 10, y: -lat * 10 });

function eastwardField(land?: number[][]) {
  const lats = [-30, -20, -10];
  const lons = [5, 20, 35];
  const u = lats.map(() => lons.map(() => 4));
  const v = lats.map(() => lons.map(() => 0));
  return makeFlowGrid(lats, lons, u, v, land)!;
}

const stepOpts = (rng: () => number, g: ReturnType<typeof eastwardField>, dt = 1 / 60) => ({
  project: flat,
  spawn: () => ({ lat: -30 + rng() * 20, lon: 5 + rng() * 30 }),
  widthPx: 400,
  heightPx: 400,
  marginPx: 24,
  dtSec: dt,
  reproject: false,
  _g: g,
});

test('particles advect with the field and never survive outside the grid', () => {
  const g = eastwardField();
  const pf = new ParticleField(FLOW_KINDS.wind, 200, 7);
  pf.setGrid(g);
  const rng = mulberry32(3);
  const o = stepOpts(rng, g);
  for (let f = 0; f < 400; f += 1) {
    pf.step(o);
    for (let i = 0; i < pf.count; i += 1) {
      if (!pf.alive[i]) continue;
      assert.ok(insideGrid(g, pf.lat[i], pf.lon[i]), 'alive particle outside the grid');
    }
  }
  let alive = 0;
  for (let i = 0; i < pf.count; i += 1) alive += pf.alive[i];
  assert.ok(alive > 150, `most particles should be alive, got ${alive}`);

  // Direction: a purely eastward field must move longitude up and leave latitude alone.
  const before = Float64Array.from(pf.lat);
  const lonBefore = Float64Array.from(pf.lon);
  const wasAlive = Uint8Array.from(pf.alive);
  pf.step(o);
  for (let i = 0; i < pf.count; i += 1) {
    if (!wasAlive[i] || !pf.alive[i] || pf.age[i] < 2) continue;
    if (pf.lon[i] === lonBefore[i]) continue; // respawned this frame
    assert.ok(pf.lon[i] > lonBefore[i], 'moved west in an eastward field');
    assert.ok(Math.abs(pf.lat[i] - before[i]) < 1e-9, 'drifted north/south in an eastward field');
  }
});

test('particle speed on screen is proportional to field speed', () => {
  const mk = (speed: number): number => {
    const g = makeFlowGrid([-30, -10], [5, 35], [[speed, speed], [speed, speed]], [[0, 0], [0, 0]])!;
    const pf = new ParticleField(FLOW_KINDS.wind, 1, 1);
    pf.setGrid(g);
    const o = { ...stepOpts(mulberry32(1), g as never), spawn: () => ({ lat: -20, lon: 10 }) };
    pf.step(o); // spawns
    const x0 = flat(pf.lat[0], pf.lon[0]).x;
    pf.step(o);
    return flat(pf.lat[0], pf.lon[0]).x - x0;
  };
  const slow = mk(2);
  const fast = mk(8);
  assert.ok(Math.abs(fast / slow - 4) < 0.01, `4x the speed should be 4x the distance, got ${(fast / slow).toFixed(3)}`);
});

test('current particles are removed from land cells and never respawn onto them', () => {
  const land = [
    [0, 0, 0],
    [0, 0, 0],
    [0, 0, 0],
  ]; // all ocean first
  const lats = [-30, -20, -10];
  const g = eastwardField(land.map((r) => r.map(() => 0.5)));
  // Make the western column land.
  g.land = lats.map(() => [true, false, false]);
  const pf = new ParticleField(FLOW_KINDS.current, 300, 5);
  pf.setGrid(g);
  const rng = mulberry32(9);
  const o = stepOpts(rng, g);
  for (let f = 0; f < 300; f += 1) {
    pf.step(o);
    for (let i = 0; i < pf.count; i += 1) {
      if (pf.alive[i]) assert.equal(isLandAt(g, pf.lat[i], pf.lon[i]), false, 'a current particle is on land');
    }
  }
});

test('the same seed reproduces the same particle layout (deterministic demonstration mode)', () => {
  const run = (): number[] => {
    const g = eastwardField();
    const pf = new ParticleField(FLOW_KINDS.wind, 50, 42);
    pf.setGrid(g);
    const o = stepOpts(mulberry32(5), g);
    for (let f = 0; f < 60; f += 1) pf.step(o);
    return Array.from(pf.lat.slice(0, 50)).concat(Array.from(pf.lon.slice(0, 50)));
  };
  assert.deepEqual(run(), run());
});

test('reprojecting rebuilds screen trails from geography', () => {
  const g = eastwardField();
  const pf = new ParticleField(FLOW_KINDS.wind, 20, 2);
  pf.setGrid(g);
  const o = stepOpts(mulberry32(8), g);
  for (let f = 0; f < 30; f += 1) pf.step(o);
  const zoomed = (lat: number, lon: number) => ({ x: lon * 20, y: -lat * 20 });
  pf.step({ ...o, project: zoomed, reproject: true, dtSec: 0 });
  for (let i = 0; i < pf.count; i += 1) {
    if (!pf.alive[i] || pf.trailCount[i] === 0) continue;
    const head = zoomed(pf.trailLat[i * pf.trailLength], pf.trailLon[i * pf.trailLength]);
    assert.ok(Math.abs(pf.trailX[i * pf.trailLength] - head.x) < 0.05, 'screen trail not rebuilt');
  }
});

test('speedBucket clamps and particleCountFor stays within its budget', () => {
  assert.equal(speedBucket(0, 25, 6), 0);
  assert.equal(speedBucket(-3, 25, 6), 0);
  assert.equal(speedBucket(12.5, 25, 6), 3);
  assert.equal(speedBucket(999, 25, 6), 5);
  assert.equal(particleCountFor(100, 100), 250);
  assert.equal(particleCountFor(4000, 3000), 1600);
  const mid = particleCountFor(1400, 800);
  assert.ok(mid > 250 && mid < 1600);
});
