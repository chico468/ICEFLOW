/**
 * Web-Mercator-style projection and viewport for the regional context map.
 *
 * WHY MERCATOR, AND WHY A SECOND PROJECTION
 * The navigation chart is polar stereographic (EPSG:3031) and cannot show Africa, India or Australia
 * sensibly: it is built around the pole. The regional map therefore uses Mercator, the conventional
 * projection for passage charts. It is conformal (shapes and bearings are locally true) but its scale grows
 * toward the poles, so areas near 70 S look larger than they are. It is a context map and says so.
 *
 * Self-contained, with no imports, so it can be unit-tested without a browser.
 */

export interface LonLat {
  lat: number;
  lon: number;
}

export interface RegionBounds {
  lon_min: number;
  lon_max: number;
  lat_min: number;
  lat_max: number;
}

const DEG = Math.PI / 180;
const MAX_LAT = 85;

/** Mercator y, in radians, for a latitude in degrees. Latitude is clamped short of the poles. */
export function mercY(lat: number): number {
  const phi = Math.max(-MAX_LAT, Math.min(MAX_LAT, lat)) * DEG;
  return Math.log(Math.tan(Math.PI / 4 + phi / 2));
}

/** Inverse of mercY, giving a latitude in degrees. */
export function mercLat(y: number): number {
  return (2 * Math.atan(Math.exp(y)) - Math.PI / 2) / DEG;
}

export class RegionViewport {
  widthPx = 1;
  heightPx = 1;
  /** Centre of the view as longitude (degrees) and Mercator y (radians). */
  centreLon: number;
  centreY: number;
  /** Pixels per radian of longitude or of Mercator y. */
  scale = 100;

  private readonly bounds: RegionBounds;
  private minScale = 50;
  private maxScale = 50_000;

  constructor(bounds: RegionBounds) {
    this.bounds = bounds;
    this.centreLon = (bounds.lon_min + bounds.lon_max) / 2;
    this.centreY = (mercY(bounds.lat_min) + mercY(bounds.lat_max)) / 2;
  }

  /** Fit scale: the largest scale at which the whole region is visible. */
  private fitScale(): number {
    const spanLon = (this.bounds.lon_max - this.bounds.lon_min) * DEG;
    const spanY = mercY(this.bounds.lat_max) - mercY(this.bounds.lat_min);
    return Math.min(this.widthPx / spanLon, this.heightPx / spanY);
  }

  resize(widthPx: number, heightPx: number): void {
    const hadSize = this.widthPx > 1 && this.heightPx > 1;
    this.widthPx = Math.max(1, widthPx);
    this.heightPx = Math.max(1, heightPx);
    this.minScale = this.fitScale();
    this.maxScale = this.minScale * 40;
    if (!hadSize) this.scale = this.minScale;
    this.clamp();
  }

  /** Zoom relative to the whole-region view: 1 shows the entire region, larger is closer. */
  get zoom(): number {
    return this.minScale > 0 ? this.scale / this.minScale : 1;
  }

  project(lat: number, lon: number): { x: number; y: number } {
    return {
      x: this.widthPx / 2 + (lon - this.centreLon) * DEG * this.scale,
      y: this.heightPx / 2 - (mercY(lat) - this.centreY) * this.scale,
    };
  }

  unproject(x: number, y: number): LonLat {
    return {
      lon: this.centreLon + ((x - this.widthPx / 2) / this.scale) / DEG,
      lat: mercLat(this.centreY + (this.heightPx / 2 - y) / this.scale),
    };
  }

  panBy(dxPx: number, dyPx: number): void {
    this.centreLon -= (dxPx / this.scale) / DEG;
    this.centreY += dyPx / this.scale;
    this.clamp();
  }

  /** Zoom by `factor` keeping the geographic point under (px, py) fixed. */
  zoomAt(px: number, py: number, factor: number): void {
    const before = this.unproject(px, py);
    this.scale = Math.min(this.maxScale, Math.max(this.minScale, this.scale * factor));
    const after = this.project(before.lat, before.lon);
    this.panBy(px - after.x, py - after.y);
  }

