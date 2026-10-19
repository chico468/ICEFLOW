/**
 * The flow layers' frame logic, with no React and no DOM beyond a 2D context: a controller that is handed
 * one animation frame at a time. The overlay component only wires it to requestAnimationFrame, which is what
 * makes the lifecycle testable (frame cap, idle arrows, coverage notices, pause and resume) without a browser.
 *
 * Imports carry explicit .ts extensions so Node's test runner can load this file directly.
 */
import {
  FLOW_KINDS,
  ParticleField,
  arrowLattice,
  arrowLength,
  insideGrid,
  isLandAt,
  lifeFraction,
  particleCountFor,
  sampleFlow,
  speedBucket,
  vectorArrow,
  viewCoverage,
  type FlowGrid,
  type FlowKind,
  type FlowStyle,
} from './flow.ts';

/** What the controller needs from a map viewport. The real Viewport satisfies it. */
export interface ViewLike {
  widthPx: number;
  heightPx: number;
  centreX: number;
  centreY: number;
  metresPerPixel: number;
  lonLatToScreen(lat: number, lon: number): { x: number; y: number };
  screenToLatLon(px: number, py: number): { lat: number; lon: number };
}

/** The slice of a canvas the controller sizes. */
export interface SizableCanvas {
  width: number;
  height: number;
  style: { width: string; height: string };
}

/** The 2D context calls used. Declared as the real type so the drawing code is unchanged. */
export type Ctx2D = CanvasRenderingContext2D;

const SEEDS: Record<FlowKind, number> = { wind: 11, current: 23 };
/**
 * Particle frames are capped at 60 a second. The cap exists for 120 and 144 Hz displays, which would otherwise
 * do twice the work for no visible gain. It is 60, not lower, because a cap below the refresh rate quantises:
 * a 40 fps cap on a 60 Hz display yields 30 fps, every other frame.
 */
export const FRAME_MS = 1000 / 60;

interface Layer {
  kind: FlowKind;
  grid: FlowGrid;
  particles: ParticleField;
}

export interface ControllerOptions {
  view: ViewLike;
  canvas: SizableCanvas;
  ctx: Ctx2D;
  windGrid: FlowGrid | null;
  currentGrid: FlowGrid | null;
  mode: FlowStyle;
  devicePixelRatio: () => number;
  /** Called only when the view moves into or out of the field's extent. */
  onOutside: (outside: boolean) => void;
}

export class FlowController {
  /** Counters for tests and diagnostics. */
  readonly stats = { frames: 0, draws: 0, steps: 0, skipped: 0 };

  private readonly o: ControllerOptions;
  private layers: Layer[] = [];
  private built = { w: 0, h: 0 };
  private sig = '';
  private sized = { w: 0, h: 0, dpr: 0 };
  private lastStep: number | null = null;
  private lastDraw = -Infinity;
  private drawnOnce = false;
  private outsideNow = false;
  private disposed = false;

  constructor(options: ControllerOptions) {
    this.o = options;
  }

  get particleCount(): number {
    return this.layers[0]?.particles.count ?? 0;
  }

  /** The particle layers, for tests. */
  get particleLayers(): readonly { kind: FlowKind; particles: ParticleField }[] {
    return this.layers;
  }

  get aliveCount(): number {
    let n = 0;
    for (const l of this.layers) for (let i = 0; i < l.particles.count; i += 1) n += l.particles.alive[i];
    return n;
  }

