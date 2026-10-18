/**
 * Animated wind and ocean-current particles, drawn on their own canvas above the chart.
 *
 * WHY A SEPARATE CANVAS
 * The chart canvas repaints every ice cell as a projected quad whenever it is dirty. Animating
 * particles through that loop would repaint the whole raster sixty times a second. This overlay has
 * its own context and its own loop, so the chart keeps its dirty-flag behaviour and idles at zero cost.
 *
 * WHAT IT COSTS, AND WHEN IT STOPS
 * The loop runs only while (a) a flow layer is switched on, (b) the field has arrived, (c) the screen
 * is the one on display, and (d) the browser tab is visible. Any of those going false cancels the
 * animation frame. Unmounting cancels it and removes the listeners it added. Users who ask the
 * system for reduced motion get a still picture of the flow instead of an animation.
 *
 * WHAT IT SHOWS
 * Only vectors the service returned in /env/field, interpolated bilinearly. Those fields are
 * synthetic today; the legend reads the response's own `is_synthetic` flag to say so.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { EnvField } from '../api/types';
import { useScreenActive } from '../components/screenActive';
import {
  FLOW_KINDS,
  ParticleField,
  insideGrid,
  makeFlowGrid,
  particleCountFor,
  speedBucket,
  type FlowGrid,
  type FlowKind,
} from './flow';
import type { MapEngine } from './MapEngine';

interface Props {
  engine: MapEngine;
  field: EnvField | null;
  wind: boolean;
  current: boolean;
}

interface Layer {
  kind: FlowKind;
  grid: FlowGrid;
  particles: ParticleField;
}

const SEEDS: Record<FlowKind, number> = { wind: 11, current: 23 };

export function FlowOverlay({ engine, field, wind, current }: Props): JSX.Element {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const screenActive = useScreenActive();
  const tabVisible = useTabVisible();
  const reducedMotion = useReducedMotion();

  const grids = useMemo(
    () => ({
      wind: field ? makeFlowGrid(field.lats, field.lons, field.u10, field.v10) : null,
      current: field
        ? makeFlowGrid(field.lats, field.lons, field.current_u, field.current_v, field.sig_wave_height_m)
        : null,
    }),
    [field],
  );

  const windGrid = wind ? grids.wind : null;
  const currentGrid = current ? grids.current : null;
  const run = screenActive && tabVisible && (windGrid !== null || currentGrid !== null);

  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const ctx = canvas.getContext('2d');
    if (!ctx) return undefined;
    if (!run) {
      ctx.setTransform(1, 0, 0, 1, 0, 0);
      ctx.clearRect(0, 0, canvas.width, canvas.height);
      return undefined;
    }

    const vp = engine.viewport;
    let layers: Layer[] = [];
    let built = { w: 0, h: 0 };
    let sig = '';
    let sized = { w: 0, h: 0, dpr: 0 };
    let last = performance.now();
    let stillDrawn = false;
    let raf = 0;

    const build = (w: number, h: number): void => {
      const count = particleCountFor(w, h);
      const next: Layer[] = [];
      if (windGrid) next.push({ kind: 'wind', grid: windGrid, particles: new ParticleField(FLOW_KINDS.wind, count, SEEDS.wind) });
      if (currentGrid)
        next.push({ kind: 'current', grid: currentGrid, particles: new ParticleField(FLOW_KINDS.current, count, SEEDS.current) });
      for (const l of next) l.particles.setGrid(l.grid);
      layers = next;
      built = { w, h };
      stillDrawn = false;
    };

    const stepAll = (dtSec: number, reproject: boolean): void => {
      const w = vp.widthPx;
      const h = vp.heightPx;
      const project = (lat: number, lon: number): { x: number; y: number } => vp.lonLatToScreen(lat, lon);
      for (const l of layers) {
        const spawn = (): { lat: number; lon: number } | null => {
          for (let t = 0; t < 5; t += 1) {
            const ll = vp.screenToLatLon(l.particles.random() * w, l.particles.random() * h);
            if (insideGrid(l.grid, ll.lat, ll.lon)) return ll;
          }
          return null;
        };
        l.particles.step({ project, spawn, widthPx: w, heightPx: h, marginPx: 24, dtSec, reproject });
      }
    };

    const frame = (now: number): void => {
      raf = requestAnimationFrame(frame);
      const w = vp.widthPx;
      const h = vp.heightPx;
      if (w < 2 || h < 2) return;

      const dpr = window.devicePixelRatio || 1;
      if (sized.w !== w || sized.h !== h || sized.dpr !== dpr) {
        canvas.width = Math.max(1, Math.round(w * dpr));
        canvas.height = Math.max(1, Math.round(h * dpr));
        canvas.style.width = `${w}px`;
        canvas.style.height = `${h}px`;
        sized = { w, h, dpr };
      }
      // Rebuild when the canvas changes size by enough to change the sensible particle count.
      if (layers.length === 0 || Math.abs(built.w * built.h - w * h) / Math.max(1, w * h) > 0.3) build(w, h);

      const nextSig = `${vp.centreX}|${vp.centreY}|${vp.metresPerPixel}|${w}|${h}`;
      const viewChanged = nextSig !== sig;
      sig = nextSig;
      const dt = (now - last) / 1000;
      last = now;

      if (reducedMotion) {
        // A still picture: settle the particles once, draw, and redraw only if the view moves.
        if (stillDrawn && !viewChanged) return;
        build(w, h);
        for (let i = 0; i < 40; i += 1) stepAll(1 / 30, i === 0);
        stillDrawn = true;
      } else {
        stepAll(dt, viewChanged);
      }

      ctx.setTransform(dpr, 0, 0, dpr, 0, 0);
      ctx.clearRect(0, 0, w, h);
      for (const l of layers) drawLayer(ctx, l);
    };

    raf = requestAnimationFrame(frame);
    return () => {
      cancelAnimationFrame(raf);
    };
  }, [engine, run, windGrid, currentGrid, reducedMotion]);

  return (
    <canvas
      ref={canvasRef}
      className="pointer-events-none absolute inset-0"
      aria-hidden="true"
      data-testid="flow-overlay"
    />
  );
}

/** Draw one layer's trails: a pale casing for contrast on any ground, then speed-coloured strokes. */
function drawLayer(ctx: CanvasRenderingContext2D, layer: Layer): void {
  const spec = FLOW_KINDS[layer.kind];
  const p = layer.particles;
  const K = p.trailLength;
  const buckets = spec.ramp.length;

  ctx.save();
  ctx.lineCap = 'round';
  ctx.lineJoin = 'round';

  // Casing, one path for the whole layer.
  ctx.strokeStyle = 'rgba(255,255,255,0.32)';
  ctx.lineWidth = spec.lineWidth + 1.8;
  ctx.beginPath();
  for (let i = 0; i < p.count; i += 1) {
    const n = p.trailCount[i];
    if (!p.alive[i] || n < 2) continue;
    const base = i * K;
    ctx.moveTo(p.trailX[base], p.trailY[base]);
    for (let k = 1; k < n; k += 1) ctx.lineTo(p.trailX[base + k], p.trailY[base + k]);
  }
  ctx.stroke();

  // Colour by speed bucket, fading toward the tail in three tiers.
  const tiers: [number, number, number][] = [
    [0, Math.floor(K / 3), 0.95],
    [Math.floor(K / 3), Math.floor((2 * K) / 3), 0.55],
    [Math.floor((2 * K) / 3), K - 1, 0.25],
  ];
  ctx.lineWidth = spec.lineWidth;
  for (let b = 0; b < buckets; b += 1) {
    const [r, g, bl] = spec.ramp[b];
    for (const [from, to, alpha] of tiers) {
      ctx.strokeStyle = `rgba(${r},${g},${bl},${alpha})`;
      ctx.beginPath();
      let any = false;
      for (let i = 0; i < p.count; i += 1) {
        const n = p.trailCount[i];
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

function useTabVisible(): boolean {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const on = (): void => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', on);
    return () => document.removeEventListener('visibilitychange', on);
  }, []);
  return visible;
}

function useReducedMotion(): boolean {
  const query = '(prefers-reduced-motion: reduce)';
  const [reduced, setReduced] = useState(() => window.matchMedia?.(query).matches ?? false);
  useEffect(() => {
    const mq = window.matchMedia?.(query);
    if (!mq) return undefined;
    const on = (): void => setReduced(mq.matches);
    mq.addEventListener('change', on);
    return () => mq.removeEventListener('change', on);
  }, []);
  return reduced;
}
