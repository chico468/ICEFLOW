/**
 * Viewport: the affine bridge between EPSG:3031 metres and canvas pixels.
 *
 * The projection is fixed; only translation and scale change as the user pans and zooms,
 * which keeps every layer's transform identical and lets the whole scene be redrawn from
 * one pair of numbers.
 */
import { fromEpsg3031, toEpsg3031, type LatLon } from './projection';

export interface Point {
  x: number;
  y: number;
}

export interface Bounds {
  minX: number;
  minY: number;
  maxX: number;
  maxY: number;
}

export class Viewport {
  /** Projected metres per CSS pixel. Smaller means more zoomed in. */
  metresPerPixel: number;
  /** Projected coordinate at the centre of the canvas. */
  centreX: number;
  centreY: number;
  widthPx: number;
  heightPx: number;
  /** Pixels at the left edge covered by a floating panel; the scale bar steps clear of it. */
  insetLeft = 0;
  /** Pixels at the bottom edge covered by a floating tray; the scale bar steps clear of it. */
  insetBottom = 0;

  static readonly MIN_MPP = 60; // ~60 m per pixel: close enough to see an anchorage
  static readonly MAX_MPP = 40_000; // whole hemisphere in one frame

  constructor(widthPx = 1000, heightPx = 700) {
    this.widthPx = widthPx;
    this.heightPx = heightPx;
    this.metresPerPixel = 9000;
    this.centreX = 1_200_000;
    this.centreY = 2_400_000;
  }

  clone(): Viewport {
    const v = new Viewport(this.widthPx, this.heightPx);
    v.metresPerPixel = this.metresPerPixel;
    v.centreX = this.centreX;
    v.centreY = this.centreY;
    v.insetLeft = this.insetLeft;
    v.insetBottom = this.insetBottom;
    return v;
  }

  resize(widthPx: number, heightPx: number): void {
    this.widthPx = Math.max(1, widthPx);
    this.heightPx = Math.max(1, heightPx);
  }

  /** Projected metres to canvas pixels. Screen y is inverted: projected +y is toward 0 E. */
  project(x: number, y: number): Point {
    return {
      x: (x - this.centreX) / this.metresPerPixel + this.widthPx / 2,
      y: this.heightPx / 2 - (y - this.centreY) / this.metresPerPixel,
    };
  }

  unproject(px: number, py: number): Point {
    return {
      x: (px - this.widthPx / 2) * this.metresPerPixel + this.centreX,
      y: (this.heightPx / 2 - py) * this.metresPerPixel + this.centreY,
    };
  }

  lonLatToScreen(lat: number, lon: number): Point {
    const p = toEpsg3031(lat, lon);
    return this.project(p.x, p.y);
  }

  screenToLatLon(px: number, py: number): LatLon {
    const p = this.unproject(px, py);
    return fromEpsg3031(p.x, p.y);
  }

  /** Zoom about a fixed screen point, so the coordinate under the cursor stays put. */
  zoomAbout(px: number, py: number, factor: number): void {
    const before = this.unproject(px, py);
    this.metresPerPixel = Math.min(
      Viewport.MAX_MPP,
      Math.max(Viewport.MIN_MPP, this.metresPerPixel * factor),
    );
    const after = this.unproject(px, py);
    this.centreX += before.x - after.x;
    this.centreY += before.y - after.y;
  }

  panPixels(dxPx: number, dyPx: number): void {
    this.centreX -= dxPx * this.metresPerPixel;
    this.centreY += dyPx * this.metresPerPixel;
  }

  /** Projected bounds currently visible, with an optional pixel margin. */
  visibleBounds(marginPx = 0): Bounds {
    const halfW = (this.widthPx / 2 + marginPx) * this.metresPerPixel;
    const halfH = (this.heightPx / 2 + marginPx) * this.metresPerPixel;
    return {
      minX: this.centreX - halfW,
      maxX: this.centreX + halfW,
      minY: this.centreY - halfH,
      maxY: this.centreY + halfH,
    };
  }