  /** Handle one animation frame. Returns what it did, for tests. */
  frame(now: number): 'drew' | 'skipped' | 'disposed' | 'no-size' {
    this.stats.frames += 1;
    if (this.disposed) return 'disposed';
    const { view: vp, canvas, ctx, windGrid, currentGrid, mode } = this.o;
    const w = vp.widthPx;
    const h = vp.heightPx;
    if (w < 2 || h < 2) return 'no-size';

    const nextSig = `${vp.centreX}|${vp.centreY}|${vp.metresPerPixel}|${w}|${h}`;
    const viewChanged = nextSig !== this.sig;
    // Arrows need a repaint only when something changed; particles are capped to 60 frames a second.
    if (mode === 'arrows') {
      if (this.drawnOnce && !viewChanged) {
        this.stats.skipped += 1;
        return 'skipped';
      }
    } else if (now - this.lastDraw < FRAME_MS - 2) {
      this.stats.skipped += 1;
      return 'skipped';
    }
    this.sig = nextSig;
    this.lastDraw = now;

    const dpr = this.o.devicePixelRatio();
    if (this.sized.w !== w || this.sized.h !== h || this.sized.dpr !== dpr) {
      canvas.width = Math.max(1, Math.round(w * dpr));
      canvas.height = Math.max(1, Math.round(h * dpr));
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
      this.sized = { w, h, dpr };
    }

    const primary = windGrid ?? currentGrid;
    if (viewChanged && primary) {
      const out = viewCoverage(primary, (x, y) => vp.screenToLatLon(x, y), w, h) === 0;
      if (out !== this.outsideNow) {
        this.outsideNow = out;
        this.o.onOutside(out);
      }
    }

    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
    ctx.clearRect(0, 0, w, h);

    if (mode === 'arrows') {
      if (windGrid) drawArrows(ctx, vp, 'wind', windGrid, w, h, 0);
      if (currentGrid) drawArrows(ctx, vp, 'current', currentGrid, w, h, windGrid ? 23 : 0);
      this.drawnOnce = true;
      this.stats.draws += 1;
      return 'drew';
    }

    if (this.layers.length === 0 || Math.abs(this.built.w * this.built.h - w * h) / Math.max(1, w * h) > 0.3) this.build(w, h);
    // The first frame after a start or resume has no previous step: use one nominal frame, never a long gap.
    const dt = this.lastStep === null ? FRAME_MS / 1000 : (now - this.lastStep) / 1000;
    this.lastStep = now;
    this.stepAll(dt, viewChanged);
    for (const l of this.layers) drawParticles(ctx, l);
    this.drawnOnce = true;
    this.stats.draws += 1;
    this.stats.steps += 1;
    return 'drew';
  }

  dispose(): void {
    this.disposed = true;
    this.layers = [];
  }

  private build(w: number, h: number): void {
    const { windGrid, currentGrid } = this.o;
    const count = particleCountFor(w, h);
    const next: Layer[] = [];
    if (windGrid) next.push({ kind: 'wind', grid: windGrid, particles: new ParticleField(FLOW_KINDS.wind, count, SEEDS.wind) });
    if (currentGrid)
      next.push({ kind: 'current', grid: currentGrid, particles: new ParticleField(FLOW_KINDS.current, count, SEEDS.current) });
    for (const l of next) l.particles.setGrid(l.grid);
    this.layers = next;
    this.built = { w, h };
  }

  private stepAll(dtSec: number, reproject: boolean): void {
    const vp = this.o.view;
    const w = vp.widthPx;
    const h = vp.heightPx;
    const project = (lat: number, lon: number): { x: number; y: number } => vp.lonLatToScreen(lat, lon);
    for (const l of this.layers) {
      const spawn = (): { lat: number; lon: number } | null => {
        for (let t = 0; t < 5; t += 1) {
          const ll = vp.screenToLatLon(l.particles.random() * w, l.particles.random() * h);
          if (insideGrid(l.grid, ll.lat, ll.lon)) return ll;
        }
        return null;
      };
      l.particles.step({ project, spawn, widthPx: w, heightPx: h, marginPx: 24, dtSec, reproject });
    }
  }
}

