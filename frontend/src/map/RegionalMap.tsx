/**
 * Regional context map: the voyage region in Mercator, drawn on its own canvas, independent of the polar chart.
 *
 * WHAT IT IS FOR
 * The polar chart is the navigation chart and cannot show where the ports are relative to Africa, India or
 * Australia. This map answers "where is this voyage on the planet?". It draws the SAME routes, vessel, ports
 * and stations the polar chart draws, from the same scene, so the two cannot disagree, and it outlines the part
 * of the world the polar chart is currently showing. It does NOT follow the polar chart's pan and zoom: the
 * two views are deliberately independent.
 *
 * WHAT IT IS NOT
 * Land comes from Natural Earth, simplified to about 4 km (scripts/build_regional_context.py). It is drawing
 * data, never used for the land mask, coastal clearance or routing, and the map says "not for navigation" on
 * its face. When that file has not been built the map says so and still draws the graticule, ports, stations
 * and route.
 *
 * INTERACTION
 *   wheel / trackpad scroll   zoom about the pointer         pinch (ctrl+wheel)   zoom about the pointer
 *   drag                      pan                            double-click         zoom in (shift: out)
 *   arrow keys                pan (shift: farther)           + / -                zoom about the centre
 *   0 or Home                 back to the route extent       F                    show the whole region
 * Keyboard shortcuts act only while the map itself has focus, so they never steal keys from form controls.
 * Button, double-click and keyboard moves ease over about 200 ms; wheel and drag are immediate. With the
 * system's reduced-motion setting on, nothing eases.
 *
 * COST
 * Nothing animates on its own. The map paints once per change, coalesced on one animation frame. Polygons
 * outside the view are skipped by bounding box. Every frame and listener is cancelled on unmount.
 */
import { useCallback, useEffect, useMemo, useRef, type KeyboardEvent, type ReactNode } from 'react';
import { Globe, Maximize2, Minus, Plus } from 'lucide-react';
import { useRegionalContext } from '../api/queries';
import { MapToolbar, ToolButton } from '../components/MapToolbar';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { LABEL_PRIORITY, MAX_COUNTRY_LABELS, MAX_MARK_LABELS, countryRankThreshold, showMarkLabel } from './labelPolicy';
import { formatLat, formatLon } from './MapCanvas';
import type { MapEngine, MapScene } from './MapEngine';
import {
  RegionViewport,
  boundsIntersect,
  easeOutCubic,
  graticuleStep,
  lerpView,
  mercLat,
  metresPerPixelAt,
  niceScaleBar,
  ringBounds,
  splitAtAntimeridian,
  viewOutline,
  type LonLat,
  type RegionBounds,
  type ViewState,
} from './mercator';
import { MAP_COLORS } from './palette';

const DEFAULT_REGION: RegionBounds = { lon_min: -30, lon_max: 165, lat_min: -75, lat_max: 40 };
const FONT = '"Avenir Next", system-ui, sans-serif';
const KEY_PAN_PX = 80;
const KEY_PAN_FAR_PX = 240;
const EASE_MS = 200;

interface Props {
  scene: MapScene;
  /** False while another view is on display: the map then does no work at all. */
  visible: boolean;
  /** The polar chart's engine, read (never written) to outline its current view. */
  polarEngine: MapEngine | null;
  originId: string;
  destinationId: string;
  /** A first row for the toolbar, e.g. the Polar / Regional switch. */
  toolbarLead?: ReactNode;
}

interface LabelJob {
  text: string;
  x: number;
  y: number;
  font: string;
  fill: string;
  halo: boolean;
  center?: boolean;
  priority: number;
}

