/**
 * Colour ramps for the chart layers.
 *
 * The bridge runs at night, so the ramps stay inside a cold, low-luminance envelope, and
 * hazard hues (amber, red) are reserved so that anything warm on the display means
 * something. Every ramp is defined once here and used by both the canvas and the panels,
 * so a legend can never drift from what is painted.
 */

export const MAP_COLORS = {
  // A daylight chart: pale glacial water, sand-grey land, deep-ink lines. Mirrors the CSS tokens
  // in src/index.css (the canvas cannot read CSS variables), so change the two together.
  ocean: '#D4E6EF',
  oceanDeep: '#C6DCE8',
  land: '#DDD6C8',
  landEdge: '#8F8574',
  graticule: 'rgba(30, 70, 100, 0.14)',
  graticuleMajor: 'rgba(30, 70, 100, 0.26)',
  graticuleLabel: 'rgba(30, 70, 100, 0.82)',
  iceEdge: '#1B6A9C',
  drift: 'rgba(27, 106, 156, 0.55)',
  routeOptimised: '#C2410C',
  routeBaseline: 'rgba(60, 80, 92, 0.75)',
  track: '#1F7A4D',
  vessel: '#FFFFFF',
  iceberg: '#5B3FD1',
  icebergCore: '#3A2790',
  station: '#0F766E',
  port: '#8A6D00',
  radar: 'rgba(31, 122, 77, 0.5)',
  compression: '#B45309',
  // Observed (not simulated) iceberg snapshot: hollow, dashed, muted, so it never reads as live.
  observedBerg: '#6B5B95',
  observedBergStale: 'rgba(107, 91, 149, 0.62)',
  iceEdgeCasing: 'rgba(255, 255, 255, 0.72)',
} as const;

function lerp(a: number, b: number, t: number): number {
  return a + (b - a) * t;
}

function mix(c1: [number, number, number], c2: [number, number, number], t: number): [number, number, number] {
  return [lerp(c1[0], c2[0], t), lerp(c1[1], c2[1], t), lerp(c1[2], c2[2], t)];
}

function rampLookup(stops: { at: number; rgb: [number, number, number] }[], v: number): [number, number, number] {
  const x = Math.min(1, Math.max(0, v));
  for (let i = 0; i < stops.length - 1; i += 1) {
    const a = stops[i];
    const b = stops[i + 1];
    if (x >= a.at && x <= b.at) {
      const t = b.at === a.at ? 0 : (x - a.at) / (b.at - a.at);
      return mix(a.rgb, b.rgb, t);
    }
  }
  return stops[stops.length - 1].rgb;
}

/**
 * Sea-ice concentration, 0 to 1.
 * Open water reads as the ocean ground so the eye is not drawn to it; pack ice brightens
 * through a cold blue-white, which is how ice charts have been drawn since the 1970s.
 */
const CONC_STOPS: { at: number; rgb: [number, number, number] }[] = [
  { at: 0.0, rgb: [212, 230, 239] },
  { at: 0.15, rgb: [186, 214, 230] },
  { at: 0.35, rgb: [150, 190, 214] },
  { at: 0.55, rgb: [104, 160, 194] },
  { at: 0.75, rgb: [58, 118, 160] },
  { at: 0.9, rgb: [30, 82, 125] },
  { at: 1.0, rgb: [16, 56, 96] },
];

export function concentrationRgb(v: number): [number, number, number] {
  return rampLookup(CONC_STOPS, v);
}

export function concentrationCss(v: number, alpha = 1): string {
  const [r, g, b] = concentrationRgb(v);
  return `rgba(${r | 0},${g | 0},${b | 0},${alpha})`;
}

/** Ice thickness in metres, 0 to about 3. Used for the alternate raster. */
const THICK_STOPS: { at: number; rgb: [number, number, number] }[] = [
  { at: 0.0, rgb: [212, 230, 239] },
  { at: 0.1, rgb: [170, 210, 205] },
  { at: 0.3, rgb: [112, 180, 160] },
  { at: 0.55, rgb: [180, 190, 90] },
  { at: 0.8, rgb: [210, 140, 60] },
  { at: 1.0, rgb: [130, 60, 40] },
];

export function thicknessCss(metres: number, alpha = 1): string {
  const [r, g, b] = rampLookup(THICK_STOPS, metres / 3);
  return `rgba(${r | 0},${g | 0},${b | 0},${alpha})`;
}