/** One layer's trails: a pale casing for contrast on any ground, then speed-coloured strokes, fading to the tail. */
export function drawParticles(ctx: CanvasRenderingContext2D, layer: Layer): void {
  const spec = FLOW_KINDS[layer.kind];
  const p = layer.particles;
  const K = p.trailLength;
  const buckets = spec.ramp.length;
  // How many trail points each particle shows: all while it lives, fewer as it dies.
  const shown = (i: number): number => {
    const n = p.trailCount[i];
    const f = lifeFraction(p.age[i], p.maxAge[i]);
    return f >= 1 ? n : Math.floor(n * f);
  };

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  ctx.strokeStyle = 'rgba(255,255,255,0.28)';
  ctx.lineWidth = spec.lineWidth + 1.4;
  ctx.beginPath();
  for (let i = 0; i < p.count; i += 1) {
    const n = shown(i);
    if (!p.alive[i] || n < 2) continue;
    const base = i * K;
    ctx.moveTo(p.trailX[base], p.trailY[base]);
    for (let k = 1; k < n; k += 1) ctx.lineTo(p.trailX[base + k], p.trailY[base + k]);
  }
  ctx.stroke();

  const tiers: [number, number, number][] = [
    [0, Math.floor(K / 3), 0.85],
    [Math.floor(K / 3), Math.floor((2 * K) / 3), 0.5],
    [Math.floor((2 * K) / 3), K - 1, 0.22],
  ];
  ctx.lineWidth = spec.lineWidth;
  for (let b = 0; b < buckets; b += 1) {
    const [r, g, bl] = spec.ramp[b];
    for (const [from, to, alpha] of tiers) {
      ctx.strokeStyle = `rgba(${r},${g},${bl},${alpha})`;
      ctx.beginPath();
      let any = false;
      for (let i = 0; i < p.count; i += 1) {
        const n = shown(i);
        if (!p.alive[i] || n < 2 || speedBucket(p.speed[i], spec.maxSpeed, buckets) !== b) continue;
        const end = Math.min(to, n - 1);
        if (from >= end) continue;
        const base = i * K;
        ctx.moveTo(p.trailX[base + from], p.trailY[base + from]);
        for (let k = from + 1; k <= end; k += 1) ctx.lineTo(p.trailX[base + k], p.trailY[base + k]);
        any = true;
      }
      if (any) ctx.stroke();
    }
  }
  ctx.restore();
}

// -------------------------------------------------------------------------------------- arrows

/**
 * Static arrows on a screen lattice. Each is the image of the cell's GEOGRAPHIC vector, so it points the way a
 * particle would move. Wind arrows have an open chevron head and current arrows a filled one, so the two are
 * told apart by shape as well as colour.
 */
export function drawArrows(
  ctx: CanvasRenderingContext2D,
  vp: ViewLike,
  kind: FlowKind,
  grid: FlowGrid,
  w: number,
  h: number,
  offsetPx: number,
): void {
  const spec = FLOW_KINDS[kind];
  const spacing = kind === 'wind' ? 46 : 52;
  const pts = arrowLattice(w, h, spacing, offsetPx);
  const project = (lat: number, lon: number): { x: number; y: number } => vp.lonLatToScreen(lat, lon);
  const out: [number, number] = [0, 0];

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';
  for (let i = 0; i < pts.length; i += 2) {
    const ll = vp.screenToLatLon(pts[i], pts[i + 1]);
    if (!Number.isFinite(ll.lat) || !insideGrid(grid, ll.lat, ll.lon) || !sampleFlow(grid, ll.lat, ll.lon, out)) continue;
    if (kind === 'current' && isLandAt(grid, ll.lat, ll.lon)) continue;
    const speed = Math.hypot(out[0], out[1]);
    const a = vectorArrow(project, ll.lat, ll.lon, out[0], out[1], arrowLength(speed, spec.maxSpeed));
    if (!a) continue;
    const [r, g, b] = spec.ramp[speedBucket(speed, spec.maxSpeed, spec.ramp.length)];
    const ang = Math.atan2(a.y1 - a.y0, a.x1 - a.x0);
    const head = kind === 'wind' ? 4.5 : 5.5;
    const wing = (sign: number): [number, number] => [
      a.x1 - head * Math.cos(ang + sign * 0.5),
      a.y1 - head * Math.sin(ang + sign * 0.5),
    ];
    const [lx, ly] = wing(1);
    const [rx, ry] = wing(-1);

    // casing
    ctx.strokeStyle = 'rgba(255,255,255,0.6)';
    ctx.lineWidth = spec.lineWidth + 2.2;
    ctx.beginPath();
    ctx.moveTo(a.x0, a.y0);
    ctx.lineTo(a.x1, a.y1);
    ctx.stroke();
    // shaft and head
    ctx.strokeStyle = `rgb(${r},${g},${b})`;
    ctx.fillStyle = `rgb(${r},${g},${b})`;
    ctx.lineWidth = spec.lineWidth + 0.4;
    ctx.beginPath();
    ctx.moveTo(a.x0, a.y0);
    ctx.lineTo(a.x1, a.y1);
    ctx.stroke();
    ctx.beginPath();
    if (kind === 'wind') {
      ctx.moveTo(lx, ly);
      ctx.lineTo(a.x1, a.y1);
      ctx.lineTo(rx, ry);
      ctx.stroke();
    } else {
      ctx.moveTo(a.x1, a.y1);
      ctx.lineTo(lx, ly);
      ctx.lineTo(rx, ry);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.restore();
}
