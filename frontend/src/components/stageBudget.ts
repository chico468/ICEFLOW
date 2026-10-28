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
/**
 * The smallest the map cell is allowed to be, in CSS pixels, as a function of the viewport width.
 * The map keeps at least 520 px, or half the viewport, whichever is larger.
 */
export function mapMinWidth(stageWidth: number): number {
  return Math.max(520, Math.floor(stageWidth * 0.5));
}
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
/** Width of a side dock's tab strip. */
export const SIDE_DOCK_BAR_WIDTH = 36;

/** Left dock: opens at 340 px, may grow to 380 px. */
export const SIDE_DOCK_LEFT_OPEN = 340;
export const SIDE_DOCK_LEFT_MAX = 380;
/** Right dock: opens at 320 px and stays there. */
export const SIDE_DOCK_RIGHT_OPEN = 320;
export const SIDE_DOCK_RIGHT_MAX = 320;

/** Below this viewport width the side docks overlay the map as drawers instead of shrinking it. */
export const SIDE_DOCK_DRAWER_BREAKPOINT = 1100;
/** Below this viewport width only one side dock panel may be open at a time. */
export const SIDE_DOCK_SINGLE_BREAKPOINT = 1400;

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
 *
 * Below SIDE_DOCK_DRAWER_BREAKPOINT the docks overlay the map as drawers and claim no width, so the
 * map keeps the full stage width. Otherwise an open side dock claims its panel width (capped by the
 * map's minimum), a closed one claims its tab strip. If there isn't room for the map minimum, the
 * open panels shrink toward their minimum share, proportionally.
 */
export function horizontalBudget(
  stageWidth: number,
  hasLeft: boolean,
  hasRight: boolean,
  leftOpen: boolean,
  rightOpen: boolean,
): HorizontalBudget {
  const drawer = stageWidth < SIDE_DOCK_DRAWER_BREAKPOINT;
  const leftWants = drawer ? 0 : (leftOpen ? SIDE_DOCK_LEFT_OPEN : SIDE_DOCK_BAR_WIDTH);
  const rightWants = drawer ? 0 : (rightOpen ? SIDE_DOCK_RIGHT_OPEN : SIDE_DOCK_BAR_WIDTH);
  const barsOnly = drawer ? 0 : (hasLeft ? SIDE_DOCK_BAR_WIDTH : 0) + (hasRight ? SIDE_DOCK_BAR_WIDTH : 0);
  const panelsNeed = leftWants + rightWants;
  const minMap = mapMinWidth(stageWidth);

  let leftPanelMax = drawer ? 0 : (leftOpen ? SIDE_DOCK_LEFT_OPEN : 0);
  let rightPanelMax = drawer ? 0 : (rightOpen ? SIDE_DOCK_RIGHT_OPEN : 0);

  let mapWidthRaw = drawer ? stageWidth : stageWidth - panelsNeed;
  if (mapWidthRaw < minMap) {
    const available = drawer ? Math.max(0, stageWidth - minMap) : stageWidth - barsOnly - minMap;
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
  const leftCanOpen = drawer ? true : leftPanelMax >= SIDE_DOCK_PANEL_MIN;
  const rightCanOpen = drawer ? true : rightPanelMax >= SIDE_DOCK_PANEL_MIN;
  const leftW = drawer ? 0 : (leftOpen && leftCanOpen ? leftPanelMax : (hasLeft ? SIDE_DOCK_BAR_WIDTH : 0));
  const rightW = drawer ? 0 : (rightOpen && rightCanOpen ? rightPanelMax : (hasRight ? SIDE_DOCK_BAR_WIDTH : 0));
  const mapWidth = drawer ? stageWidth : stageWidth - leftW - rightW;
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
