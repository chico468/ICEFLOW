/**
 * Regional context map: the voyage region in Mercator, drawn on its own canvas.
 *
 * WHAT IT IS FOR
 * The polar chart is the navigation chart and cannot show where the ports are relative to Africa,
 * India or Australia. This map answers "where is this voyage on the planet?". It draws the SAME routes,
 * vessel, ports and stations the polar chart draws, from the same scene, so the two cannot disagree, and it
 * outlines the part of the world the polar chart is currently showing.
 *
 * WHAT IT IS NOT
 * Land comes from Natural Earth, simplified to about 4 km (scripts/build_regional_context.py). It is
 * drawing data. It is never used for the land mask, coastal clearance or routing, and the map says
 * "not for navigation" on its face. When that file has not been built the map says so and still draws
 * the graticule, ports, stations and route, rather than showing a blank rectangle.
 *
 * COST
 * Nothing animates here. It paints once per change (pan, zoom, new data, becoming visible), coalesced
 * on one animation frame, and the frame is cancelled on unmount.
 */
import { useCallback, useEffect, useMemo, useRef } from 'react';
import { Maximize2, Minus, Plus } from 'lucide-react';
import { useRegionalContext } from '../api/queries';
import { useStageInsets } from '../components/stageInsets';
import type { MapEngine, MapScene } from './MapEngine';
import { RegionViewport, graticuleStep, splitAtAntimeridian, viewOutline, type RegionBounds } from './mercator';
import { MAP_COLORS } from './palette';

const DEFAULT_REGION: RegionBounds = { lon_min: -30, lon_max: 165, lat_min: -75, lat_max: 40 };
const FONT = '"Avenir Next", system-ui, sans-serif';

interface Props {
  scene: MapScene;
  /** False while another view is on display: the map then does no work at all. */
  visible: boolean;
  /** The polar chart's engine, read (never written) to outline its current view. */
  polarEngine: MapEngine | null;
  originId: string;
  destinationId: string;
}

