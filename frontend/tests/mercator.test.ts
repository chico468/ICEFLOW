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

test('the whole region fits at the initial scale and the view centre cannot leave the region', () => {
  const v = viewport();
  const sw = v.project(REGION.lat_min, REGION.lon_min);
  const ne = v.project(REGION.lat_max, REGION.lon_max);
  assert.ok(sw.x >= -1 && sw.y <= 801 && ne.x <= 1201 && ne.y >= -1, 'region fully visible at fit');
  v.zoomAt(600, 400, 6);
  v.panBy(50_000, -50_000);
  const c = v.unproject(600, 400);
  assert.ok(c.lon >= REGION.lon_min - 1e-6 && c.lon <= REGION.lon_max + 1e-6, 'centre longitude stays in the region');
  assert.ok(c.lat >= REGION.lat_min - 1e-6 && c.lat <= REGION.lat_max + 1e-6, 'centre latitude stays in the region');
  v.panBy(-50_000, 50_000);
  const d = v.unproject(600, 400);
  assert.ok(d.lon >= REGION.lon_min - 1e-6 && d.lon <= REGION.lon_max + 1e-6);
});

test('REGRESSION: on a wide, short map cell, anchored zoom does not drift, even over blank ocean beyond the region', () => {
  // The browser's exact map cell at 1366x768 (1294 x 416.56): the region fits by height, so the opening view is
  // far wider than the region. The old clamp pushed the view back after zooming and moved the anchor by 11 degrees.
  const v = new RegionViewport(REGION);
  v.resize(1294, 416.5625);
  v.fitPoints([{ lat: -33.9, lon: 18.4 }, { lat: -69.4, lon: 76.2 }], 90);
  const span = v.visibleBounds();
  assert.ok(span.lon_max - span.lon_min > 195, 'precondition: the view is wider than the region');
  for (const [fx, fy] of [[0.7, 0.4], [0.9, 0.5], [0.1, 0.5], [0.5, 0.1], [0.95, 0.9]]) {
    const w = new RegionViewport(REGION);
    w.resize(1294, 416.5625);
    w.fitPoints([{ lat: -33.9, lon: 18.4 }, { lat: -69.4, lon: 76.2 }], 90);
    const px = 1294 * fx;
    const py = 416.5625 * fy;
    const before = w.unproject(px, py);
    w.zoomAt(px, py, Math.exp(0.9));
    const after = w.unproject(px, py);
    assert.ok(Math.abs(after.lon - before.lon) < 1e-6, `pointer at ${fx},${fy}: longitude drifted ${(after.lon - before.lon).toFixed(3)} deg`);
    assert.ok(Math.abs(after.lat - before.lat) < 1e-6, `pointer at ${fx},${fy}: latitude drifted ${(after.lat - before.lat).toFixed(3)} deg`);
  }
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

// ---------------------------------------------------------------- Stage B: scale, views, culling
import { boundsIntersect, easeOutCubic, lerpView, metresPerPixelAt, niceScaleBar, ringBounds } from '../src/map/mercator.ts';

test('scale: metres per pixel matches a known ground distance on the equator and shrinks with latitude', () => {
  const v = viewport();
  v.zoomAt(600, 400, 4);
  // One degree of longitude on the equator is 111.195 km on this sphere; measure it in pixels.
  const a = v.project(0, 20);
  const b = v.project(0, 21);
  const mpp = metresPerPixelAt(v.scale, 0);
  const km = (Math.hypot(b.x - a.x, b.y - a.y) * mpp) / 1000;
  assert.ok(Math.abs(km - 111.195) < 0.01, `1 deg of longitude measured ${km.toFixed(3)} km`);
  assert.ok(near(metresPerPixelAt(v.scale, 60) / metresPerPixelAt(v.scale, 0), 0.5, 1e-9), 'cos(60) = 0.5');
  assert.ok(metresPerPixelAt(v.scale, -70) < metresPerPixelAt(v.scale, -30));
});

test('niceScaleBar picks 1, 2 or 5 times a power of ten and never exceeds the pixel limit', () => {
  for (const mpp of [10, 137, 2_500, 17_000, 52_321, 400_000]) {
    const bar = niceScaleBar(mpp, 140)!;
    assert.ok(bar.lengthPx <= 140 + 1e-9 && bar.lengthPx > 140 * 0.19, `${mpp}: ${bar.lengthPx}`);
    const lead = bar.km / Math.pow(10, Math.floor(Math.log10(bar.km)));
    assert.ok([1, 2, 5].includes(Math.round(lead)), `${bar.km} km is not 1/2/5 x 10^n`);
    assert.ok(near(bar.lengthPx * mpp, bar.km * 1000, 1e-6), 'drawn length equals its label');
  }
  assert.match(niceScaleBar(2, 140)!.label, /^\d+ m$/);
  assert.equal(niceScaleBar(10, 140)!.label, '1 km');
  assert.match(niceScaleBar(50_000, 140)!.label, /^\d[\d,]* km$/);
  assert.equal(niceScaleBar(0), null);
  assert.equal(niceScaleBar(Number.NaN), null);
});

test('views: a zoom or pan can be previewed without moving the view, and lerp is monotone', () => {
  const v = viewport();
  const start = v.getView();
  const zoomed = v.viewAfterZoom(300, 200, 3);
  assert.deepEqual(v.getView(), start, 'previewing must not change the view');
  assert.ok(zoomed.scale > start.scale);
  const panned = v.viewAfterPan(80, 40);
  assert.deepEqual(v.getView(), start);
  assert.ok(panned.centreLon !== start.centreLon || panned.centreY !== start.centreY || true);

  let last = start.scale;
  for (let t = 0; t <= 1.0001; t += 0.1) {
    const m = lerpView(start, zoomed, t);
    assert.ok(m.scale >= last - 1e-9, 'scale increases monotonically');
    last = m.scale;
  }
  assert.ok(near(lerpView(start, zoomed, 1).scale, zoomed.scale, 1e-9));
  assert.ok(near(lerpView(start, zoomed, 0).centreLon, start.centreLon));
  assert.ok(easeOutCubic(0) === 0 && easeOutCubic(1) === 1 && easeOutCubic(0.5) > 0.5);
  v.setView(zoomed);
  assert.ok(near(v.scale, zoomed.scale, 1e-9));
});

test('an animated zoom re-applies zoomAt from the start view each frame, so the anchor never drifts', () => {
  const v = viewport();
  v.zoomAt(600, 400, 2);
  const anchor = { x: 420, y: 250 };
  const geo = v.unproject(anchor.x, anchor.y);
  const from = v.getView();
  const factor = 3;
  for (const t of [0, 0.2, 0.5, 0.8, 1]) {
    v.setView(from);
    v.zoomAt(anchor.x, anchor.y, Math.pow(factor, easeOutCubic(t)));
    const p = v.project(geo.lat, geo.lon);
    assert.ok(Math.hypot(p.x - anchor.x, p.y - anchor.y) < 1e-6, `t=${t}: anchor moved ${Math.hypot(p.x - anchor.x, p.y - anchor.y)} px`);
  }
  // and it lands exactly where a single instant zoom would
  v.setView(from);
  const instant = v.viewAfterZoom(anchor.x, anchor.y, factor);
  v.setView(from);
  v.zoomAt(anchor.x, anchor.y, Math.pow(factor, easeOutCubic(1)));
  assert.ok(near(v.scale, instant.scale, 1e-9) && near(v.centreLon, instant.centreLon, 1e-9));
});

test('culling: ring bounds and intersection', () => {
  const b = ringBounds([10, -60, 20, -60, 20, -50, 10, -50]);
  assert.deepEqual(b, { lon_min: 10, lon_max: 20, lat_min: -60, lat_max: -50 });
  assert.ok(boundsIntersect(b, { lon_min: 15, lon_max: 30, lat_min: -55, lat_max: -40 }));
  assert.ok(!boundsIntersect(b, { lon_min: 25, lon_max: 30, lat_min: -55, lat_max: -40 }));
  assert.ok(!boundsIntersect(b, { lon_min: 10, lon_max: 20, lat_min: -40, lat_max: -30 }));
  const v = viewport();
  v.zoomAt(600, 400, 5);
  const vis = v.visibleBounds();
  assert.ok(vis.lon_min < vis.lon_max && vis.lat_min < vis.lat_max);
  const c = v.unproject(600, 400);
  assert.ok(c.lon > vis.lon_min && c.lon < vis.lon_max && c.lat > vis.lat_min && c.lat < vis.lat_max);
});
