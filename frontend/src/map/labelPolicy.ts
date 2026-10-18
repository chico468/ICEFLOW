/**
 * Which labels the regional map may draw at a given zoom. Pure, so the rules can be tested.
 *
 * Zoom is relative to the whole region (1 = the whole region fits). The rules keep the map readable:
 * the voyage endpoints are always named; everything else earns a label by zoom level; and at most a
 * handful of country names appear at once, largest first. Collision avoidance in the painter then drops
 * whatever still overlaps, in priority order.
 */

export interface MarkInfo {
  kind: 'port' | 'station';
  /** The planned origin or destination. */
  endpoint: boolean;
  /** An Indian-programme station. */
  indian: boolean;
}

export const MAX_COUNTRY_LABELS = 12;
export const MAX_MARK_LABELS = 16;

export function showMarkLabel(m: MarkInfo, zoom: number): boolean {
  if (m.endpoint) return true;
  if (m.kind === 'port') return zoom >= 2;
  return m.indian ? zoom >= 3.5 : zoom >= 6;
}

/** Smallest country footprint (square degrees of its largest visible piece) that earns a name. */
export function countryRankThreshold(zoom: number): number {
  const z = Math.max(1, zoom);
  return 55 / (z * z);
}

/** Collision priority: lower is placed first and so survives a clash. */
export const LABEL_PRIORITY = { view: 0, endpoint: 1, port: 2, station: 3, country: 4 } as const;
