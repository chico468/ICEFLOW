/**
 * Canvas layer painters, applied bottom-up by the render loop.
 *
 * Each function takes the 2D context and the viewport and knows nothing about React, so
 * the whole scene stays a pure function of (data, viewport) and can be redrawn on demand.
 */
import type {
  CoastlineFeature,
  IceField,
  IcebergForecast,
  IcebergProfile,
  ObservedIceberg,
  Port,
  RadarSweep,
  Station,
  Waypoint,
} from '../api/types';
import {
  MAP_COLORS,
  changeCss,
  classedCss,
  compressionCss,
  concentrationCss,
  rioColor,
  thicknessCss,
  threatColor,
} from './palette';
import { scaleFactorAt, toEpsg3031 } from './projection';
import type { Viewport } from './viewport';

/**
 * concentration  continuous ramp
 * classes        the same data in five labelled bands (see ICE_BANDS), so the legend and map agree
 * thickness      ice thickness, metres
 * change         concentration at the shown lead time minus concentration at +0 h
 */
export type RasterMode = 'concentration' | 'classes' | 'thickness' | 'change';

const TAU = Math.PI * 2;

// ------------------------------------------------------------------------------ ground

export function drawBackground(ctx: CanvasRenderingContext2D, vp: Viewport): void {
  const g = ctx.createRadialGradient(
    vp.widthPx / 2,
    vp.heightPx / 2,
    0,
    vp.widthPx / 2,
    vp.heightPx / 2,
    Math.max(vp.widthPx, vp.heightPx) * 0.8,
  );
  g.addColorStop(0, MAP_COLORS.ocean);
  g.addColorStop(1, MAP_COLORS.oceanDeep);
  ctx.fillStyle = g;
  ctx.fillRect(0, 0, vp.widthPx, vp.heightPx);
}

// --------------------------------------------------------------------------- graticule

/** Parallels are circles about the pole; meridians are straight rays. Both are exact here. */
export function drawGraticule(ctx: CanvasRenderingContext2D, vp: Viewport): void {
  const mpp = vp.metresPerPixel;
  const latStep = mpp > 14000 ? 10 : mpp > 6000 ? 5 : mpp > 2000 ? 2 : 1;
  const lonStep = mpp > 14000 ? 30 : mpp > 6000 ? 15 : mpp > 2000 ? 10 : 5;
  const pole = vp.project(0, 0);

  ctx.save();
  ctx.lineWidth = 1;

  // Parallels
  for (let lat = -85; lat <= -35; lat += latStep) {
    const r = Math.hypot(toEpsg3031(lat, 0).x - 0, toEpsg3031(lat, 0).y - 0) / mpp;
    if (r < 4) continue;
    if (
      pole.x - r > vp.widthPx &&
      pole.x + r < 0 &&
      pole.y - r > vp.heightPx &&
      pole.y + r < 0
    )
      continue;
    const major = lat % (latStep * 2) === 0;
    ctx.strokeStyle = major ? MAP_COLORS.graticuleMajor : MAP_COLORS.graticule;
    ctx.beginPath();
    ctx.arc(pole.x, pole.y, r, 0, TAU);
    ctx.stroke();
  }

  // Meridians
  for (let lon = -180; lon < 180; lon += lonStep) {
    const inner = vp.lonLatToScreen(-88, lon);
    const outer = vp.lonLatToScreen(-35, lon);
    const major = ((lon + 360) % 90) === 0;
    ctx.strokeStyle = major ? MAP_COLORS.graticuleMajor : MAP_COLORS.graticule;
    ctx.beginPath();
    ctx.moveTo(inner.x, inner.y);
    ctx.lineTo(outer.x, outer.y);
    ctx.stroke();
  }

  // Labels: parallels along the central meridian ray, meridians at the frame edge.
  ctx.font = '10px ui-monospace, Consolas, monospace';
  ctx.fillStyle = MAP_COLORS.graticuleLabel;
  ctx.textAlign = 'left';
  ctx.textBaseline = 'middle';
  for (let lat = -85; lat <= -40; lat += latStep) {
    const p = vp.lonLatToScreen(lat, 0);
    if (p.x < -40 || p.x > vp.widthPx + 40 || p.y < 0 || p.y > vp.heightPx) continue;
    ctx.fillText(`${Math.abs(lat)}°S`, p.x + 4, p.y);
  }
  for (let lon = -180; lon < 180; lon += lonStep * 2) {
    const p = vp.lonLatToScreen(-42, lon);
    if (p.x < 8 || p.x > vp.widthPx - 30 || p.y < 8 || p.y > vp.heightPx - 8) continue;
    const label = lon === 0 ? '0°' : lon > 0 ? `${lon}°E` : `${-lon}°W`;
    ctx.fillText(label, p.x + 3, p.y);
  }
  ctx.restore();
}

