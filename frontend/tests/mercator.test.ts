import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  RegionViewport,
  graticuleStep,
  mercLat,
  mercY,
  splitAtAntimeridian,
  viewOutline,
} from '../src/map/mercator.ts';

const REGION = { lon_min: -30, lon_max: 165, lat_min: -75, lat_max: 40 };
const near = (a: number, b: number, tol = 1e-6): boolean => Math.abs(a - b) <= tol;

function viewport(w = 1200, h = 800): RegionViewport {
  const v = new RegionViewport(REGION);
  v.resize(w, h);
  return v;
}

test('mercY and mercLat are inverses, and the equator maps to zero', () => {
  assert.ok(near(mercY(0), 0));
  for (const lat of [-75, -60, -33.9, -12, 0, 15.4, 40]) assert.ok(near(mercLat(mercY(lat)), lat, 1e-9), `lat ${lat}`);
  assert.ok(mercY(-70) < mercY(-30), 'monotonic: further south is lower');
});

test('mercator is conformal: a small square stays square at any latitude', () => {
  const v = viewport();
  v.zoomAt(600, 400, 8);
  for (const lat of [-70, -34, 15]) {
    // A square on the ground: d degrees of latitude north, and d / cos(lat) degrees of longitude east.
    const a = v.project(lat, 20);
    const east = v.project(lat, 20 + 0.01 / Math.cos((lat * Math.PI) / 180));
    const north = v.project(lat + 0.01, 20);
    const dx = Math.hypot(east.x - a.x, east.y - a.y);
    const dy = Math.hypot(north.x - a.x, north.y - a.y);
    assert.ok(Math.abs(dx / dy - 1) < 0.01, `lat ${lat}: east ${dx} vs north ${dy}`);
  }
});

test('project and unproject round-trip', () => {
  const v = viewport();
  for (const [lat, lon] of [[-33.9, 18.4], [15.4, 73.8], [-69.4, 76.2], [-42.9, 147.3]]) {
    const p = v.project(lat, lon);
    const q = v.unproject(p.x, p.y);
    assert.ok(near(q.lat, lat, 1e-7) && near(q.lon, lon, 1e-7), `${lat},${lon}`);
  }
});

test('the whole region fits at the initial scale and the view cannot leave the region', () => {
  const v = viewport();
  const sw = v.project(REGION.lat_min, REGION.lon_min);
  const ne = v.project(REGION.lat_max, REGION.lon_max);
  assert.ok(sw.x >= -1 && sw.y <= 801 && ne.x <= 1201 && ne.y >= -1, 'region fully visible at fit');
  v.zoomAt(600, 400, 6);
  v.panBy(5000, -5000);
  const tl = v.unproject(0, 0);
  const br = v.unproject(1200, 800);
  assert.ok(tl.lon >= REGION.lon_min - 1e-6 && br.lon <= REGION.lon_max + 1e-6);
  assert.ok(tl.lat <= REGION.lat_max + 1e-6 && br.lat >= REGION.lat_min - 1e-6);
});

test('zoomAt keeps the point under the cursor fixed, and respects the zoom limits', () => {
  const v = viewport();
  v.zoomAt(600, 400, 3);
  const before = v.unproject(450, 300);
  v.zoomAt(450, 300, 1.5);
  const after = v.unproject(450, 300);
  assert.ok(near(before.lon, after.lon, 1e-6) && near(before.lat, after.lat, 1e-6));
  v.zoomAt(600, 400, 1e-6);
  assert.ok(near(v.zoom, 1, 1e-9), 'cannot zoom out past the region');
  v.zoomAt(600, 400, 1e9);
  assert.ok(v.zoom <= 40 + 1e-9, 'zoom is capped');
});

test('fitPoints frames Cape Town to Bharati inside the canvas', () => {
  const v = viewport();
  const pts = [
    { lat: -33.9, lon: 18.4 },
    { lat: -69.4, lon: 76.2 },
  ];
  v.fitPoints(pts, 80);
  for (const p of pts) {
    const s = v.project(p.lat, p.lon);
    assert.ok(s.x >= 0 && s.x <= 1200 && s.y >= 0 && s.y <= 800, `${p.lat},${p.lon} -> ${s.x},${s.y}`);
  }
  v.fitPoints([], 80);
  assert.ok(near(v.zoom, 1, 1e-9));
});

test('viewOutline samples a curved screen edge instead of using four corners', () => {
  // A source whose screen rectangle maps to a latitude/longitude band bending with y.
  const src = {
    widthPx: 400,
    heightPx: 300,
    insetLeft: 100,
    insetBottom: 50,
    screenToLatLon: (x: number, y: number) => ({ lat: -60 - y / 10 - (x * x) / 40000, lon: x / 10 }),
  };
  const out = viewOutline(src, 10);
  assert.equal(out.length, 41, '4 edges x 10 samples, closed');
  assert.deepEqual(out[0], out[out.length - 1]);
  const lons = out.map((p) => p.lon);
  assert.ok(Math.min(...lons) >= 10 - 1e-9, 'honours the left inset');
  assert.deepEqual(viewOutline({ ...src, widthPx: 2, insetLeft: 0 }), [], 'degenerate view gives no outline');
});

test('splitAtAntimeridian breaks a line that jumps across ±180', () => {
  const runs = splitAtAntimeridian([
    { lat: -60, lon: 170 },
    { lat: -61, lon: 179 },
    { lat: -62, lon: -179 },
    { lat: -63, lon: -170 },
  ]);
  assert.equal(runs.length, 2);
  assert.equal(runs[0].length, 2);
  assert.equal(splitAtAntimeridian([]).length, 0);
});

test('graticuleStep picks a readable spacing', () => {
  assert.equal(graticuleStep(195), 30);
  assert.equal(graticuleStep(40), 5);
  assert.equal(graticuleStep(8), 1);
  assert.equal(graticuleStep(1000), 45);
});
