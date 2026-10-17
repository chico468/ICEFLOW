/**
 * The render loop.
 *
 * The engine holds a scene and a viewport and redraws only when something changes, or
 * while an animation is running. A frame is a single pass over the layer stack, so there
 * is one place that decides paint order and one place that owns the canvas.
 */
import type {
  CoastlineFeature,
  IceField,
  IcebergForecast,
  IcebergProfile,
  Port,
  RadarSweep,
  Station,
  Waypoint,
} from '../api/types';
import {
  drawBackground,
  drawCompression,
  drawDriftField,
  drawGraticule,
  drawIceEdge,
  drawIceRaster,
  drawIcebergDrift,
  drawIcebergs,
  drawInspectMarker,
  drawLand,
  drawRadarRings,
  drawRoute,
  drawScaleBar,
  drawStations,
  drawTrack,
  drawVessel,
  type RasterMode,
} from './layers';
import { MAP_COLORS } from './palette';
import { Viewport } from './viewport';

export interface LayerToggles {
  graticule: boolean;
  iceRaster: boolean;
  iceEdge: boolean;
  compression: boolean;
  land: boolean;
  drift: boolean;
  icebergs: boolean;
  baselineRoute: boolean;
  optimisedRoute: boolean;
  track: boolean;
  vessel: boolean;
  radarRings: boolean;
  labels: boolean;
}

export const DEFAULT_LAYERS: LayerToggles = {
  graticule: true,
  iceRaster: true,
  iceEdge: true,
  compression: true,
  land: true,
  drift: true,
  icebergs: true,
  baselineRoute: true,
  optimisedRoute: true,
  track: true,
  vessel: true,
  radarRings: true,
  labels: true,
};

export interface MapScene {
  coastline: CoastlineFeature[];
  stations: Station[];
  ports: Port[];
  iceField: IceField | null;
  icebergs: IcebergProfile[];
  selectedBergId: string | null;
  bergDrift: IcebergForecast | null;
  optimisedRoute: Waypoint[];
  baselineRoute: Waypoint[];
  track: [number, number][];
  vessel: { lat: number; lon: number; heading: number } | null;
  radar: RadarSweep | null;
  inspect: { lat: number; lon: number } | null;
  rasterMode: RasterMode;
  rasterOpacity: number;
  rioColoredRoute: boolean;
  layers: LayerToggles;
}

export function emptyScene(): MapScene {
  return {
    coastline: [],
    stations: [],
    ports: [],
    iceField: null,
    icebergs: [],
    selectedBergId: null,
    bergDrift: null,
    optimisedRoute: [],
    baselineRoute: [],
    track: [],
    vessel: null,
    radar: null,
    inspect: null,
    rasterMode: 'concentration',
    rasterOpacity: 0.92,
    rioColoredRoute: false,
    layers: { ...DEFAULT_LAYERS },
  };
}

export class MapEngine {
  readonly viewport = new Viewport();
  private scene: MapScene = emptyScene();
  private canvas: HTMLCanvasElement | null = null;
  private ctx: CanvasRenderingContext2D | null = null;
  private dpr = 1;
  private dirty = true;
  private rafId: number | null = null;
  private frameMs = 0;

  attach(canvas: HTMLCanvasElement): void {
    this.canvas = canvas;
    this.ctx = canvas.getContext('2d', { alpha: false });
    this.dirty = true;
    this.start();
  }

  detach(): void {
    this.stop();
    this.canvas = null;
    this.ctx = null;
  }

  setScene(scene: MapScene): void {
    this.scene = scene;
    this.dirty = true;
  }

  invalidate(): void {
    this.dirty = true;
  }

  /** Sizes the backing store for the device pixel ratio and keeps CSS pixels as the unit. */
  resize(cssWidth: number, cssHeight: number, dpr: number): void {
    if (!this.canvas) return;
    this.dpr = dpr;
    this.canvas.width = Math.max(1, Math.round(cssWidth * dpr));
    this.canvas.height = Math.max(1, Math.round(cssHeight * dpr));
    this.canvas.style.width = `${cssWidth}px`;
    this.canvas.style.height = `${cssHeight}px`;
    this.viewport.resize(cssWidth, cssHeight);
    this.dirty = true;
  }

  get lastFrameDurationMs(): number {
    return this.frameMs;
  }

  private start(): void {
    if (this.rafId !== null) return;
    const loop = (): void => {
      this.rafId = requestAnimationFrame(loop);
      if (!this.dirty) return;
      this.dirty = false;
      const started = performance.now();
      this.render();
      this.frameMs = performance.now() - started;
    };
    this.rafId = requestAnimationFrame(loop);
  }

  private stop(): void {
    if (this.rafId !== null) cancelAnimationFrame(this.rafId);
    this.rafId = null;
  }

  /** Paint one frame, bottom-up. */
  render(): void {
    const ctx = this.ctx;
    if (!ctx || !this.canvas) return;
    const s = this.scene;
    const vp = this.viewport;
    const L = s.layers;

    ctx.save();
    ctx.setTransform(this.dpr, 0, 0, this.dpr, 0, 0);

    drawBackground(ctx, vp);
    if (L.graticule) drawGraticule(ctx, vp);
    if (L.iceRaster && s.iceField) drawIceRaster(ctx, vp, s.iceField, s.rasterMode, s.rasterOpacity);
    if (L.iceEdge && s.iceField) drawIceEdge(ctx, vp, s.iceField.lons, s.iceField.ice_edge_lat);
    if (L.compression && s.iceField) drawCompression(ctx, vp, s.iceField);
    if (L.land) drawLand(ctx, vp, s.coastline);
    if (L.drift && s.iceField) drawDriftField(ctx, vp, s.iceField);
    if (L.icebergs && s.bergDrift) drawIcebergDrift(ctx, vp, s.bergDrift);
    if (L.icebergs) drawIcebergs(ctx, vp, s.icebergs, s.selectedBergId);
    if (L.baselineRoute && s.baselineRoute.length > 1)
      drawRoute(ctx, vp, s.baselineRoute, { dashed: true, color: MAP_COLORS.routeBaseline, width: 1.5 });
    if (L.optimisedRoute && s.optimisedRoute.length > 1)
      drawRoute(ctx, vp, s.optimisedRoute, {
        color: MAP_COLORS.routeOptimised,
        width: 2.2,
        rioColored: s.rioColoredRoute,
      });
    if (L.track) drawTrack(ctx, vp, s.track);
    if (L.radarRings && s.vessel)
      drawRadarRings(ctx, vp, s.vessel.lat, s.vessel.lon, s.radar?.max_range_nm ?? 6, s.radar);
    if (L.vessel && s.vessel) drawVessel(ctx, vp, s.vessel.lat, s.vessel.lon, s.vessel.heading);
    if (L.labels) drawStations(ctx, vp, s.stations, s.ports);
    if (s.inspect) drawInspectMarker(ctx, vp, s.inspect.lat, s.inspect.lon);
    drawScaleBar(ctx, vp);

    ctx.restore();
  }
}