export function RegionalMap({ scene, visible, polarEngine, originId, destinationId }: Props): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const insets = useStageInsets();
  const context = useRegionalContext();
  const data = context.data;

  const region = data?.region ?? DEFAULT_REGION;
  const vp = useMemo(
    () => new RegionViewport(region),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [region.lon_min, region.lon_max, region.lat_min, region.lat_max],
  );

  const rafRef = useRef(0);
  const dragRef = useRef<{ x: number; y: number } | null>(null);
  const fittedKeyRef = useRef<string>('');

  const routePoints = useMemo(
    () => scene.optimisedRoute.map((w) => ({ lat: w.latitude, lon: w.longitude })),
    [scene.optimisedRoute],
  );
  const routeKey = routePoints.length
    ? `${routePoints[0].lat},${routePoints[0].lon}|${routePoints[routePoints.length - 1].lat},${routePoints[routePoints.length - 1].lon}|${routePoints.length}`
    : 'none';

  // The latest props, read by the painter without re-creating it on every render.
  const latest = useRef({ scene, data, originId, destinationId, polarEngine, visible });
  latest.current = { scene, data, originId, destinationId, polarEngine, visible };

  const paint = useCallback((): void => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { scene: sc, data: d, originId: oid, destinationId: did, polarEngine: pe, visible: vis } = latest.current;
    if (!vis || vp.widthPx < 2 || vp.heightPx < 2) return;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    const dpr = window.devicePixelRatio || 1;
    const w = vp.widthPx;
    const h = vp.heightPx;
    if (canvas.width !== Math.round(w * dpr) || canvas.height !== Math.round(h * dpr)) {
      canvas.width = Math.round(w * dpr);
      canvas.height = Math.round(h * dpr);
      canvas.style.width = `${w}px`;
      canvas.style.height = `${h}px`;
    }
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0);

    // ---- ground
    ctx.fillStyle = MAP_COLORS.ocean;
    ctx.fillRect(0, 0, w, h);
    drawGraticule(ctx, vp);

    // ---- land and borders (Natural Earth, simplified; drawing data only)
    if (d?.available) {
      ctx.fillStyle = MAP_COLORS.land;
      ctx.strokeStyle = MAP_COLORS.landEdge;
      ctx.lineWidth = 0.8;
      ctx.lineJoin = 'round';
      ctx.beginPath();
      for (const polygon of d.land) tracePolygon(ctx, vp, polygon);
      ctx.fill('evenodd');
      ctx.stroke();

      ctx.strokeStyle = 'rgba(143,133,116,0.5)';
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      for (const c of d.countries) for (const polygon of c.polygons) tracePolygon(ctx, vp, polygon);
      ctx.stroke();
    }

    const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
    const place = (text: string, x: number, y: number, font: string): { x: number; y: number } | null => {
      ctx.font = font;
      const tw = ctx.measureText(text).width;
      const box = { x0: x - 2, y0: y - 11, x1: x + tw + 2, y1: y + 3 };
      if (box.x0 < 0 || box.y0 < 0 || box.x1 > w || box.y1 > h) return null;
      for (const b of placed) if (box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0) return null;
      placed.push(box);
      return { x, y };
    };

    // Reserve space for the things that must be labelled first, then fill with country names.
    const labelJobs: { text: string; x: number; y: number; font: string; fill: string; halo: boolean; center?: boolean }[] = [];

    // ---- polar-chart view outline
    if (pe) {
      const outline = viewOutline(pe.viewport);
      if (outline.length > 3) {
        ctx.save();
        ctx.setLineDash([6, 4]);
        ctx.strokeStyle = '#0B5C8E';
        ctx.fillStyle = 'rgba(11,92,142,0.07)';
        ctx.lineWidth = 1.6;
        for (const run of splitAtAntimeridian(outline)) {
          ctx.beginPath();
          run.forEach((p, i) => {
            const s = vp.project(p.lat, p.lon);
            if (i === 0) ctx.moveTo(s.x, s.y);
            else ctx.lineTo(s.x, s.y);
          });
          ctx.fill();
          ctx.stroke();
        }
        ctx.restore();
        const anchor = vp.project(outline[0].lat, outline[0].lon);
        labelJobs.push({
          text: 'Antarctic chart view',
          x: Math.min(w - 150, Math.max(8, anchor.x + 6)),
          y: Math.min(h - 8, Math.max(16, anchor.y + 14)),
          font: `600 11px ${FONT}`,
          fill: '#0B5C8E',
          halo: true,
        });
      }
    }

    // ---- routes
    const line = (pts: { lat: number; lon: number }[], style: string, width: number, dash: number[]): void => {
      if (pts.length < 2) return;
      ctx.save();
      ctx.setLineDash(dash);
      ctx.strokeStyle = style;
      ctx.lineWidth = width;
      ctx.lineJoin = 'round';
      ctx.lineCap = 'round';
      ctx.beginPath();
      pts.forEach((p, i) => {
        const s = vp.project(p.lat, p.lon);
        if (i === 0) ctx.moveTo(s.x, s.y);
        else ctx.lineTo(s.x, s.y);
      });
      ctx.stroke();
      ctx.restore();
    };
    if (sc.layers.baselineRoute) {
      line(sc.baselineRoute.map((q) => ({ lat: q.latitude, lon: q.longitude })), MAP_COLORS.routeBaseline, 1.5, [6, 4]);
    }
    if (sc.layers.optimisedRoute) {
      line(sc.optimisedRoute.map((q) => ({ lat: q.latitude, lon: q.longitude })), MAP_COLORS.routeOptimised, 2.4, []);
    }
    if (sc.layers.track) line(sc.track.map(([lat, lon]) => ({ lat, lon })), MAP_COLORS.track, 2.6, []);

    // ---- ports and stations
    const zoom = vp.zoom;
    const marks: { id: string; name: string; lat: number; lon: number; kind: 'port' | 'station'; key: boolean }[] = [
      ...sc.ports.map((p) => ({
        id: p.id,
        name: p.name,
        lat: p.latitude,
        lon: p.longitude,
        kind: 'port' as const,
        key: p.id === oid || p.id === did,
      })),
      ...sc.stations.map((s) => ({
        id: s.id,
        name: s.name,
        lat: s.latitude,
        lon: s.longitude,
        kind: 'station' as const,
        key: s.id === oid || s.id === did || Boolean(s.is_indian),
      })),
    ];
    // Draw the endpoints last so they sit on top.
    marks.sort((a, b) => Number(a.key) - Number(b.key));
    for (const m of marks) {
      const s = vp.project(m.lat, m.lon);
      if (s.x < -10 || s.x > w + 10 || s.y < -10 || s.y > h + 10) continue;
      const endpoint = m.id === oid || m.id === did;
      ctx.beginPath();
      if (m.kind === 'port') {
        ctx.rect(s.x - 4, s.y - 4, 8, 8);
        ctx.fillStyle = MAP_COLORS.port;
      } else {
        ctx.arc(s.x, s.y, 4, 0, Math.PI * 2);
        ctx.fillStyle = MAP_COLORS.station;
      }
      ctx.fill();
      ctx.lineWidth = endpoint ? 2.4 : 1;
      ctx.strokeStyle = endpoint ? '#0E2433' : 'rgba(255,255,255,0.9)';
      ctx.stroke();
      if (m.key || zoom > 2.2) {
        labelJobs.push({
          text: m.name,
          x: s.x + 8,
          y: s.y + 4,
          font: `${endpoint ? 600 : 500} 11px ${FONT}`,
          fill: '#0E2433',
          halo: true,
        });
      }
    }

    // ---- vessel
    if (sc.layers.vessel && sc.vessel) {
      const s = vp.project(sc.vessel.lat, sc.vessel.lon);
      ctx.beginPath();
      ctx.arc(s.x, s.y, 5.5, 0, Math.PI * 2);
      ctx.fillStyle = '#FFFFFF';
      ctx.fill();
      ctx.lineWidth = 2.2;
      ctx.strokeStyle = MAP_COLORS.track;
      ctx.stroke();
    }

    // ---- labels: important ones were queued first, then country names fill what is left
    const countryThreshold = 55 / Math.max(1, zoom * zoom);
    if (d?.available) {
      for (const c of d.countries) {
        if (c.label_rank < countryThreshold) continue;
        const s = vp.project(c.label[1], c.label[0]);
        labelJobs.push({
          text: c.name.toUpperCase(),
          x: s.x,
          y: s.y,
          font: `500 10px ${FONT}`,
          fill: 'rgba(14,36,51,0.52)',
          halo: false,
          center: true,
        });
      }
    }
    for (const j of labelJobs) {
      let jx = j.x;
      if (j.center) {
        ctx.font = j.font;
        jx = j.x - ctx.measureText(j.text).width / 2;
      }
      const at = place(j.text, jx, j.y, j.font);
      if (!at) continue;
      ctx.font = j.font;
      if (j.halo) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(255,255,255,0.85)';
        ctx.strokeText(j.text, at.x, at.y);
      }
      ctx.fillStyle = j.fill;
      ctx.fillText(j.text, at.x, at.y);
    }

    // ---- honesty strip
    ctx.font = `600 11px ${FONT}`;
    ctx.fillStyle = 'rgba(14,36,51,0.75)';
    ctx.fillText('REGIONAL CONTEXT  ·  Mercator  ·  not for navigation', 14 + insets.left, h - 12 - insets.bottom);
    if (d?.available) {
      ctx.font = `10px ${FONT}`;
      ctx.textAlign = 'right';
      ctx.fillStyle = 'rgba(14,36,51,0.62)';
      ctx.fillText('Land: Natural Earth (public domain), simplified ~4 km', w - 14, h - 12 - insets.bottom);
      ctx.textAlign = 'left';
    }
  }, [vp, insets.left, insets.bottom]);

  const schedule = useCallback((): void => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      paint();
    });
  }, [paint]);

  const fit = useCallback((): void => {
    const pts = routePoints.length ? routePoints : [];
    vp.fitPoints(pts, 90);
    schedule();
  }, [routePoints, vp, schedule]);

  // Size tracking. A hidden host measures zero, which is ignored, as MapCanvas does.
  useEffect(() => {
    const host = hostRef.current;
    if (!host) return undefined;
    const apply = (): void => {
      const r = host.getBoundingClientRect();
      if (r.width < 2 || r.height < 2) return;
      vp.resize(r.width, r.height);
      schedule();
    };
    apply();
    const ro = new ResizeObserver(apply);
    ro.observe(host);
    return () => {
      ro.disconnect();
      if (rafRef.current) cancelAnimationFrame(rafRef.current);
      rafRef.current = 0;
    };
  }, [vp, schedule]);

  // Repaint on data, scene or visibility changes; frame the route when it first appears or changes.
  useEffect(() => {
    if (visible && fittedKeyRef.current !== routeKey) {
      fittedKeyRef.current = routeKey;
      vp.fitPoints(routePoints, 90);
    }
    schedule();
  }, [visible, data, scene, routeKey, routePoints, vp, schedule, originId, destinationId, polarEngine]);

  // ---- interaction
  const onWheel = (e: React.WheelEvent<HTMLCanvasElement>): void => {
    const r = e.currentTarget.getBoundingClientRect();
    vp.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * 0.0016));
    schedule();
  };
  const onDown = (e: React.PointerEvent<HTMLCanvasElement>): void => {
    e.currentTarget.setPointerCapture(e.pointerId);
    dragRef.current = { x: e.clientX, y: e.clientY };
  };
  const onMove = (e: React.PointerEvent<HTMLCanvasElement>): void => {
    const d = dragRef.current;
    if (!d) return;
    vp.panBy(e.clientX - d.x, e.clientY - d.y);
    d.x = e.clientX;
    d.y = e.clientY;
    schedule();
  };
  const onUp = (): void => {
    dragRef.current = null;
  };
  const zoomBy = (f: number): void => {
    vp.zoomAt(vp.widthPx / 2, vp.heightPx / 2, f);
    schedule();
  };

  const unavailable = context.isError || (data && !data.available);

  return (
    <div ref={hostRef} className="relative h-full w-full overflow-hidden">
      <canvas
        ref={canvasRef}
        className="absolute inset-0 touch-none select-none"
        style={{ cursor: 'grab' }}
        role="img"
        aria-label="Regional context map: voyage route, ports and stations, with the Antarctic chart view outlined"
        onWheel={onWheel}
        onPointerDown={onDown}
        onPointerMove={onMove}
        onPointerUp={onUp}
        onPointerLeave={onUp}
      />

      <div className="absolute z-10 flex flex-col gap-1.5" style={{ top: Math.max(12, insets.top), right: insets.right + 16 }}>
        <button className="btn-icon" title="Zoom in" aria-label="Zoom in" onClick={() => zoomBy(1.4)}>
          <Plus size={16} />
        </button>
        <button className="btn-icon" title="Zoom out" aria-label="Zoom out" onClick={() => zoomBy(1 / 1.4)}>
          <Minus size={16} />
        </button>
        <button className="btn-icon" title="Fit to route" aria-label="Fit to route" onClick={fit}>
          <Maximize2 size={16} />
        </button>
      </div>

      {context.isLoading && (
        <Note title="Loading regional coastline…" />
      )}
      {unavailable && (
        <Note
          title="Regional coastline not built"
          lines={
            context.isError
              ? ['The regional geography could not be fetched from the service.']
              : [
                  data?.reason ?? '',
                  'The ports, stations and route below are still drawn in their true positions.',
                  `Build it once:  ${data?.setup?.[0] ?? 'python -m scripts.build_regional_context'}`,
                ]
          }
          bottomInset={insets.bottom}
        />
      )}
    </div>
  );
}

