/**
 * Wind and ocean-current layers, drawn on their own canvas above the chart, as moving particles or as
 * static arrows.
 *
 * WHY A SEPARATE CANVAS
 * The chart canvas repaints every ice cell as a projected quad whenever it is dirty. Animating particles
 * through that loop would repaint the whole raster dozens of times a second. This overlay has its own context
 * and its own loop, so the chart keeps idling when nothing changes.
 *
 * ONE LIFECYCLE
 * A single requestAnimationFrame loop exists only while all of these hold: a flow layer is on, its field has
 * arrived, the screen (and chart view) is the one on display, and the browser tab is visible. If any stops
 * holding, the effect cleans up and the frame is cancelled; when it holds again the effect re-runs from a
 * clean state. Unmounting cancels the frame too. Particle frames are capped at 60 per second.
 *
 * TWO WAYS TO DRAW THE SAME VECTORS
 *   animated   particles that follow the field, with short trails that dissolve at the end of their life
 *   arrows     a regular lattice of arrows whose length is relative speed
 * Arrows are used when the system asks for reduced motion (stated on screen, not silently) or when the user
 * chooses them. Arrow mode runs no animation: it redraws only when the view, the data or the layers change.
 *
 * WHAT IT SHOWS, AND WHAT IT SAYS WHEN IT CANNOT
 * Only vectors the service returned in /env/field, interpolated bilinearly. Those fields are simulated; the
 * legend carries that label. Nothing moves unless a field is present. A notice explains each case where nothing
 * is drawn: loading, failed, no data, or the view lying outside the field's extent.
 */
import { useEffect, useMemo, useRef, useState } from 'react';
import type { EnvField } from '../api/types';
import { useScreenActive } from '../components/screenActive';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { coverageText, makeFlowGrid, type FlowStyle } from './flow';
import { FlowController } from './FlowController';
import type { MapEngine } from './MapEngine';

interface Props {
  engine: MapEngine;
  field: EnvField | null;
  wind: boolean;
  current: boolean;
  style: FlowStyle;
  loading: boolean;
  error: string | null;
}

export function FlowOverlay({ engine, field, wind, current, style, loading, error }: Props): JSX.Element | null {
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const screenActive = useScreenActive();
  const tabVisible = useTabVisible();
  const reduced = useReducedMotion();
  const mode: FlowStyle = reduced ? 'arrows' : style;
  const [outside, setOutside] = useState(false);

  // A failing request disables the layers even if an earlier field is still cached: the notice says nothing
  // is animated, so nothing may be. Stale vectors must not keep moving behind an error message.
  const usable = error ? null : field;
  const grids = useMemo(
    () => ({
      wind: usable ? makeFlowGrid(usable.lats, usable.lons, usable.u10, usable.v10) : null,
      current: usable
        ? makeFlowGrid(usable.lats, usable.lons, usable.current_u, usable.current_v, usable.sig_wave_height_m)
        : null,
    }),
    [usable],
  );

  const windGrid = wind ? grids.wind : null;
  const currentGrid = current ? grids.current : null;
  const anyLayer = wind || current;
  const haveData = windGrid !== null || currentGrid !== null;
  const run = screenActive && tabVisible && haveData;
  const extent = windGrid ?? currentGrid;

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

    const controller = new FlowController({
      view: engine.viewport,
      canvas,
      ctx,
      windGrid,
      currentGrid,
      mode,
      devicePixelRatio: () => window.devicePixelRatio || 1,
      onOutside: setOutside,
    });
    let raf = 0;
    const loop = (now: number): void => {
      raf = requestAnimationFrame(loop);
      controller.frame(now);
    };
    raf = requestAnimationFrame(loop);
    return () => {
      cancelAnimationFrame(raf);
      controller.dispose();
    };
  }, [engine, run, windGrid, currentGrid, mode]);

  // Clear any stale 'outside' notice when the layers or data go away.
  useEffect(() => {
    if (!run) setOutside(false);
  }, [run]);

  if (!anyLayer) return null;

  let notice: { text: string; alert?: boolean } | null = null;
  if (error) notice = { text: `Wind and current data unavailable: ${error}. Nothing is shown or animated.`, alert: true };
  else if (loading && !field) notice = { text: 'Loading wind and current…' };
  else if (!field || !haveData) notice = { text: 'No wind or current data for this time. Nothing is shown.' };
  else if (outside && extent) notice = { text: `This view is outside the flow field (${coverageText(extent)}). Pan back to see vectors.` };
  else if (reduced) notice = { text: 'Reduced motion is on: showing static vectors instead of moving particles.' };

  return (
    <>
      <canvas ref={canvasRef} className="pointer-events-none absolute inset-0" aria-hidden="true" data-testid="flow-overlay" />
      {notice && (
        <div
          role={notice.alert ? 'alert' : 'status'}
          className="float pointer-events-none absolute left-1/2 top-3 z-10 max-w-[min(520px,46%)] -translate-x-1/2 px-3 py-1.5 text-center text-2xs text-ink-2"
        >
          {notice.text}
        </div>
      )}
    </>
  );
}

// ------------------------------------------------------------------------------------ particles

function useTabVisible(): boolean {
  const [visible, setVisible] = useState(() => !document.hidden);
  useEffect(() => {
    const on = (): void => setVisible(!document.hidden);
    document.addEventListener('visibilitychange', on);
    return () => document.removeEventListener('visibilitychange', on);
  }, []);
  return visible;
}