// ------------------------------------------------------------------------- ice raster

/**
 * Per-cell fill of the ice grid.
 *
 * The grid arrives as [lat][lon] arrays on a regular lat/lon lattice; in EPSG:3031 each
 * cell is a curved quadrilateral, so each is drawn as a projected quad rather than an
 * axis-aligned rectangle. At the field resolutions the API returns (0.25 to 2 degrees)
 * this stays comfortably inside one frame's budget.
 */
export function drawIceRaster(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  field: IceField,
  mode: RasterMode,
  opacity: number,
  base: IceField | null = null,
): void {
  const { lats, lons } = field;
  if (lats.length < 2 || lons.length < 2) return;
  const values = mode === 'thickness' ? field.thickness_m : field.concentration;
  let baseValues: number[][] | null = null;
  if (mode === 'change') {
    // A difference is only meaningful on an identical grid. Refuse rather than misalign.
    const same =
      base !== null &&
      base.lats.length === lats.length &&
      base.lons.length === lons.length &&
      base.lats[0] === lats[0] &&
      base.lons[0] === lons[0];
    if (!same || !base) return;
    baseValues = base.concentration;
  }

  ctx.save();
  ctx.globalAlpha = opacity;
  for (let i = 0; i < lats.length - 1; i += 1) {
    const rowA = values[i];
    if (!rowA) continue;
    for (let j = 0; j < lons.length - 1; j += 1) {
      const v = rowA[j];
      if (v === undefined) continue;
      let fill: string | null;
      if (mode === 'change') {
        const b = baseValues?.[i]?.[j];
        if (b === undefined) continue;
        fill = changeCss(v - b);
      } else {
        if ((mode === 'concentration' || mode === 'classes') && v < 0.03) continue;
        if (mode === 'thickness' && v < 0.01) continue;
        fill = mode === 'thickness' ? thicknessCss(v) : mode === 'classes' ? classedCss(v) : concentrationCss(v);
      }
      if (fill === null) continue;

      const p0 = vp.lonLatToScreen(lats[i], lons[j]);
      const p1 = vp.lonLatToScreen(lats[i], lons[j + 1]);
      const p2 = vp.lonLatToScreen(lats[i + 1], lons[j + 1]);
      const p3 = vp.lonLatToScreen(lats[i + 1], lons[j]);
      const minX = Math.min(p0.x, p1.x, p2.x, p3.x);
      const maxX = Math.max(p0.x, p1.x, p2.x, p3.x);
      const minY = Math.min(p0.y, p1.y, p2.y, p3.y);
      const maxY = Math.max(p0.y, p1.y, p2.y, p3.y);
      if (maxX < -8 || minX > vp.widthPx + 8 || maxY < -8 || minY > vp.heightPx + 8) continue;

      ctx.fillStyle = fill;
      ctx.beginPath();
      ctx.moveTo(p0.x, p0.y);
      ctx.lineTo(p1.x, p1.y);
      ctx.lineTo(p2.x, p2.y);
      ctx.lineTo(p3.x, p3.y);
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.restore();
}

/**
 * The 15 percent ice edge, the operational boundary every ice chart marks.
 * Drawn from the field's own `ice_edge_lat` column so it agrees with the backend exactly.
 */
export function drawIceEdge(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  lons: number[],
  edgeLat: number[],
): void {
  if (lons.length < 2) return;
  const trace = (): void => {
    ctx.beginPath();
    let started = false;
    for (let i = 0; i < lons.length; i += 1) {
      const lat = edgeLat[i];
      if (lat === undefined || !Number.isFinite(lat)) {
        started = false;
        continue;
      }
      const p = vp.lonLatToScreen(lat, lons[i]);
      if (!started) {
        ctx.moveTo(p.x, p.y);
        started = true;
      } else {
        ctx.lineTo(p.x, p.y);
      }
    }
  };
  ctx.save();
  ctx.setLineDash([]);
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  // A pale casing under the blue line keeps the edge readable where it crosses dense, dark ice
  // and where it runs over the route; the line alone disappears into the 70 percent and up ramp.
  ctx.strokeStyle = MAP_COLORS.iceEdgeCasing;
  ctx.lineWidth = 4.2;
  trace();
  ctx.stroke();
  ctx.strokeStyle = MAP_COLORS.iceEdge;
  ctx.lineWidth = 1.8;
  trace();
  ctx.stroke();
  ctx.restore();
}

/** Compression / besetting shading, hatched so it reads differently from the raster. */
export function drawCompression(ctx: CanvasRenderingContext2D, vp: Viewport, field: IceField): void {
  const { lats, lons, compression_index: comp, concentration } = field;
  ctx.save();
  for (let i = 0; i < lats.length - 1; i += 1) {
    const row = comp[i];
    const conc = concentration[i];
    if (!row || !conc) continue;
    for (let j = 0; j < lons.length - 1; j += 1) {
      const c = row[j];
      // Compression only matters where there is ice to be compressed against.
      if (c === undefined || (conc[j] ?? 0) < 0.4) continue;
      const css = compressionCss(c);
      if (!css) continue;
      const p0 = vp.lonLatToScreen(lats[i], lons[j]);
      const p2 = vp.lonLatToScreen(lats[i + 1], lons[j + 1]);
      const x = Math.min(p0.x, p2.x);
      const y = Math.min(p0.y, p2.y);
      const w = Math.abs(p2.x - p0.x);
      const h = Math.abs(p2.y - p0.y);
      if (x + w < 0 || x > vp.widthPx || y + h < 0 || y > vp.heightPx) continue;
      ctx.fillStyle = css;
      ctx.fillRect(x, y, Math.max(1, w), Math.max(1, h));
    }
  }
  ctx.restore();
}

// ------------------------------------------------------------------------------- land

export function drawLand(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  features: CoastlineFeature[],
): void {
  ctx.save();
  ctx.fillStyle = MAP_COLORS.land;
  ctx.strokeStyle = MAP_COLORS.landEdge;
  ctx.lineWidth = 1;
  ctx.lineJoin = 'round';
  for (const f of features) {
    for (const ring of f.geometry.coordinates) {
      if (ring.length < 3) continue;
      ctx.beginPath();
      for (let i = 0; i < ring.length; i += 1) {
        const c = ring[i];
        const p = vp.lonLatToScreen(c[1], c[0]);
        if (i === 0) ctx.moveTo(p.x, p.y);
        else ctx.lineTo(p.x, p.y);
      }
      ctx.closePath();
      ctx.fill();
      ctx.stroke();
    }
  }
  ctx.restore();
}

// ------------------------------------------------------------------------ drift vectors

/** Ice-drift barbs. Length is proportional to speed; the head marks the direction of travel. */
export function drawDriftField(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  field: IceField,
  strideOverride?: number,
): void {
  const { lats, lons } = field;
  const stride = strideOverride ?? Math.max(1, Math.round(28 / Math.max(1, vp.widthPx / lons.length)));
  ctx.save();
  ctx.strokeStyle = MAP_COLORS.drift;
  ctx.fillStyle = MAP_COLORS.drift;
  ctx.lineWidth = 1;
  for (let i = 0; i < lats.length; i += stride) {
    for (let j = 0; j < lons.length; j += stride) {
      const u = field.drift_u_ms[i]?.[j];
      const v = field.drift_v_ms[i]?.[j];
      const conc = field.concentration[i]?.[j] ?? 0;
      if (u === undefined || v === undefined || conc < 0.15) continue;
      const speed = Math.hypot(u, v);
      if (speed < 0.01) continue;

      const origin = vp.lonLatToScreen(lats[i], lons[j]);
      if (origin.x < -20 || origin.x > vp.widthPx + 20 || origin.y < -20 || origin.y > vp.heightPx + 20)
        continue;
      // Step a short distance along the drift bearing and project the endpoint, so the
      // arrow follows the projection's local rotation instead of assuming screen north.
      const dLat = (v * 3600 * 6) / 111_132;
      const dLon =
        (u * 3600 * 6) / (111_320 * Math.max(0.05, Math.cos((lats[i] * Math.PI) / 180)));
      const tip = vp.lonLatToScreen(lats[i] + dLat, lons[j] + dLon);
      const len = Math.hypot(tip.x - origin.x, tip.y - origin.y);
      const cap = Math.min(26, 6 + speed * 45);
      const k = len > 0.001 ? cap / len : 0;
      const ex = origin.x + (tip.x - origin.x) * k;
      const ey = origin.y + (tip.y - origin.y) * k;

      ctx.globalAlpha = Math.min(0.9, 0.25 + speed * 2.2);
      ctx.beginPath();
      ctx.moveTo(origin.x, origin.y);
      ctx.lineTo(ex, ey);
      ctx.stroke();
      const ang = Math.atan2(ey - origin.y, ex - origin.x);
      ctx.beginPath();
      ctx.moveTo(ex, ey);
      ctx.lineTo(ex - 4 * Math.cos(ang - 0.42), ey - 4 * Math.sin(ang - 0.42));
      ctx.lineTo(ex - 4 * Math.cos(ang + 0.42), ey - 4 * Math.sin(ang + 0.42));
      ctx.closePath();
      ctx.fill();
    }
  }
  ctx.restore();
}

// ---------------------------------------------------------------------------- icebergs

function kmToPixels(km: number, lat: number, vp: Viewport): number {
  // Convert a true-ground distance into projected metres before dividing by the scale.
  return (km * 1000 * scaleFactorAt(lat)) / vp.metresPerPixel;
}

export function drawIcebergs(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  bergs: IcebergProfile[],
  selectedId: string | null,
): void {
  ctx.save();
  ctx.font = '10px ui-monospace, Consolas, monospace';
  for (const berg of bergs) {
    const lat = berg.forecast_latitude ?? berg.latitude;
    const lon = berg.forecast_longitude ?? berg.longitude;
    const p = vp.lonLatToScreen(lat, lon);
    if (p.x < -60 || p.x > vp.widthPx + 60 || p.y < -60 || p.y > vp.heightPx + 60) continue;
    const selected = berg.berg_id === selectedId;
    // A giant berg is tens of kilometres across: draw its true footprint when it is
    // larger than the marker, otherwise draw the marker.
    const footprintPx = kmToPixels(berg.length_m / 2000, lat, vp);
    const r = Math.max(4, Math.min(60, footprintPx));

    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, TAU);
    ctx.fillStyle = selected ? 'rgba(91, 63, 209, 0.26)' : 'rgba(91, 63, 209, 0.14)';
    ctx.fill();
    ctx.strokeStyle = selected ? MAP_COLORS.icebergCore : MAP_COLORS.iceberg;
    ctx.lineWidth = selected ? 1.8 : 1;
    ctx.stroke();

    ctx.fillStyle = selected ? MAP_COLORS.icebergCore : 'rgba(196, 181, 253, 0.9)';
    ctx.fillText(berg.berg_id, p.x + r + 4, p.y + 3);
  }
  ctx.restore();
}

/**
 * The observed iceberg snapshot. Drawn as a hollow dashed diamond and an equivalent-area circle,
 * so it can never be mistaken for the filled, simulated catalogue. The circle is the circle with the
 * same area as the reported footprint: orientation is not in the data, so no shape is implied.
 * Stale snapshots are drawn fainter. Labels appear only when zoomed in enough to avoid clutter.
 */
export function drawObservedIcebergs(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  bergs: ObservedIceberg[],
  stale: boolean,
  tag: string,
): void {
  ctx.save();
  ctx.font = '10px ui-monospace, Consolas, monospace';
  ctx.strokeStyle = stale ? MAP_COLORS.observedBergStale : MAP_COLORS.observedBerg;
  ctx.fillStyle = ctx.strokeStyle;
  const showLabels = vp.metresPerPixel < 16000;
  for (const b of bergs) {
    const p = vp.lonLatToScreen(b.latitude, b.longitude);
    if (p.x < -80 || p.x > vp.widthPx + 80 || p.y < -80 || p.y > vp.heightPx + 80) continue;
    const radiusKm = Math.sqrt(b.area_sqkm / Math.PI);
    const rPx = Math.min(140, kmToPixels(radiusKm, b.latitude, vp));
    if (rPx > 5) {
      ctx.setLineDash([5, 4]);
      ctx.lineWidth = 1;
      ctx.beginPath();
      ctx.arc(p.x, p.y, rPx, 0, TAU);
      ctx.stroke();
    }
    ctx.setLineDash([]);
    ctx.lineWidth = 1.5;
    ctx.beginPath();
    ctx.moveTo(p.x, p.y - 5);
    ctx.lineTo(p.x + 5, p.y);
    ctx.lineTo(p.x, p.y + 5);
    ctx.lineTo(p.x - 5, p.y);
    ctx.closePath();
    ctx.stroke();
    if (showLabels) ctx.fillText(`${b.id} ${tag}`, p.x + 9, p.y + 3);
  }
  ctx.restore();
}

/**
 * Ensemble drift track with 50 and 90 percent uncertainty ellipses.
 *
 * The tracker reports circular uncertainty radii, so the ellipses are circles in true
 * ground distance. They are still ellipses on screen, because the projection stretches
 * them away from the standard parallel, which is exactly the honest depiction.
 */
export function drawIcebergDrift(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  forecast: IcebergForecast,
): void {
  const traj = forecast.trajectory;
  if (traj.length < 2) return;
  ctx.save();

  for (let i = traj.length - 1; i >= 0; i -= 1) {
    const t = traj[i];
    if (t.uncertainty_radius_90_km <= 0) continue;
    const p = vp.lonLatToScreen(t.latitude, t.longitude);
    const r90 = kmToPixels(t.uncertainty_radius_90_km, t.latitude, vp);
    const r50 = kmToPixels(t.uncertainty_radius_50_km, t.latitude, vp);
    if (r90 < 1.5) continue;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r90, 0, TAU);
    ctx.fillStyle = 'rgba(91, 63, 209, 0.09)';
    ctx.fill();
    ctx.strokeStyle = 'rgba(91, 63, 209, 0.35)';
    ctx.lineWidth = 1;
    ctx.setLineDash([3, 3]);
    ctx.stroke();
    ctx.setLineDash([]);
    ctx.beginPath();
    ctx.arc(p.x, p.y, r50, 0, TAU);
    ctx.fillStyle = 'rgba(91, 63, 209, 0.15)';
    ctx.fill();
  }

  ctx.beginPath();
  for (let i = 0; i < traj.length; i += 1) {
    const p = vp.lonLatToScreen(traj[i].latitude, traj[i].longitude);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.strokeStyle = '#5B3FD1';
  ctx.lineWidth = 1.6;
  ctx.stroke();

  ctx.fillStyle = '#3A2790';
  for (const t of traj) {
    if (t.hour % 24 !== 0) continue;
    const p = vp.lonLatToScreen(t.latitude, t.longitude);
    ctx.beginPath();
    ctx.arc(p.x, p.y, 2.5, 0, TAU);
    ctx.fill();
  }
  ctx.restore();
}

// ------------------------------------------------------------------------------- routes

export function drawRoute(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  waypoints: Waypoint[],
  opts: { dashed?: boolean; color?: string; width?: number; rioColored?: boolean } = {},
): void {
  if (waypoints.length < 2) return;
  ctx.save();
  ctx.lineJoin = 'round';
  ctx.lineCap = 'round';
  ctx.lineWidth = opts.width ?? 2;
  if (opts.dashed) ctx.setLineDash([7, 5]);

  if (opts.rioColored) {
    // Segment-by-segment so the POLARIS state along the leg is visible on the chart.
    for (let i = 0; i < waypoints.length - 1; i += 1) {
      const a = vp.lonLatToScreen(waypoints[i].latitude, waypoints[i].longitude);
      const b = vp.lonLatToScreen(waypoints[i + 1].latitude, waypoints[i + 1].longitude);
      ctx.strokeStyle = rioColor(Math.min(waypoints[i].rio_score, waypoints[i + 1].rio_score));
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
    }
  } else {
    ctx.strokeStyle = opts.color ?? MAP_COLORS.routeOptimised;
    ctx.beginPath();
    for (let i = 0; i < waypoints.length; i += 1) {
      const p = vp.lonLatToScreen(waypoints[i].latitude, waypoints[i].longitude);
      if (i === 0) ctx.moveTo(p.x, p.y);
      else ctx.lineTo(p.x, p.y);
    }
    ctx.stroke();
  }
  ctx.setLineDash([]);

  // Waypoint dots at a readable density only.
  if (vp.metresPerPixel < 12_000) {
    const step = Math.max(1, Math.round(waypoints.length / 40));
    for (let i = 0; i < waypoints.length; i += step) {
      const w = waypoints[i];
      const p = vp.lonLatToScreen(w.latitude, w.longitude);
      ctx.beginPath();
      ctx.arc(p.x, p.y, 2.2, 0, TAU);
      ctx.fillStyle = opts.rioColored ? rioColor(w.rio_score) : (opts.color ?? MAP_COLORS.routeOptimised);
      ctx.fill();
    }
  }
  ctx.restore();
}

export function drawTrack(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  track: [number, number][],
): void {
  if (track.length < 2) return;
  ctx.save();
  ctx.strokeStyle = MAP_COLORS.track;
  ctx.lineWidth = 2.4;
  ctx.lineJoin = 'round';
  ctx.shadowColor = 'rgba(31, 122, 77, 0.35)';
  ctx.shadowBlur = 5;
  ctx.beginPath();
  for (let i = 0; i < track.length; i += 1) {
    const p = vp.lonLatToScreen(track[i][0], track[i][1]);
    if (i === 0) ctx.moveTo(p.x, p.y);
    else ctx.lineTo(p.x, p.y);
  }
  ctx.stroke();
  ctx.restore();
}

// ------------------------------------------------------------------------------- vessel

export function drawVessel(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  lat: number,
  lon: number,
  headingDeg: number,
): void {
  const p = vp.lonLatToScreen(lat, lon);
  // Screen-space heading: step 0.05 degrees along the true bearing and re-project, so the
  // marker points where the ship is actually going under the projection's rotation.
  const rad = (headingDeg * Math.PI) / 180;
  const dLat = (0.05 * Math.cos(rad));
  const dLon = (0.05 * Math.sin(rad)) / Math.max(0.05, Math.cos((lat * Math.PI) / 180));
  const ahead = vp.lonLatToScreen(lat + dLat, lon + dLon);
  const screenAngle = Math.atan2(ahead.y - p.y, ahead.x - p.x);

  ctx.save();
  ctx.translate(p.x, p.y);

  ctx.beginPath();
  ctx.arc(0, 0, 13, 0, TAU);
  ctx.fillStyle = 'rgba(11, 92, 142, 0.12)';
  ctx.fill();
  ctx.strokeStyle = 'rgba(11, 92, 142, 0.6)';
  ctx.lineWidth = 1;
  ctx.stroke();

  ctx.rotate(screenAngle);
  ctx.beginPath();
  ctx.moveTo(11, 0);
  ctx.lineTo(-6, 6);
  ctx.lineTo(-3.5, 0);
  ctx.lineTo(-6, -6);
  ctx.closePath();
  ctx.fillStyle = MAP_COLORS.vessel;
  ctx.fill();
  ctx.strokeStyle = '#0E2433';
  ctx.lineWidth = 1;
  ctx.stroke();

  // Heading line
  ctx.beginPath();
  ctx.moveTo(13, 0);
  ctx.lineTo(34, 0);
  ctx.strokeStyle = 'rgba(14, 36, 51, 0.6)';
  ctx.setLineDash([3, 3]);
  ctx.stroke();
  ctx.restore();
}

/** Radar range rings around the ship, labelled in nautical miles. */
export function drawRadarRings(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  lat: number,
  lon: number,
  maxRangeNm: number,
  sweep: RadarSweep | null,
): void {
  const p = vp.lonLatToScreen(lat, lon);
  const nmPerPx = vp.nmPerPixel(lat);
  if (nmPerPx <= 0) return;
  ctx.save();
  ctx.strokeStyle = MAP_COLORS.radar;
  ctx.setLineDash([2, 4]);
  ctx.lineWidth = 1;
  ctx.font = '9px ui-monospace, Consolas, monospace';
  ctx.fillStyle = 'rgba(31, 122, 77, 0.85)';
  for (let nm = 2; nm <= maxRangeNm; nm += 2) {
    const r = nm / nmPerPx;
    if (r < 8 || r > Math.max(vp.widthPx, vp.heightPx)) continue;
    ctx.beginPath();
    ctx.arc(p.x, p.y, r, 0, TAU);
    ctx.stroke();
    ctx.fillText(`${nm} nm`, p.x + r * 0.7, p.y - r * 0.7);
  }
  ctx.setLineDash([]);
  if (sweep) {
    for (const c of sweep.contacts) {
      const cp = vp.lonLatToScreen(c.latitude, c.longitude);
      ctx.beginPath();
      ctx.arc(cp.x, cp.y, 2, 0, TAU);
      ctx.fillStyle = threatColor(c.threat_level);
      ctx.fill();
    }
  }
  ctx.restore();
}

// ------------------------------------------------------------------------------- labels

export function drawStations(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  stations: Station[],
  ports: Port[],
): void {
  ctx.save();
  ctx.font = '10px ui-sans-serif, system-ui, sans-serif';
  ctx.textBaseline = 'middle';

  // Label decluttering.
  //
  // Seven stations sit within a few hundred kilometres of each other along Queen Maud Land and
  // Prydz Bay - which is precisely the region this system is about - and drawing every label
  // turned that coastline into an unreadable smear. Claimed rectangles are tracked as labels are
  // drawn, and a label whose box would collide with one already placed is dropped. Its marker is
  // always drawn, so nothing disappears from the chart; only the text yields.
  //
  // Indian stations are painted first so that when something has to give way, it is never one of
  // the two the operator actually cares about.
  const claimed: { x: number; y: number; w: number; h: number }[] = [];
  const collides = (x: number, y: number, w: number, h: number): boolean =>
    claimed.some((r) => x < r.x + r.w && x + w > r.x && y < r.y + r.h && y + h > r.y);

  const paint = (
    lat: number,
    lon: number,
    label: string,
    color: string,
    square: boolean,
    dim: boolean,
    priority = false,
  ): void => {
    const p = vp.lonLatToScreen(lat, lon);
    if (p.x < -80 || p.x > vp.widthPx + 80 || p.y < -30 || p.y > vp.heightPx + 30) return;
    ctx.globalAlpha = dim ? 0.55 : 1;
    ctx.fillStyle = color;
    if (square) {
      ctx.fillRect(p.x - 3, p.y - 3, 6, 6);
    } else {
      ctx.beginPath();
      ctx.arc(p.x, p.y, 3.4, 0, TAU);
      ctx.fill();
    }

    const w = ctx.measureText(label).width;
    const box = { x: p.x + 6, y: p.y - 6, w: w + 4, h: 12 };
    if (!priority && collides(box.x, box.y, box.w, box.h)) {
      ctx.globalAlpha = 1;
      return;
    }
    claimed.push(box);

    ctx.strokeStyle = 'rgba(244, 248, 250, 0.92)';
    ctx.lineWidth = 3;
    ctx.strokeText(label, p.x + 7, p.y);
    ctx.fillStyle = dim ? 'rgba(61, 86, 102, 0.8)' : '#0E2433';
    ctx.fillText(label, p.x + 7, p.y);
    ctx.globalAlpha = 1;
  };

  const ordered = [...stations].sort((a, b) => Number(b.is_indian) - Number(a.is_indian));
  for (const s of ordered) {
    paint(
      s.latitude,
      s.longitude,
      s.name,
      s.is_indian ? MAP_COLORS.station : '#6B7F8C',
      true,
      !s.is_indian,
      Boolean(s.is_indian),
    );
    if (s.station_is_inland) {
      // The anchorage is where the ship actually goes; show the pair so the difference is
      // visible on the chart rather than buried in a footnote.
      const a = vp.lonLatToScreen(s.anchorage_lat, s.anchorage_lon);
      const b = vp.lonLatToScreen(s.latitude, s.longitude);
      ctx.strokeStyle = 'rgba(15, 118, 110, 0.5)';
      ctx.lineWidth = 1;
      ctx.setLineDash([3, 3]);
      ctx.beginPath();
      ctx.moveTo(a.x, a.y);
      ctx.lineTo(b.x, b.y);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.arc(a.x, a.y, 3, 0, TAU);
      ctx.fillStyle = MAP_COLORS.station;
      ctx.fill();
    }
  }
  for (const p of ports) {
    paint(p.latitude, p.longitude, p.name, MAP_COLORS.port, false, false);
  }
  ctx.restore();
}

/** Scale bar, bottom-left, computed from the true local scale at the view centre. */
export function drawScaleBar(ctx: CanvasRenderingContext2D, vp: Viewport): void {
  const centre = vp.screenToLatLon(vp.widthPx / 2, vp.heightPx / 2);
  const nmPerPx = vp.nmPerPixel(centre.lat);
  if (!Number.isFinite(nmPerPx) || nmPerPx <= 0) return;
  const targetPx = 130;
  const roughNm = nmPerPx * targetPx;
  const magnitude = Math.pow(10, Math.floor(Math.log10(roughNm)));
  const nice = [1, 2, 5, 10].map((m) => m * magnitude).find((v) => v >= roughNm) ?? 10 * magnitude;
  const px = nice / nmPerPx;
  const x = 14 + vp.insetLeft;
  const y = vp.heightPx - 18 - vp.insetBottom;

  ctx.save();
  ctx.strokeStyle = 'rgba(14, 36, 51, 0.8)';
  ctx.fillStyle = 'rgba(14, 36, 51, 0.9)';
  ctx.lineWidth = 1;
  ctx.beginPath();
  ctx.moveTo(x, y - 4);
  ctx.lineTo(x, y);
  ctx.lineTo(x + px, y);
  ctx.lineTo(x + px, y - 4);
  ctx.stroke();
  ctx.font = '12px "Avenir Next", system-ui, sans-serif';
  ctx.fillText(`${nice >= 1 ? nice.toFixed(0) : nice.toFixed(1)} nm`, x + px + 6, y);
  ctx.restore();
}

/** Crosshair and coordinate readout for the inspected point. */
export function drawInspectMarker(
  ctx: CanvasRenderingContext2D,
  vp: Viewport,
  lat: number,
  lon: number,
): void {
  const p = vp.lonLatToScreen(lat, lon);
  ctx.save();
  ctx.strokeStyle = '#B45309';
  ctx.lineWidth = 1.6;
  ctx.beginPath();
  ctx.arc(p.x, p.y, 8, 0, TAU);
  ctx.moveTo(p.x - 14, p.y);
  ctx.lineTo(p.x - 4, p.y);
  ctx.moveTo(p.x + 4, p.y);
  ctx.lineTo(p.x + 14, p.y);
  ctx.moveTo(p.x, p.y - 14);
  ctx.lineTo(p.x, p.y - 4);
  ctx.moveTo(p.x, p.y + 4);
  ctx.lineTo(p.x, p.y + 14);
  ctx.stroke();
  ctx.restore();
}
