// Drives the flow layers' frame logic by hand, against a fake viewport that uses the REAL EPSG:3031
// projection in both directions. This is what stands in for a browser here: the frame cap, idle arrows,
// the gap after a pause, coverage notices and flow direction are all exercised for real.
import assert from 'node:assert/strict';
import { test } from 'node:test';
import { FRAME_MS, FlowController, type ViewLike } from '../src/map/FlowController.ts';
import { makeFlowGrid, particleCountFor, type FlowGrid } from '../src/map/flow.ts';
import { fromEpsg3031, toEpsg3031 } from '../src/map/projection.ts';

class FakeView implements ViewLike {
  widthPx = 1000;
  heightPx = 600;
  centreX: number;
  centreY: number;
  metresPerPixel = 9000;
  constructor(lat: number, lon: number) {
    const c = toEpsg3031(lat, lon);
    this.centreX = c.x;
    this.centreY = c.y;
  }
  lonLatToScreen(lat: number, lon: number) {
    const p = toEpsg3031(lat, lon);
    return { x: this.widthPx / 2 + (p.x - this.centreX) / this.metresPerPixel, y: this.heightPx / 2 - (p.y - this.centreY) / this.metresPerPixel };
  }
  screenToLatLon(px: number, py: number) {
    return fromEpsg3031(this.centreX + (px - this.widthPx / 2) * this.metresPerPixel, this.centreY - (py - this.heightPx / 2) * this.metresPerPixel);
  }
  moveTo(lat: number, lon: number) {
    const c = toEpsg3031(lat, lon);
    this.centreX = c.x;
    this.centreY = c.y;
  }
}

/** A circumpolar grid like the one the app requests: 78 S to 28 S, all longitudes, 1 x 2 degrees. */
function grid(u: number, v: number, land?: (lat: number) => number): FlowGrid {
  const lats: number[] = [];
  const lons: number[] = [];
  for (let la = -78; la <= -28; la += 1) lats.push(la);
  for (let lo = -180; lo <= 180; lo += 2) lons.push(lo);
  return makeFlowGrid(
    lats,
    lons,
    lats.map(() => lons.map(() => u)),
    lats.map(() => lons.map(() => v)),
    land ? lats.map((la) => lons.map(() => land(la))) : undefined,
  )!;
}

function recorder() {
  const calls: Record<string, number> = {};
  const ctx = new Proxy({}, {
    get: (_t, k: string) => (...a: unknown[]) => { calls[k] = (calls[k] ?? 0) + 1; void a; },
    set: () => true,
  }) as unknown as CanvasRenderingContext2D;
  return { ctx, calls };
}

const canvasStub = () => ({ width: 0, height: 0, style: { width: '', height: '' } });

function make(mode: 'animated' | 'arrows', view: FakeView, opts: { wind?: FlowGrid | null; current?: FlowGrid | null; dpr?: () => number; onOutside?: (o: boolean) => void } = {}) {
  const rec = recorder();
  const canvas = canvasStub();
  const controller = new FlowController({
    view,
    canvas,
    ctx: rec.ctx,
    windGrid: opts.wind === undefined ? grid(8, 0) : opts.wind,
    currentGrid: opts.current ?? null,
    mode,
    devicePixelRatio: opts.dpr ?? (() => 1),
    onOutside: opts.onOutside ?? (() => undefined),
  });
  return { controller, rec, canvas };
}

/** Feed frames at a given refresh rate for `ms` milliseconds, starting at t0. */
function run(controller: FlowController, ms: number, hz = 60, t0 = 1000): number {
  const step = 1000 / hz;
  let t = t0;
  for (; t < t0 + ms; t += step) controller.frame(t);
  return t;
}

test('particle frames are capped at 60 a second, and a 60 Hz display is not halved to 30', () => {
  for (const hz of [60, 120, 144]) {
    const { controller } = make('animated', new FakeView(-62, 60));
    run(controller, 1000, hz);
    assert.ok(controller.stats.draws >= 44 && controller.stats.draws <= 62, `${hz} Hz: ${controller.stats.draws} draws in 1 s`);
    assert.equal(controller.stats.steps, controller.stats.draws, 'every drawn frame advanced the particles exactly once');
  }
  assert.ok(Math.abs(FRAME_MS - 1000 / 60) < 1e-9);
});