  /** Frame a set of points with padding, never zooming out beyond the region or in past the limit. */
  fitPoints(points: LonLat[], padPx = 60): void {
    if (points.length === 0) {
      this.scale = this.minScale;
      this.centreLon = (this.bounds.lon_min + this.bounds.lon_max) / 2;
      this.centreY = (mercY(this.bounds.lat_min) + mercY(this.bounds.lat_max)) / 2;
      this.clamp();
      return;
    }
    let lonMin = Infinity;
    let lonMax = -Infinity;
    let yMin = Infinity;
    let yMax = -Infinity;
    for (const p of points) {
      lonMin = Math.min(lonMin, p.lon);
      lonMax = Math.max(lonMax, p.lon);
      const y = mercY(p.lat);
      yMin = Math.min(yMin, y);
      yMax = Math.max(yMax, y);
    }
    const spanX = Math.max(1e-6, (lonMax - lonMin) * DEG);
    const spanY = Math.max(1e-6, yMax - yMin);
    const availW = Math.max(1, this.widthPx - 2 * padPx);
    const availH = Math.max(1, this.heightPx - 2 * padPx);
    this.scale = Math.min(this.maxScale, Math.max(this.minScale, Math.min(availW / spanX, availH / spanY)));
    this.centreLon = (lonMin + lonMax) / 2;
    this.centreY = (yMin + yMax) / 2;
    this.clamp();
  }

  /** Keep the view inside the region; when the region is smaller than the view in an axis, centre it. */
  clamp(): void {
    const b = this.bounds;
    const halfLon = (this.widthPx / 2 / this.scale) / DEG;
    const halfY = this.heightPx / 2 / this.scale;
    const lonMid = (b.lon_min + b.lon_max) / 2;
    const yLo = mercY(b.lat_min);
    const yHi = mercY(b.lat_max);
    const yMid = (yLo + yHi) / 2;

    this.centreLon =
      halfLon * 2 >= b.lon_max - b.lon_min
        ? lonMid
        : Math.min(b.lon_max - halfLon, Math.max(b.lon_min + halfLon, this.centreLon));
    this.centreY = halfY * 2 >= yHi - yLo ? yMid : Math.min(yHi - halfY, Math.max(yLo + halfY, this.centreY));
  }

  /** True when the point projects inside the canvas, with a margin. */
  contains(lat: number, lon: number, marginPx = 0): boolean {
    const p = this.project(lat, lon);
    return p.x >= -marginPx && p.x <= this.widthPx + marginPx && p.y >= -marginPx && p.y <= this.heightPx + marginPx;
  }
}

/** The part of another viewport that is on screen, as a closed polyline of geographic points. */
export interface OutlineSource {
  widthPx: number;
  heightPx: number;
  insetLeft?: number;
  insetBottom?: number;
  screenToLatLon(px: number, py: number): LonLat;
}

/**
 * The visible rectangle of a polar chart, sampled along its edges and unprojected.
 * A rectangle in a polar projection is curved in latitude and longitude, so it is sampled rather than
 * reduced to four corners; that is what keeps the indicator honest on the Mercator map.
 */
export function viewOutline(src: OutlineSource, samplesPerEdge = 14): LonLat[] {
  const left = src.insetLeft ?? 0;
  const right = src.widthPx;
  const top = 0;
  const bottom = src.heightPx - (src.insetBottom ?? 0);
  if (right - left < 4 || bottom - top < 4) return [];
  const out: LonLat[] = [];
  const edge = (x0: number, y0: number, x1: number, y1: number): void => {
    for (let i = 0; i < samplesPerEdge; i += 1) {
      const t = i / samplesPerEdge;
      out.push(src.screenToLatLon(x0 + (x1 - x0) * t, y0 + (y1 - y0) * t));
    }
  };
  edge(left, top, right, top);
  edge(right, top, right, bottom);
  edge(right, bottom, left, bottom);
  edge(left, bottom, left, top);
  out.push(out[0]);
  return out.filter((p) => Number.isFinite(p.lat) && Number.isFinite(p.lon));
}

/** Split a polyline wherever it jumps across the antimeridian, so it is not drawn across the map. */
export function splitAtAntimeridian(points: LonLat[]): LonLat[][] {
  const runs: LonLat[][] = [];
  let run: LonLat[] = [];
  for (const p of points) {
    const prev = run[run.length - 1];
    if (prev && Math.abs(p.lon - prev.lon) > 180) {
      runs.push(run);
      run = [];
    }
    run.push(p);
  }
  if (run.length) runs.push(run);
  return runs;
}

/** Choose a graticule step that gives roughly `target` lines across `spanDeg`. */
export function graticuleStep(spanDeg: number, target = 8): number {
  const steps = [1, 2, 5, 10, 15, 20, 30, 45];
  const raw = spanDeg / target;
  return steps.find((s) => s >= raw) ?? 45;
}
