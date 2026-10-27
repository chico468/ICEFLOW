/**
 * The geometry budget of the map stage, as pure arithmetic (no React), so it can be tested directly.
 *
 * The map cell is promised a minimum height and width. The bottom dock, side docks and top bar
 * get what is left, never more. If what is left cannot show a useful panel, the dock stays collapsed
 * to its tab strip.
 *
 * The earlier design only had a bottom dock; this adds left and right side docks that share the
 * horizontal space.
 */

/** The smallest the map cell is allowed to be, in CSS pixels. */
export const MAP_MIN_HEIGHT = 300;
export const MAP_MIN_WIDTH = 320;
/** Height of the bottom dock's tab bar. */
export const DOCK_BAR_HEIGHT = 40;
/** Tallest the bottom dock panel may grow. */
export const DOCK_PANEL_MAX = 280;
/** Tallest the bottom dock needs to stay useful. */
export const DOCK_PANEL_MIN = 120;
/** Tallest the bottom result tray may grow. */
export const TRAY_MAX = 360;
const TRAY_HEADER_MIN = 56;
const TOP_BAR_MIN = 64;

/** The minimum width a side dock panel must have to be worth opening. */
export const SIDE_DOCK_PANEL_MIN = 200;
/** Tallest a side dock panel may grow. */
export const SIDE_DOCK_PANEL_MAX = 480;
/** Width of a side dock's tab strip. */
export const SIDE_DOCK_BAR_WIDTH = 36;

export interface VerticalBudget {
  /** Tallest the open bottom dock panel may be. */
  panelMax: number;
  /** Whether there is room to open the bottom dock at all. */
  canOpen: boolean;
  /** Tallest the result tray may be. */
  trayMax: number;
  /** Tallest the top command bar may be. */
  topMax: number;
  /** Available height for the map cell. */
  mapHeight: number;
}

export interface HorizontalBudget {
  /** Whether the left dock can open and at most how wide. */
  leftCanOpen: boolean;
  leftPanelMax: number;
  /** Whether the right dock can open and at most how wide. */
  rightCanOpen: boolean;
  rightPanelMax: number;
  /** Available width for the map cell. */
  mapWidth: number;
}

export interface StageBudget extends VerticalBudget, HorizontalBudget {}

function verticalBudget(stageHeight: number, topHeight: number, hasDock: boolean, hasTray: boolean): VerticalBudget {
  const bar = hasDock ? DOCK_BAR_HEIGHT : 0;
  const dockRoom = Math.max(0, stageHeight - topHeight - MAP_MIN_HEIGHT - bar);
  const panelMax = Math.min(DOCK_PANEL_MAX, dockRoom);
  const trayMax = Math.min(TRAY_MAX, Math.max(0, stageHeight - topHeight - MAP_MIN_HEIGHT));
  const bottomNeed = hasDock ? DOCK_BAR_HEIGHT : hasTray ? TRAY_HEADER_MIN : 0;
  const topMax = Math.max(TOP_BAR_MIN, stageHeight - MAP_MIN_HEIGHT - bottomNeed);
  const mapHeight = Math.max(MAP_MIN_HEIGHT, stageHeight - topHeight - bar);
  return { panelMax, canOpen: panelMax >= DOCK_PANEL_MIN, trayMax, topMax, mapHeight };
}

/**
 * Compute the horizontal layout budget given the stage width and whether each side dock is open.
 * An open side dock claims its panel max width (capped by available space); a closed one claims zero.
 */
export function horizontalBudget(
  stageWidth: number,
  hasLeft: boolean,
  hasRight: boolean,
  leftOpen: boolean,
  rightOpen: boolean,
): HorizontalBudget {
  const leftWants = leftOpen ? SIDE_DOCK_PANEL_MAX : SIDE_DOCK_BAR_WIDTH;
  const rightWants = rightOpen ? SIDE_DOCK_PANEL_MAX : SIDE_DOCK_BAR_WIDTH;
  const barsOnly = (hasLeft ? SIDE_DOCK_BAR_WIDTH : 0) + (hasRight ? SIDE_DOCK_BAR_WIDTH : 0);
  const panelsNeed = leftWants + rightWants;
  let leftPanelMax = leftOpen ? SIDE_DOCK_PANEL_MAX : 0;
  let rightPanelMax = rightOpen ? SIDE_DOCK_PANEL_MAX : 0;
  const mapWidthRaw = stageWidth - panelsNeed;
  if (mapWidthRaw < MAP_MIN_WIDTH) {
    const available = stageWidth - barsOnly - MAP_MIN_WIDTH;
    // Shrink the open panels to their minimum share, proportionally.
    if (leftOpen && rightOpen) {
      const half = Math.floor(available / 2);
      leftPanelMax = Math.max(SIDE_DOCK_PANEL_MIN, half);
      rightPanelMax = Math.max(SIDE_DOCK_PANEL_MIN, available - half);
    } else if (leftOpen) {
      leftPanelMax = Math.max(SIDE_DOCK_PANEL_MIN, available);
    } else if (rightOpen) {
      rightPanelMax = Math.max(SIDE_DOCK_PANEL_MIN, available);
    }
  }
  const leftCanOpen = leftPanelMax >= SIDE_DOCK_PANEL_MIN;
  const rightCanOpen = rightPanelMax >= SIDE_DOCK_PANEL_MIN;
  const leftW = leftOpen && leftCanOpen ? leftPanelMax : (hasLeft ? SIDE_DOCK_BAR_WIDTH : 0);
  const rightW = rightOpen && rightCanOpen ? rightPanelMax : (hasRight ? SIDE_DOCK_BAR_WIDTH : 0);
  const mapWidth = stageWidth - leftW - rightW;
  return { leftCanOpen, leftPanelMax, rightCanOpen, rightPanelMax, mapWidth };
}

/** Legacy height-only budget for the bottom dock and tray. */
export function budget(stageHeight: number, topHeight: number, hasDock: boolean, hasTray: boolean): StageBudget {
  const v = verticalBudget(stageHeight, topHeight, hasDock, hasTray);
  // No side docks by default; map width is unconstrained.
  return { ...v, leftCanOpen: false, leftPanelMax: 0, rightCanOpen: false, rightPanelMax: 0, mapWidth: 10_000 };
}

/**
 * Full budget for a stage with optional top bar, bottom dock, bottom tray,
 * and left/right side docks.
 */
export function fullBudget(
  stageWidth: number,
  stageHeight: number,
  topHeight: number,
  hasBottomDock: boolean,
  hasTray: boolean,
  hasLeftDock: boolean,
  hasRightDock: boolean,
  leftOpen: boolean,
  rightOpen: boolean,
): StageBudget {
  const v = verticalBudget(stageHeight, topHeight, hasBottomDock, hasTray);
  const h = horizontalBudget(stageWidth, hasLeftDock, hasRightDock, leftOpen, rightOpen);
  return { ...v, ...h };
}