function Note({ title, lines = [], bottomInset = 0 }: { title: string; lines?: string[]; bottomInset?: number }): JSX.Element {
  return (
    <div
      role="status"
      className="float absolute left-1/2 z-10 w-[min(520px,90%)] -translate-x-1/2 px-4 py-3 text-xs text-ink-2"
      style={{ bottom: Math.max(48, bottomInset + 40) }}
    >
      <div className="font-medium text-ink">{title}</div>
      {lines.filter(Boolean).map((l) => (
        <div key={l} className="mt-0.5 text-2xs text-ink-3">
          {l}
        </div>
      ))}
    </div>
  );
}

function tracePolygon(ctx: CanvasRenderingContext2D, vp: RegionViewport, rings: number[][]): void {
  for (const ring of rings) {
    for (let i = 0; i + 1 < ring.length; i += 2) {
      const s = vp.project(ring[i + 1], ring[i]);
      if (i === 0) ctx.moveTo(s.x, s.y);
      else ctx.lineTo(s.x, s.y);
    }
    ctx.closePath();
  }
}

function drawGraticule(ctx: CanvasRenderingContext2D, vp: RegionViewport): void {
  const tl = vp.unproject(0, 0);
  const br = vp.unproject(vp.widthPx, vp.heightPx);
  const step = graticuleStep(Math.abs(br.lon - tl.lon));
  ctx.save();
  ctx.lineWidth = 1;
  ctx.font = `10px ${FONT}`;
  ctx.fillStyle = MAP_COLORS.graticuleLabel;
  ctx.strokeStyle = MAP_COLORS.graticule;
  for (let lon = Math.ceil(tl.lon / step) * step; lon <= br.lon; lon += step) {
    const x = vp.project(0, lon).x;
    ctx.beginPath();
    ctx.moveTo(x, 0);
    ctx.lineTo(x, vp.heightPx);
    ctx.stroke();
    ctx.fillText(`${Math.abs(lon)}°${lon < 0 ? 'W' : lon > 0 ? 'E' : ''}`, x + 3, 12);
  }
  for (let lat = Math.ceil(br.lat / step) * step; lat <= tl.lat; lat += step) {
    const y = vp.project(lat, 0).y;
    ctx.beginPath();
    ctx.moveTo(0, y);
    ctx.lineTo(vp.widthPx, y);
    ctx.stroke();
    ctx.fillText(`${Math.abs(lat)}°${lat < 0 ? 'S' : lat > 0 ? 'N' : ''}`, 4, y - 3);
  }
  ctx.restore();
}