test('particles start reliably: most are alive within half a second, and the count is restrained', () => {
  const { controller } = make('animated', new FakeView(-62, 60));
  run(controller, 500);
  assert.equal(controller.particleCount, particleCountFor(1000, 600));
  assert.ok(controller.particleCount <= 200 * 2);
  assert.ok(controller.aliveCount > controller.particleCount * 0.8, `alive ${controller.aliveCount}/${controller.particleCount}`);
});

test('pausing freezes the current frame and resuming advances without applying the pause gap', () => {
  const { controller, rec } = make('animated', new FakeView(-62, 60));
  run(controller, 500);
  const draws = controller.stats.draws;
  const steps = controller.stats.steps;
  const strokes = rec.calls.stroke ?? 0;
  const p = controller.particleLayers[0].particles;
  const before = p.lat[0];

  controller.setPaused(true);
  assert.equal(controller.frame(600_000), 'skipped');
  assert.equal(controller.stats.draws, draws);
  assert.equal(controller.stats.steps, steps);
  assert.equal(rec.calls.stroke ?? 0, strokes, 'the visible canvas is untouched while paused');
  assert.equal(p.lat[0], before);

  controller.setPaused(false);
  assert.equal(controller.frame(600_100), 'drew');
  assert.equal(controller.stats.steps, steps + 1);
  assert.equal(p.lat[0], before, 'one nominal step after resume does not move the particle latitude');
});

test('paused trails stay attached to the map when the view moves, without advancing particles', () => {
  const view = new FakeView(-62, 60);
  const { controller } = make('animated', view);
  run(controller, 500);
  const p = controller.particleLayers[0].particles;
  const beforeLat = p.lat[0];
  const beforeX = p.trailX[0];
  const steps = controller.stats.steps;
  controller.setPaused(true);
  view.moveTo(-61, 60);
  assert.equal(controller.frame(600_000), 'drew');
  assert.equal(controller.stats.steps, steps);
  assert.equal(p.lat[0], beforeLat);
  assert.notEqual(p.trailX[0], beforeX, 'the stored trail is reprojected onto the new map view');
});

test('particles follow the field: a purely eastward wind leaves every trail on a line of constant latitude', () => {
  const { controller } = make('animated', new FakeView(-62, 60));
  run(controller, 1500);
  const p = controller.particleLayers[0].particles;
  let checked = 0;
  for (let i = 0; i < p.count; i += 1) {
    if (!p.alive[i] || p.trailCount[i] < 4) continue;
    const base = i * p.trailLength;
    const dLat = Math.abs(p.trailLat[base] - p.trailLat[base + p.trailCount[i] - 1]);
    const dLon = p.trailLon[base] - p.trailLon[base + p.trailCount[i] - 1];
    assert.ok(dLat < 0.01, `particle ${i} drifted ${dLat} deg in latitude`);
    assert.ok(dLon > 0, 'and moved EAST along that line');
    checked += 1;
  }
  assert.ok(checked > 50, `only ${checked} particles had a trail to check`);
});

test('arrow mode draws once, then idles: no animation work while nothing changes', () => {
  const view = new FakeView(-62, 60);
  const { controller, rec } = make('arrows', view);
  assert.equal(controller.frame(1000), 'drew');
  const strokes = rec.calls.stroke ?? 0;
  assert.ok(strokes > 100, `arrows were drawn (${strokes} strokes)`);
  for (let t = 1016; t < 3000; t += 16) assert.equal(controller.frame(t), 'skipped');
  assert.equal(controller.stats.draws, 1);
  assert.equal(rec.calls.stroke, strokes, 'an idle frame touches the canvas not at all');
  view.moveTo(-60, 70); // the view moves
  assert.equal(controller.frame(3100), 'drew');
  assert.equal(controller.stats.draws, 2);
  assert.equal(controller.stats.steps, 0, 'arrow mode never advances particles');
});

test('arrows are skipped where the field says there is land, for currents only', () => {
  const landBelow = (lat: number) => (lat < -70 ? 0 : 0.4); // hs == 0 south of 70 S: not ocean
  const view = new FakeView(-76, 60);
  view.metresPerPixel = 4000;
  const cur = make('arrows', view, { wind: null, current: grid(0.2, 0, landBelow) });
  cur.controller.frame(1000);
  const wind = make('arrows', view, { wind: grid(8, 0, landBelow), current: null });
  wind.controller.frame(1000);
  assert.ok((wind.rec.calls.stroke ?? 0) > (cur.rec.calls.stroke ?? 0) * 1.5, 'wind blows over the continent; current does not flow over it');
});

