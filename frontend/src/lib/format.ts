/**
 * Number formatting. Every figure that reaches the screen goes through here, because the
 * design rule is that no number is ever shown without its unit.
 */

export function num(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return value.toFixed(digits);
}

export function int(value: number | null | undefined): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return Math.round(value).toLocaleString('en-IN');
}

export function signed(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return `${value > 0 ? '+' : ''}${value.toFixed(digits)}`;
}

export function pct(fraction01: number | null | undefined, digits = 0): string {
  if (fraction01 === null || fraction01 === undefined || !Number.isFinite(fraction01)) return '--';
  return `${(fraction01 * 100).toFixed(digits)} %`;
}

/** A value already expressed in percent (the API returns several of these). */
export function pctValue(value: number | null | undefined, digits = 1): string {
  if (value === null || value === undefined || !Number.isFinite(value)) return '--';
  return `${value.toFixed(digits)} %`;
}

export function bytes(n: number | null | undefined): string {
  if (n === null || n === undefined || !Number.isFinite(n)) return '--';
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} kB`;
  return `${(n / (1024 * 1024)).toFixed(2)} MB`;
}

/** Hours as a days-and-hours reading, which is how a passage plan is actually read. */
export function hoursToDhm(hours: number | null | undefined): string {
  if (hours === null || hours === undefined || !Number.isFinite(hours)) return '--';
  const total = Math.max(0, hours);
  const d = Math.floor(total / 24);
  const h = Math.floor(total % 24);
  const m = Math.round((total - Math.floor(total)) * 60);
  if (d > 0) return `${d} d ${h.toString().padStart(2, '0')} h`;
  return `${h} h ${m.toString().padStart(2, '0')} m`;
}

export function bearing(deg: number | null | undefined): string {
  if (deg === null || deg === undefined || !Number.isFinite(deg)) return '--';
  return `${(((deg % 360) + 360) % 360).toFixed(0).padStart(3, '0')}°`;
}

const CARDINALS = [
  'N', 'NNE', 'NE', 'ENE', 'E', 'ESE', 'SE', 'SSE',
  'S', 'SSW', 'SW', 'WSW', 'W', 'WNW', 'NW', 'NNW',
];

export function cardinal(deg: number): string {
  return CARDINALS[Math.round((((deg % 360) + 360) % 360) / 22.5) % 16];
}

/** Concentration expressed in tenths, the convention every ice chart uses. */
export function tenths(concentration01: number): string {
  return `${Math.round(concentration01 * 10)}/10`;
}

/** WMO stage names arrive as enum keys; make them readable without losing the term. */
export function iceTypeLabel(key: string): string {
  return key.replace(/_/g, ' ').replace(/\bStage (\d)\b/, 'stage $1');
}

export function shortIso(iso: string | null | undefined): string {
  if (!iso) return '--';
  const d = new Date(iso);
  if (Number.isNaN(d.getTime())) return iso;
  const pad = (n: number): string => n.toString().padStart(2, '0');
  return `${d.getUTCFullYear()}-${pad(d.getUTCMonth() + 1)}-${pad(d.getUTCDate())} ${pad(
    d.getUTCHours(),
  )}:${pad(d.getUTCMinutes())}Z`;
}

export function clamp(v: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, v));
}