  /** Approximate geographic envelope of the current view, clamped to the model's domain. */
  visibleLatLonBounds(): { latMin: number; latMax: number; lonMin: number; lonMax: number } {
    const b = this.visibleBounds(20);
    let latMin = 90;
    let latMax = -90;
    let lonMin = 180;
    let lonMax = -180;
    const corners: Point[] = [
      { x: b.minX, y: b.minY },
      { x: b.maxX, y: b.minY },
      { x: b.minX, y: b.maxY },
      { x: b.maxX, y: b.maxY },
      { x: (b.minX + b.maxX) / 2, y: b.minY },
      { x: (b.minX + b.maxX) / 2, y: b.maxY },
      { x: b.minX, y: (b.minY + b.maxY) / 2 },
      { x: b.maxX, y: (b.minY + b.maxY) / 2 },
    ];
    const spansPole = b.minX < 0 && b.maxX > 0 && b.minY < 0 && b.maxY > 0;
    for (const c of corners) {
      const ll = fromEpsg3031(c.x, c.y);
      latMin = Math.min(latMin, ll.lat);
      latMax = Math.max(latMax, ll.lat);
      lonMin = Math.min(lonMin, ll.lon);
      lonMax = Math.max(lonMax, ll.lon);
    }
    if (spansPole) {
      latMin = -90;
      lonMin = -180;
      lonMax = 180;
    }
    return {
      latMin: Math.max(-89.5, latMin),
      latMax: Math.min(-30, Math.max(latMax, latMin + 1)),
      lonMin: Math.max(-180, lonMin),
      lonMax: Math.min(180, Math.max(lonMax, lonMin + 1)),
    };
  }

  /** Frame a set of coordinates with a pixel margin. Used by fit-to-route. */
  fitLatLon(
    points: { lat: number; lon: number }[],
    marginPx = 60,
    insets: { left: number; right: number; top: number; bottom: number } = { left: 0, right: 0, top: 0, bottom: 0 },
  ): void {
    if (points.length === 0) return;
    let minX = Infinity;
    let minY = Infinity;
    let maxX = -Infinity;
    let maxY = -Infinity;
    for (const p of points) {
      const xy = toEpsg3031(p.lat, p.lon);
      minX = Math.min(minX, xy.x);
      maxX = Math.max(maxX, xy.x);
      minY = Math.min(minY, xy.y);
      maxY = Math.max(maxY, xy.y);
    }
    const spanX = Math.max(1000, maxX - minX);
    const spanY = Math.max(1000, maxY - minY);
    // Frame inside the part of the canvas that no floating panel covers.
    const usableW = Math.max(80, this.widthPx - insets.left - insets.right - marginPx * 2);
    const usableH = Math.max(80, this.heightPx - insets.top - insets.bottom - marginPx * 2);
    this.metresPerPixel = Math.min(
      Viewport.MAX_MPP,
      Math.max(Viewport.MIN_MPP, Math.max(spanX / usableW, spanY / usableH)),
    );
    // Put the route's centre in the middle of the uncovered area, not of the whole canvas.
    this.centreX = (minX + maxX) / 2 - ((insets.left - insets.right) / 2) * this.metresPerPixel;
    this.centreY = (minY + maxY) / 2 + ((insets.top - insets.bottom) / 2) * this.metresPerPixel;
  }

  /** Nautical miles represented by one CSS pixel at the given latitude. */
  nmPerPixel(lat: number): number {
    // Local scale of the projection, from the derivative of the conformal radius.
    const d = 0.01;
    const a = toEpsg3031(lat, 0);
    const b = toEpsg3031(lat + d, 0);
    const metresPerDegLat = Math.hypot(b.x - a.x, b.y - a.y) / d;
    const trueMetresPerDeg = 111_132;
    const k = metresPerDegLat / trueMetresPerDeg;
    return (this.metresPerPixel / k / 1852) * 1;
  }

  equals(other: Viewport): boolean {
    return (
      Math.abs(this.metresPerPixel - other.metresPerPixel) < 1e-6 &&
      Math.abs(this.centreX - other.centreX) < 1e-3 &&
      Math.abs(this.centreY - other.centreY) < 1e-3 &&
      this.widthPx === other.widthPx &&
      this.heightPx === other.heightPx
    );
  }
}
