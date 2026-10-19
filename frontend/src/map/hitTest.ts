/**
 * Nearest-item hit testing in screen space. Pure, so it can be tested without a browser.
 * Used for hover cards on the chart (observed icebergs), where a label on every symbol would carpet the map.
 */

export interface Hit<T> {
  item: T;
  distPx: number;
}

/** The item whose screen position is nearest to (px, py) and within maxPx, or null. Ties go to the earlier item. */
export function nearestWithin<T>(
  items: readonly T[],
  position: (item: T) => { x: number; y: number } | null,
  px: number,
  py: number,
  maxPx: number,
): Hit<T> | null {
  let best: Hit<T> | null = null;
  for (const item of items) {
    const p = position(item);
    if (!p || !Number.isFinite(p.x) || !Number.isFinite(p.y)) continue;
    const d = Math.hypot(p.x - px, p.y - py);
    if (d <= maxPx && (best === null || d < best.distPx)) best = { item, distPx: d };
  }
  return best;
}
