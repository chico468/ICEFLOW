/**
 * The React surface over MapEngine: sizing, pointer handling and the hover tooltip.
 *
 * All interaction mutates the viewport in place and calls invalidate(), so panning and
 * zooming never round-trip through React state. Only the tooltip text is React state,
 * and it is throttled to animation frames.
 */
import { useCallback, useEffect, useMemo, useRef, useState } from 'react';
import { Crosshair, Maximize2, Minus, Plus } from 'lucide-react';
import { MapEngine, type MapScene } from './MapEngine';
import type { LatLon } from './projection';
import { useStageInsets } from '../components/stageInsets';

export interface MapCanvasHandle {
  fitTo(points: { lat: number; lon: number }[]): void;
  engine: MapEngine;
}

interface Props {
  scene: MapScene;
  onClickPoint?: (ll: LatLon) => void;
  /** Coordinates the fit-to button should frame. */
  fitTargets?: { lat: number; lon: number }[];
  onReady?: (handle: MapCanvasHandle) => void;
  className?: string;
  showControls?: boolean;
}

export function MapCanvas({
  scene,
  onClickPoint,
  fitTargets,
  onReady,
  className,
  showControls = true,
}: Props): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const engineRef = useRef<MapEngine>();
  if (!engineRef.current) engineRef.current = new MapEngine();
  const engine = engineRef.current;
  const insets = useStageInsets();

  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const [cursor, setCursor] = useState<LatLon | null>(null);
  const [tooltipPos, setTooltipPos] = useState<{ x: number; y: number } | null>(null);

  // --- attach and size ---
  useEffect(() => {
    const canvas = canvasRef.current;
    const host = hostRef.current;
    if (!canvas || !host) return;
    engine.attach(canvas);

    const apply = (): void => {
      const rect = host.getBoundingClientRect();
      // Refuse to size the backing store from a degenerate measurement. A hidden or
      // not-yet-laid-out host reports zero, and committing that leaves a blank chart that no
      // later resize necessarily corrects, because ResizeObserver does not fire when an element
      // merely becomes visible again.
      if (rect.width < 2 || rect.height < 2) return;
      engine.resize(rect.width, rect.height, window.devicePixelRatio || 1);
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(host);
    window.addEventListener('resize', apply);
    return () => {
      ro.disconnect();
      window.removeEventListener('resize', apply);
      engine.detach();
    };
  }, [engine]);

  useEffect(() => {
    engine.setScene(scene);
  }, [engine, scene]);

  const fitTo = useCallback(
    (points: { lat: number; lon: number }[]) => {
      if (points.length === 0) return;
      engine.viewport.fitLatLon(points, 70, insets);
      engine.invalidate();
    },
    [engine, insets],
  );

  // Keep the scale bar clear of floating panels.
  useEffect(() => {
    engine.viewport.insetLeft = insets.left;
    engine.viewport.insetBottom = insets.bottom;
    engine.invalidate();
  }, [engine, insets.left, insets.bottom]);

  const handle = useMemo<MapCanvasHandle>(() => ({ fitTo, engine }), [fitTo, engine]);
  useEffect(() => {
    onReady?.(handle);
  }, [handle, onReady]);

  // Frame the route the first time one appears, then leave the operator in control.
  const framedRef = useRef(false);
  useEffect(() => {
    if (framedRef.current) return;
    if (!fitTargets || fitTargets.length < 2) return;
    framedRef.current = true;
    fitTo(fitTargets);
  }, [fitTargets, fitTo]);

  // --- interactions ---
  const onWheel = useCallback(
    (e: React.WheelEvent<HTMLCanvasElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const factor = Math.exp(e.deltaY * 0.0016);
      engine.viewport.zoomAbout(e.clientX - rect.left, e.clientY - rect.top, factor);
      engine.invalidate();
    },
    [engine],
  );

  const onPointerDown = useCallback((e: React.PointerEvent<HTMLCanvasElement>) => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY, moved: false };
  }, []);

  const onPointerMove = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const rect = e.currentTarget.getBoundingClientRect();
      const px = e.clientX - rect.left;
      const py = e.clientY - rect.top;
      const drag = dragRef.current;
      if (drag) {
        const dx = e.clientX - drag.x;
        const dy = e.clientY - drag.y;
        if (Math.abs(dx) + Math.abs(dy) > 2) drag.moved = true;
        engine.viewport.panPixels(dx, dy);
        engine.invalidate();
        drag.x = e.clientX;
        drag.y = e.clientY;
      }
      setCursor(engine.viewport.screenToLatLon(px, py));
      setTooltipPos({ x: px, y: py });
    },
    [engine],
  );

  const onPointerUp = useCallback(
    (e: React.PointerEvent<HTMLCanvasElement>) => {
      const drag = dragRef.current;
      dragRef.current = null;
      if (drag && !drag.moved && onClickPoint) {
        const rect = e.currentTarget.getBoundingClientRect();
        onClickPoint(engine.viewport.screenToLatLon(e.clientX - rect.left, e.clientY - rect.top));
      }
    },
    [engine, onClickPoint],
  );

  const zoomBy = useCallback(
    (factor: number) => {
      engine.viewport.zoomAbout(engine.viewport.widthPx / 2, engine.viewport.heightPx / 2, factor);
      engine.invalidate();
    },
    [engine],
  );

  return (
    // h-full w-full is load-bearing, not decoration. The canvas inside is absolutely positioned,
    // so it contributes nothing to this element's layout height; without an explicit height the
    // host collapses to zero, the backing store is sized 1 px tall, and the chart renders blank
    // on every screen while the surrounding panel still looks perfectly correct.
    <div ref={hostRef} className={`relative h-full w-full overflow-hidden ${className ?? ''}`}>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 touch-none select-none"
        style={{ cursor: dragRef.current ? 'grabbing' : 'crosshair' }}
        onWheel={onWheel}
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={onPointerUp}
        onPointerLeave={() => {
          dragRef.current = null;
          setCursor(null);
          setTooltipPos(null);
        }}
      />

      {cursor && tooltipPos && (
        <div
          className="pointer-events-none absolute z-10 rounded border border-hair bg-ground/90 px-2 py-1 num text-2xs text-ink-2"
          style={{
            left: Math.min(tooltipPos.x + 14, (hostRef.current?.clientWidth ?? 400) - 150),
            top: tooltipPos.y + 14,
          }}
        >
          {formatLat(cursor.lat)} &nbsp; {formatLon(cursor.lon)}
        </div>
      )}

      {showControls && (
        <div
          className="absolute z-10 flex flex-col gap-1.5"
          style={{ top: Math.max(12, insets.top), right: insets.right + 16 }}
        >
          <button className="btn-icon" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(1 / 1.4)}>
            <Plus size={16} />
          </button>
          <button className="btn-icon" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1.4)}>
            <Minus size={16} />
          </button>
          <button
            className="btn-icon"
            title="Fit to route"
            aria-label="Fit to route"
            onClick={() => fitTargets && fitTo(fitTargets)}
            disabled={!fitTargets || fitTargets.length < 2}
          >
            <Maximize2 size={16} />
          </button>
          <button
            className="btn-icon"
            title="Frame the Antarctic sector"
            aria-label="Frame the Antarctic sector"
            onClick={() =>
              fitTo([
                { lat: -78, lon: -30 },
                { lat: -78, lon: 120 },
                { lat: -45, lon: -30 },
                { lat: -45, lon: 120 },
              ])
            }
          >
            <Crosshair size={16} />
          </button>
        </div>
      )}
    </div>
  );
}

export function formatLat(lat: number): string {
  const hemi = lat < 0 ? 'S' : 'N';
  const a = Math.abs(lat);
  const deg = Math.floor(a);
  const min = (a - deg) * 60;
  return `${deg.toString().padStart(2, '0')}° ${min.toFixed(1).padStart(4, '0')}' ${hemi}`;
}

export function formatLon(lon: number): string {
  const hemi = lon < 0 ? 'W' : 'E';
  const a = Math.abs(lon);
  const deg = Math.floor(a);
  const min = (a - deg) * 60;
  return `${deg.toString().padStart(3, '0')}° ${min.toFixed(1).padStart(4, '0')}' ${hemi}`;
}