export function RegionalMap({ scene, visible, polarEngine, originId, destinationId, toolbarLead }: Props): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const canvasRef = useRef<HTMLCanvasElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const reduced = useReducedMotion();
  const context = useRegionalContext();
  const data = context.data;

  const region = data?.region ?? DEFAULT_REGION;
  const vp = useMemo(
    () => new RegionViewport(region),
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [region.lon_min, region.lon_max, region.lat_min, region.lat_max],
  );

  const rafRef = useRef(0);
  const animRef = useRef(0);
  /** Where the animation in flight will end. New moves build on this, so rapid presses accumulate instead of restarting. */
  const pendingRef = useRef<ViewState | null>(null);
  const dragRef = useRef<{ x: number; y: number; moved: boolean } | null>(null);
  const fittedKeyRef = useRef('');

  // ---- the extent the map opens on and returns to: the route, else the two endpoints
  const routePoints = useMemo(
    () => scene.optimisedRoute.map((w) => ({ lat: w.latitude, lon: w.longitude })),
    [scene.optimisedRoute],
  );
  const endpointPoints = useMemo(() => {
    const find = (id: string): LonLat | null => {
      const hit = scene.ports.find((p) => p.id === id) ?? scene.stations.find((s) => s.id === id);
      return hit ? { lat: hit.latitude, lon: hit.longitude } : null;
    };
    return [find(originId), find(destinationId)].filter((p): p is LonLat => p !== null);
  }, [scene.ports, scene.stations, originId, destinationId]);
  const initialPoints = routePoints.length >= 2 ? routePoints : endpointPoints;
  const initialKey = `${originId}>${destinationId}|${routePoints.length}|${initialPoints.length}`;

  // ---- per-polygon bounding boxes, computed once per dataset, so off-screen shapes cost nothing
  const landBounds = useMemo(() => (data?.land ?? []).map((poly) => ringBounds(poly[0] ?? [])), [data?.land]);
  const countryBounds = useMemo(
    () => (data?.countries ?? []).map((c) => c.polygons.map((poly) => ringBounds(poly[0] ?? []))),
    [data?.countries],
  );

  const latest = useRef({ scene, data, originId, destinationId, polarEngine, visible, landBounds, countryBounds });
  latest.current = { scene, data, originId, destinationId, polarEngine, visible, landBounds, countryBounds };

  // =================================================================== painting
  const paint = useCallback((): void => {
    const canvas = canvasRef.current;
    if (!canvas) return;
    const { scene: sc, data: d, originId: oid, destinationId: did, polarEngine: pe, visible: vis } = latest.current;
    const { landBounds: lb, countryBounds: cb } = latest.current;
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
    const view = vp.visibleBounds();
    const zoom = vp.zoom;
    // Exposed for tests and diagnostics: the view's zoom (1 = whole region) and centre.
    const host = hostRef.current;
    if (host) {
      host.dataset.zoom = zoom.toFixed(3);
      host.dataset.centre = `${vp.centreLon.toFixed(3)},${mercLat(vp.centreY).toFixed(3)}`;
    }

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
      d.land.forEach((polygon, i) => {
        if (boundsIntersect(lb[i], view)) tracePolygon(ctx, vp, polygon);
      });
      ctx.fill('evenodd');
      ctx.stroke();

      ctx.strokeStyle = 'rgba(143,133,116,0.5)';
      ctx.lineWidth = 0.6;
      ctx.beginPath();
      d.countries.forEach((c, ci) =>
        c.polygons.forEach((polygon, pi) => {
          if (boundsIntersect(cb[ci][pi], view)) tracePolygon(ctx, vp, polygon);
        }),
      );
      ctx.stroke();
    }

    const jobs: LabelJob[] = [];

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
        jobs.push({
          text: 'Antarctic chart view',
          x: Math.min(w - 150, Math.max(8, anchor.x + 6)),
          y: Math.min(h - 8, Math.max(16, anchor.y + 14)),
          font: `600 11px ${FONT}`,
          fill: '#0B5C8E',
          halo: true,
          priority: LABEL_PRIORITY.view,
        });
      }
    }

    // ---- routes
    const line = (pts: LonLat[], style: string, width: number, dash: number[]): void => {
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

    // ---- ports and stations: every one is drawn as a small symbol; names are earned by zoom
    const marks = [
      ...sc.ports.map((p) => ({ id: p.id, name: p.name, lat: p.latitude, lon: p.longitude, kind: 'port' as const, indian: false })),
      ...sc.stations.map((s) => ({
        id: s.id,
        name: s.name,
        lat: s.latitude,
        lon: s.longitude,
        kind: 'station' as const,
        indian: Boolean(s.is_indian),
      })),
    ];
    // Draw the endpoints last so they sit on top.
    marks.sort((a, b) => Number(a.id === oid || a.id === did) - Number(b.id === oid || b.id === did));
    for (const m of marks) {
      const s = vp.project(m.lat, m.lon);
      if (s.x < -10 || s.x > w + 10 || s.y < -10 || s.y > h + 10) continue;
      const endpoint = m.id === oid || m.id === did;
      ctx.beginPath();
      if (m.kind === 'port') {
        ctx.rect(s.x - 3.5, s.y - 3.5, 7, 7);
        ctx.fillStyle = MAP_COLORS.port;
      } else {
        ctx.arc(s.x, s.y, 3.5, 0, Math.PI * 2);
        ctx.fillStyle = MAP_COLORS.station;
      }
      ctx.fill();
      ctx.lineWidth = endpoint ? 2.2 : 1;
      ctx.strokeStyle = endpoint ? '#0E2433' : 'rgba(255,255,255,0.9)';
      ctx.stroke();
      if (showMarkLabel({ kind: m.kind, endpoint, indian: m.indian }, zoom)) {
        jobs.push({
          text: m.name,
          x: s.x + 8,
          y: s.y + 4,
          font: `${endpoint ? 600 : 500} 11px ${FONT}`,
          fill: '#0E2433',
          halo: true,
          priority: endpoint ? LABEL_PRIORITY.endpoint : m.kind === 'port' ? LABEL_PRIORITY.port : LABEL_PRIORITY.station,
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

    // ---- country names: only the largest visible, and only as many as the cap allows
    if (d?.available) {
      const threshold = countryRankThreshold(zoom);
      let count = 0;
      for (const c of d.countries) {
        if (count >= MAX_COUNTRY_LABELS) break;
        if (c.label_rank < threshold) continue;
        const s = vp.project(c.label[1], c.label[0]);
        if (s.x < 0 || s.x > w || s.y < 0 || s.y > h) continue;
        count += 1;
        jobs.push({
          text: c.name.toUpperCase(),
          x: s.x,
          y: s.y,
          font: `500 10px ${FONT}`,
          fill: 'rgba(14,36,51,0.52)',
          halo: false,
          center: true,
          priority: LABEL_PRIORITY.country,
        });
      }
    }

    // ---- place labels in priority order, dropping anything that would overlap or leave the map
    const placed: { x0: number; y0: number; x1: number; y1: number }[] = [];
    let markLabels = 0;
    jobs.sort((a, b) => a.priority - b.priority);
    for (const j of jobs) {
      if (j.priority >= LABEL_PRIORITY.port && j.priority < LABEL_PRIORITY.country && markLabels >= MAX_MARK_LABELS) continue;
      ctx.font = j.font;
      const tw = ctx.measureText(j.text).width;
      const x = j.center ? j.x - tw / 2 : j.x;
      const box = { x0: x - 2, y0: j.y - 11, x1: x + tw + 2, y1: j.y + 3 };
      if (box.x0 < 0 || box.y0 < 0 || box.x1 > w || box.y1 > h) continue;
      if (placed.some((b) => box.x0 < b.x1 && box.x1 > b.x0 && box.y0 < b.y1 && box.y1 > b.y0)) continue;
      placed.push(box);
      if (j.priority >= LABEL_PRIORITY.port && j.priority < LABEL_PRIORITY.country) markLabels += 1;
      if (j.halo) {
        ctx.lineWidth = 3;
        ctx.strokeStyle = 'rgba(255,255,255,0.85)';
        ctx.strokeText(j.text, x, j.y);
      }
      ctx.fillStyle = j.fill;
      ctx.fillText(j.text, x, j.y);
    }

    // ---- scale bar, true at the latitude of the view's centre (Mercator stretches away from the equator)
    const centreLat = vp.unproject(w / 2, h / 2).lat;
    const bar = niceScaleBar(metresPerPixelAt(vp.scale, centreLat), 120);
    if (bar) {
      const x0 = 14;
      const y0 = h - 34;
      ctx.save();
      ctx.lineCap = 'butt';
      ctx.strokeStyle = 'rgba(255,255,255,0.9)';
      ctx.lineWidth = 4.5;
      ctx.beginPath();
      ctx.moveTo(x0, y0);
      ctx.lineTo(x0 + bar.lengthPx, y0);
      ctx.stroke();
      ctx.strokeStyle = '#0E2433';
      ctx.lineWidth = 2;
      ctx.beginPath();
      ctx.moveTo(x0, y0 - 4);
      ctx.lineTo(x0, y0);
      ctx.lineTo(x0 + bar.lengthPx, y0);
      ctx.lineTo(x0 + bar.lengthPx, y0 - 4);
      ctx.stroke();
      ctx.font = `600 11px ${FONT}`;
      ctx.fillStyle = '#0E2433';
      ctx.fillText(`${bar.label}  ·  true at ${Math.abs(centreLat).toFixed(0)}°${centreLat < 0 ? 'S' : 'N'}`, x0, y0 - 8);
      ctx.restore();
    }

    // ---- honesty strip
    ctx.font = `600 11px ${FONT}`;
    ctx.fillStyle = 'rgba(14,36,51,0.75)';
    ctx.fillText('REGIONAL CONTEXT  ·  Mercator  ·  not for navigation', 14, h - 12);
    if (d?.available) {
      ctx.font = `10px ${FONT}`;
      ctx.textAlign = 'right';
      ctx.fillStyle = 'rgba(14,36,51,0.62)';
      ctx.fillText('Land: Natural Earth (public domain), simplified ~4 km', w - 14, h - 12);
      ctx.textAlign = 'left';
    }
  }, [vp]);

  const schedule = useCallback((): void => {
    if (rafRef.current) return;
    rafRef.current = requestAnimationFrame(() => {
      rafRef.current = 0;
      paint();
    });
  }, [paint]);

  // =================================================================== view changes
  const cancelAnim = useCallback((): void => {
    if (animRef.current) cancelAnimationFrame(animRef.current);
    animRef.current = 0;
    pendingRef.current = null;
  }, []);

  /** Run `frame(e)` for e easing 0 to 1 over `ms`; or jump straight to 1 when motion is reduced. */
  const animate = useCallback(
    (frame: (e: number) => void, ms = EASE_MS): void => {
      if (animRef.current) cancelAnimationFrame(animRef.current);
      animRef.current = 0;
      if (reduced) {
        frame(1);
        pendingRef.current = null;
        schedule();
        return;
      }
      const t0 = performance.now();
      const step = (now: number): void => {
        const t = Math.min(1, (now - t0) / ms);
        frame(easeOutCubic(t));
        schedule();
        if (t < 1) {
          animRef.current = requestAnimationFrame(step);
        } else {
          animRef.current = 0;
          pendingRef.current = null;
        }
      };
      animRef.current = requestAnimationFrame(step);
    },
    [schedule, reduced],
  );

  /** The view a change would produce, built on the pending target of any animation in flight. */
  const targetFrom = useCallback(
    (apply: (v: RegionViewport) => void): ViewState => {
      const now = vp.getView();
      vp.setView(pendingRef.current ?? now);
      apply(vp);
      const target = vp.getView();
      vp.setView(now);
      return target;
    },
    [vp],
  );

  const zoomAbout = useCallback(
    (factor: number, px: number, py: number): void => {
      const target = targetFrom((v) => v.zoomAt(px, py, factor));
      const from: ViewState = vp.getView();
      const total = target.scale / from.scale;
      pendingRef.current = target;
      // Each frame re-applies the zoom from the start view, so the point under (px, py) never drifts mid-flight.
      animate((e) => {
        vp.setView(from);
        vp.zoomAt(px, py, Math.pow(total, e));
      });
    },
    [animate, targetFrom, vp],
  );

  const moveTo = useCallback(
    (target: ViewState, ms = EASE_MS): void => {
      const from = vp.getView();
      pendingRef.current = target;
      animate((e) => vp.setView(lerpView(from, target, e)), ms);
    },
    [animate, vp],
  );

  const panBy = useCallback((dx: number, dy: number): void => moveTo(targetFrom((v) => v.panBy(dx, dy)), 140), [moveTo, targetFrom]);

  const resetView = useCallback((): void => moveTo(vp.viewAfterFit(initialPoints, 90), 260), [initialPoints, moveTo, vp]);
  const wholeRegion = useCallback((): void => moveTo(vp.viewAfterFit([], 0), 260), [moveTo, vp]);
  const zoomCentre = (factor: number): void => zoomAbout(factor, vp.widthPx / 2, vp.heightPx / 2);

  // Size tracking. A hidden host still has layout, so it measures correctly; a zero size is ignored.
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
      cancelAnim();
    };
  }, [vp, schedule, cancelAnim]);

  // Open on the route (or the two endpoints) the first time this view is shown, and again if the route changes.
  useEffect(() => {
    if (visible && fittedKeyRef.current !== initialKey && vp.widthPx > 2) {
      fittedKeyRef.current = initialKey;
      vp.setView(vp.viewAfterFit(initialPoints, 90));
    }
    schedule();
  }, [visible, initialKey, initialPoints, data, scene, vp, schedule, originId, destinationId, polarEngine]);

  // Wheel: a NATIVE, non-passive listener. React's onWheel is passive, so it cannot stop the page from
  // scrolling or the browser from page-zooming on a pinch (which arrives as ctrl+wheel).
  useEffect(() => {
    const canvas = canvasRef.current;
    if (!canvas) return undefined;
    const onWheel = (e: WheelEvent): void => {
      e.preventDefault();
      cancelAnim();
      const unit = e.deltaMode === 1 ? 16 : e.deltaMode === 2 ? 400 : 1;
      const rate = e.ctrlKey ? 0.01 : 0.0018;
      const r = canvas.getBoundingClientRect();
      vp.zoomAt(e.clientX - r.left, e.clientY - r.top, Math.exp(-e.deltaY * unit * rate));
      schedule();
    };
    canvas.addEventListener('wheel', onWheel, { passive: false });
    return () => canvas.removeEventListener('wheel', onWheel);
  }, [vp, schedule, cancelAnim]);

  // =================================================================== pointer and keyboard
  const setReadout = (clientX: number, clientY: number | null): void => {
    const el = readoutRef.current;
    const canvas = canvasRef.current;
    if (!el || !canvas) return;
    if (clientY === null) {
      el.textContent = '—';
      return;
    }
    const r = canvas.getBoundingClientRect();
    const ll = vp.unproject(clientX - r.left, clientY - r.top);
    el.textContent = `${formatLat(ll.lat)}   ${formatLon(ll.lon)}`;
  };

  const onPointerDown = (e: React.PointerEvent<HTMLCanvasElement>): void => {
    if (e.button !== 0) return;
    cancelAnim();
    e.currentTarget.setPointerCapture(e.pointerId);
    e.currentTarget.style.cursor = 'grabbing';
    dragRef.current = { x: e.clientX, y: e.clientY, moved: false };
    hostRef.current?.focus({ preventScroll: true });
  };
  const onPointerMove = (e: React.PointerEvent<HTMLCanvasElement>): void => {
    setReadout(e.clientX, e.clientY);
    const d = dragRef.current;
    if (!d) return;
    d.moved = d.moved || Math.hypot(e.clientX - d.x, e.clientY - d.y) > 3;
    vp.panBy(e.clientX - d.x, e.clientY - d.y);
    d.x = e.clientX;
    d.y = e.clientY;
    schedule();
  };
  const endDrag = (e: React.PointerEvent<HTMLCanvasElement>): void => {
    dragRef.current = null;
    e.currentTarget.style.cursor = 'grab';
  };
  const onDoubleClick = (e: React.MouseEvent<HTMLCanvasElement>): void => {
    const r = e.currentTarget.getBoundingClientRect();
    zoomAbout(e.shiftKey ? 1 / 2 : 2, e.clientX - r.left, e.clientY - r.top);
  };

  const onKeyDown = (e: KeyboardEvent<HTMLDivElement>): void => {
    // Only when the map itself has focus: a button or field inside keeps its own keys.
    if (e.target !== e.currentTarget || e.altKey || e.ctrlKey || e.metaKey) return;
    const step = e.shiftKey ? KEY_PAN_FAR_PX : KEY_PAN_PX;
    const pan = panBy;
    switch (e.key) {
      case 'ArrowLeft': pan(step, 0); break;
      case 'ArrowRight': pan(-step, 0); break;
      case 'ArrowUp': pan(0, step); break;
      case 'ArrowDown': pan(0, -step); break;
      case '+': case '=': zoomCentre(1.5); break;
      case '-': case '_': zoomCentre(1 / 1.5); break;
      case '0': case 'Home': resetView(); break;
      case 'f': case 'F': wholeRegion(); break;
      default: return;
    }
    e.preventDefault();
  };

  const unavailable = context.isError || (data && !data.available);

  return (
    <div
      ref={hostRef}
      tabIndex={0}
      role="application"
      aria-label="Regional context map"
      aria-describedby="regional-map-help"
      onKeyDown={onKeyDown}
      className="relative h-full w-full overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    >
      <p id="regional-map-help" className="sr-only">
        Arrow keys pan, plus and minus zoom, zero returns to the route extent, F shows the whole region.
        Scroll or pinch to zoom, drag to pan, double-click to zoom in.
      </p>
      <canvas
        ref={canvasRef}
        className="absolute inset-0 touch-none select-none"
        style={{ cursor: 'grab' }}
        role="img"
        aria-label="Map of the voyage region with the route, ports and stations, and the Antarctic chart view outlined"
        onPointerDown={onPointerDown}
        onPointerMove={onPointerMove}
        onPointerUp={endDrag}
        onPointerCancel={endDrag}
        onPointerLeave={(e) => {
          if (!dragRef.current) setReadout(e.clientX, null);
        }}
        onDoubleClick={onDoubleClick}
      />

      <MapToolbar
        lead={toolbarLead}
        groups={[
          <>
            <ToolButton label="Zoom in" onClick={() => zoomCentre(1.5)}>
              <Plus size={15} />
            </ToolButton>
            <ToolButton label="Zoom out" onClick={() => zoomCentre(1 / 1.5)}>
              <Minus size={15} />
            </ToolButton>
            <ToolButton label="Reset to the route extent" onClick={resetView}>
              <Maximize2 size={15} />
            </ToolButton>
            <ToolButton label="Show the whole region" onClick={wholeRegion}>
              <Globe size={15} />
            </ToolButton>
          </>,
        ]}
      />

      <div
        ref={readoutRef}
        data-testid="regional-readout"
        className="pointer-events-none absolute bottom-7 right-3 z-10 rounded border border-hair bg-panel px-2 py-0.5 num text-2xs text-ink-2"
        aria-live="off"
      >
        —
      </div>

      {context.isLoading && <Note title="Loading regional coastline…" />}
      {unavailable && (
        <Note
          title="Regional coastline not built"
          lines={
            context.isError
              ? ['The regional geography could not be fetched from the service.']
              : [
                  data?.reason ?? '',
                  'The ports, stations and route are still drawn in their true positions.',
                  `Build it once:  ${data?.setup?.[0] ?? 'python -m scripts.build_regional_context'}`,
                ]
          }
        />
      )}
    </div>
  );
}

function Note({ title, lines = [] }: { title: string; lines?: string[] }): JSX.Element {
  return (
    <div
      role="status"
      className="float absolute bottom-14 left-1/2 z-10 w-[min(520px,90%)] -translate-x-1/2 px-4 py-3 text-xs text-ink-2"
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