/**
 * Display classes for sea-ice concentration.
 *
 * These are plain bands for reading the chart, not a WMO egg-code decision. The 15 percent
 * boundary is the ice-edge threshold this model uses; the others are round numbers chosen for legibility.
 * The legend and the "classes" raster both read this one table, so they cannot disagree.
 */
export interface IceBand {
  key: 'open' | 'low' | 'moderate' | 'dense' | 'veryDense';
  label: string;
  /** Inclusive lower and exclusive upper bound, as a 0 to 1 fraction. */
  from: number;
  to: number;
}

export const ICE_BANDS: readonly IceBand[] = [
  { key: 'open', label: 'Open water / trace', from: 0, to: 0.15 },
  { key: 'low', label: 'Low concentration', from: 0.15, to: 0.4 },
  { key: 'moderate', label: 'Moderate', from: 0.4, to: 0.7 },
  { key: 'dense', label: 'Dense', from: 0.7, to: 0.9 },
  { key: 'veryDense', label: 'Very dense / consolidated', from: 0.9, to: 1.0000001 },
];

export function iceBandOf(concentration: number): IceBand {
  const c = Math.min(1, Math.max(0, concentration));
  return ICE_BANDS.find((b) => c >= b.from && c < b.to) ?? ICE_BANDS[ICE_BANDS.length - 1];
}

/** Colour of a band: the continuous ramp sampled at the middle of the band. */
export function bandCss(band: IceBand, alpha = 1): string {
  return concentrationCss((band.from + Math.min(1, band.to)) / 2, alpha);
}

/** The "classes" raster: each cell takes its band's single colour. */
export function classedCss(concentration: number): string {
  return bandCss(iceBandOf(concentration));
}

/**
 * Change in concentration between two forecast times, -1 to +1.
 * Diverging: teal where ice has retreated, indigo where it has advanced. Neither is amber or red,
 * which stay reserved for hazard. A dead band around zero stays transparent so noise is not painted.
 */
export const CHANGE_DEADBAND = 0.03;

export function changeCss(delta: number): string | null {
  if (!Number.isFinite(delta) || Math.abs(delta) < CHANGE_DEADBAND) return null;
  const t = Math.min(1, Math.abs(delta) / 0.5);
  return delta > 0
    ? `rgba(67, 56, 202, ${(0.25 + 0.65 * t).toFixed(3)})`
    : `rgba(13, 148, 136, ${(0.25 + 0.65 * t).toFixed(3)})`;
}

/**
 * RIO to colour, following the POLARIS decision boundaries rather than a smooth ramp:
 * at or above 0 is normal operation, 0 to -10 is elevated risk, below -10 is prohibited.
 */
export function rioColor(rio: number): string {
  if (rio >= 10) return '#1F7A4D';
  if (rio >= 0) return '#4D7C0F';
  if (rio >= -5) return '#A16207';
  if (rio > -10) return '#C2410C';
  return '#B3261E';
}

export function rioStatusLabel(rio: number): string {
  if (rio >= 0) return 'NORMAL OPERATION';
  if (rio > -10) return 'ELEVATED RISK';
  return 'OPERATION PROHIBITED';
}

/** Compression / besetting shading: transparent below 0.35, hot above it. */
export function compressionCss(index: number): string | null {
  if (index < 0.35) return null;
  const t = Math.min(1, (index - 0.35) / 0.65);
  const r = lerp(196, 179, t);
  const g = lerp(120, 38, t);
  const b = lerp(30, 30, t);
  return `rgba(${r | 0},${g | 0},${b | 0},${(0.1 + 0.4 * t).toFixed(3)})`;
}

export function severityColor(severity: string): string {
  switch (severity.toUpperCase()) {
    case 'CRITICAL':
      return '#B3261E';
    case 'WARNING':
      return '#C2410C';
    case 'CAUTION':
      return '#A16207';
    default:
      return '#0B5C8E';
  }
}

export function threatColor(level: string): string {
  switch (level.toUpperCase()) {
    case 'CRITICAL':
      return '#B3261E';
    case 'HIGH':
      return '#C2410C';
    case 'MODERATE':
      return '#A16207';
    case 'LOW':
      return '#1F7A4D';
    default:
      return '#0B5C8E';
  }
}

export function besettingColor(risk: string): string {
  switch (risk.toUpperCase()) {
    case 'SEVERE':
    case 'HIGH':
      return '#B3261E';
    case 'MODERATE':
      return '#A16207';
    default:
      return '#1F7A4D';
  }
}