test('after a pause the first frame uses one nominal step, not the whole gap, so nothing teleports', () => {
  const view = new FakeView(-62, 60);
  const first = make('animated', view);
  run(first.controller, 500);
  first.controller.dispose();
  assert.equal(first.controller.frame(99_999), 'disposed');
  assert.equal(first.controller.stats.draws > 0, true);

  // Resume 10 minutes later with a brand-new controller, as the overlay does.
  const resumed = make('animated', view);
  resumed.controller.frame(600_000);
  resumed.controller.frame(600_000 + FRAME_MS);
  resumed.controller.frame(600_000 + 2 * FRAME_MS);
  const p = resumed.controller.particleLayers[0].particles;
  let maxStep = 0;
  for (let i = 0; i < p.count; i += 1) {
    if (!p.alive[i] || p.trailCount[i] < 2) continue;
    const b = i * p.trailLength;
    maxStep = Math.max(maxStep, Math.hypot(p.trailX[b] - p.trailX[b + 1], p.trailY[b] - p.trailY[b + 1]));
  }
  assert.ok(maxStep > 0, 'particles moved');
  assert.ok(maxStep < 4, `largest single step ${maxStep.toFixed(2)} px: a 10-minute gap was NOT applied as one step`);
});

test('coverage notice fires once when the view leaves the field, once when it returns, and never repeats', () => {
  const view = new FakeView(-60, 60);
  const events: boolean[] = [];
  const { controller } = make('animated', view, { onOutside: (o) => events.push(o) });
  let t = run(controller, 200);
  assert.deepEqual(events, [], 'inside the field: no notice');
  view.metresPerPixel = 2000; // a view ~1200 km tall (about 11 degrees of latitude)...
  view.moveTo(-12, 60); // ...centred at 12 S: wholly north of the field's 28 S edge
  t = run(controller, 300, 60, t);
  assert.deepEqual(events, [true], 'one notice on leaving');
  t = run(controller, 300, 60, t);
  assert.deepEqual(events, [true], 'it does not repeat while the view stays outside');
  view.metresPerPixel = 9000;
  view.moveTo(-60, 60);
  run(controller, 200, 60, t);
  assert.deepEqual(events, [true, false], 'cleared on return');
});

test('outside the field nothing is spawned, so nothing moves', () => {
  const view = new FakeView(-12, 60);
  view.metresPerPixel = 2000; // wholly north of the field's edge
  const { controller } = make('animated', view);
  run(controller, 800);
  assert.equal(controller.aliveCount, 0);
});

test('a missing field draws nothing and never throws', () => {
  const view = new FakeView(-62, 60);
  const { controller, rec } = make('animated', view, { wind: null, current: null });
  run(controller, 300);
  assert.equal(controller.aliveCount, 0);
  assert.equal(rec.calls.stroke ?? 0, 0);
});

test('a zero-size or hidden chart is a no-op, and a size or pixel-ratio change resizes the canvas backing store', () => {
  const view = new FakeView(-62, 60);
  const { controller, canvas } = make('animated', view);
  view.widthPx = 0;
  assert.equal(controller.frame(1000), 'no-size');
  view.widthPx = 1000;
  controller.frame(1100);
  assert.equal(canvas.width, 1000);
  let dpr = 2;
  const hi = make('animated', view, { dpr: () => dpr });
  hi.controller.frame(1000);
  assert.equal(hi.canvas.width, 2000);
  assert.equal(hi.canvas.style.width, '1000px');
  dpr = 1;
  hi.controller.frame(1100);
  assert.equal(hi.canvas.width, 1000, 'a monitor change is picked up');
});

test('zoom and pan: particle trails are rebuilt for the new view, not left where they were', () => {
  const view = new FakeView(-62, 60);
  const { controller } = make('animated', view);
  let t = run(controller, 600);
  view.metresPerPixel = 4500; // zoom in 2x
  controller.frame(t + 30);
  const p = controller.particleLayers[0].particles;
  let checked = 0;
  for (let i = 0; i < p.count; i += 1) {
    if (!p.alive[i] || p.trailCount[i] < 3) continue;
    const b = i * p.trailLength;
    const proj = view.lonLatToScreen(p.trailLat[b + 1], p.trailLon[b + 1]);
    assert.ok(Math.hypot(proj.x - p.trailX[b + 1], proj.y - p.trailY[b + 1]) < 0.5, 'screen trail matches the new projection');
    checked += 1;
  }
  assert.ok(checked > 20);
  t = run(controller, 300, 60, t + 60);
  assert.ok(controller.aliveCount > 0);
});
