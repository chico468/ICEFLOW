/**
 * The height budget of the map stage, as pure arithmetic (no React), so it can be tested directly.
 *
 * The map cell is promised a minimum height. The dock and the top bar get what is left, never more.
 * If what is left cannot show a useful dock panel, the dock stays collapsed to its tab strip.
 */

/** The smallest the map cell is allowed to be, in CSS pixels. */
export const MAP_MIN_HEIGHT = 300;
export const DOCK_BAR_HEIGHT = 40;
export const DOCK_PANEL_MAX = 280;
export const DOCK_PANEL_MIN = 120;
export const TRAY_MAX = 360;
const TRAY_HEADER_MIN = 56;
const TOP_BAR_MIN = 64;

export interface StageBudget {
  /** Tallest the open dock panel may be. */
  panelMax: number;
  /** Whether there is room to open the dock at all. */
  canOpen: boolean;
  /** Tallest the result tray may be. */
  trayMax: number;
  /** Tallest the top command bar may be. */
  topMax: number;
}

export function budget(stageHeight: number, topHeight: number, hasDock: boolean, hasTray: boolean): StageBudget {
  const bar = hasDock ? DOCK_BAR_HEIGHT : 0;
  const dockRoom = Math.max(0, stageHeight - topHeight - MAP_MIN_HEIGHT - bar);
  const panelMax = Math.min(DOCK_PANEL_MAX, dockRoom);
  const trayMax = Math.min(TRAY_MAX, Math.max(0, stageHeight - topHeight - MAP_MIN_HEIGHT));
  const bottomNeed = hasDock ? DOCK_BAR_HEIGHT : hasTray ? TRAY_HEADER_MIN : 0;
  const topMax = Math.max(TOP_BAR_MIN, stageHeight - MAP_MIN_HEIGHT - bottomNeed);
  return { panelMax, canOpen: panelMax >= DOCK_PANEL_MIN, trayMax, topMax };
}
