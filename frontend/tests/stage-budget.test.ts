import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  DOCK_BAR_HEIGHT,
  DOCK_PANEL_MAX,
  DOCK_PANEL_MIN,
  MAP_MIN_HEIGHT,
  SIDE_DOCK_BAR_WIDTH,
  SIDE_DOCK_LEFT_OPEN,
  SIDE_DOCK_RIGHT_OPEN,
  fullBudget,
  horizontalBudget,
  mapMinWidth,
  budget,
} from '../src/components/stageBudget.ts';

// Stage heights = viewport height minus the 56 px header, for the sizes the brief requires.
const SIZES: [string, number][] = [
  ['1024x640', 640 - 56],
  ['1280x720', 720 - 56],
  ['1366x768', 768 - 56],
  ['1440x900', 900 - 56],
  ['1920x1080', 1080 - 56],
];

test('at every supported size the map keeps its minimum height beside an open dock', () => {
  for (const [name, h] of SIZES) {
    const b = budget(h, 0, true, false);
    if (!b.canOpen) continue; // then the dock is collapsed and the map has even more
    const mapHeight = h - DOCK_BAR_HEIGHT - b.panelMax;
    assert.ok(mapHeight >= MAP_MIN_HEIGHT, `${name}: map would be ${mapHeight}px`);
  }
});

test('every supported size can open the dock', () => {
  for (const [name, h] of SIZES) assert.equal(budget(h, 0, true, false).canOpen, true, name);
});

test('the dock panel never exceeds its cap, even on a tall screen', () => {
  assert.equal(budget(5000, 0, true, false).panelMax, DOCK_PANEL_MAX);
});

test('a tall top bar shrinks the dock room instead of the map, and may collapse the dock', () => {
  const open = budget(584, 0, true, false);
  const crowded = budget(584, 230, true, false);
  assert.ok(crowded.panelMax < open.panelMax);
  assert.equal(crowded.canOpen, false, 'not enough room: the dock stays collapsed to its tab strip');
  assert.ok(crowded.panelMax >= 0);
});

test('the top bar is capped so the map minimum survives, but never below a usable floor', () => {
  const b = budget(584, 0, true, false);
  assert.equal(b.topMax, 584 - MAP_MIN_HEIGHT - DOCK_BAR_HEIGHT);
  assert.ok(budget(200, 0, true, false).topMax >= 64);
});

test('no negative heights on a tiny window', () => {
  const b = budget(100, 90, true, true);
  assert.ok(b.panelMax >= 0 && b.trayMax >= 0 && b.topMax > 0);
  assert.equal(b.canOpen, false);
  assert.ok(DOCK_PANEL_MIN > 0);
});

test('the result tray gets room only after the map minimum, and never above its cap', () => {
  assert.equal(budget(584, 0, false, true).trayMax, 584 - MAP_MIN_HEIGHT);
  assert.equal(budget(2000, 0, false, true).trayMax, 360);
});

test('mapMinWidth is at least 520 px or half the viewport, whichever is larger', () => {
  assert.equal(mapMinWidth(1280), 640);
  assert.equal(mapMinWidth(1440), 720);
  assert.equal(mapMinWidth(1920), 960);
  assert.equal(mapMinWidth(1000), 520);
  assert.equal(mapMinWidth(700), 520);
});

test('at 1280x720, 1440x900 and 1920x1080 the map keeps its minimum width with both docks open', () => {
  const cases: [string, number][] = [
    ['1280x720', 1280],
    ['1440x900', 1440],
    ['1920x1080', 1920],
  ];
  for (const [name, w] of cases) {
    const b = fullBudget(w, 700, 56, false, false, true, true, true, true);
    const expectedMin = mapMinWidth(w);
    assert.ok(b.mapWidth >= expectedMin, `${name}: map width ${b.mapWidth}px below minimum ${expectedMin}px`);
    // A closed dock claims only its tab strip; an open one claims at most its open width.
    assert.ok(b.leftPanelMax <= SIDE_DOCK_LEFT_OPEN || b.leftPanelMax === 0);
    assert.ok(b.rightPanelMax <= SIDE_DOCK_RIGHT_OPEN || b.rightPanelMax === 0);
  }
});

test('horizontal budget never surrenders more width than both open side docks claim', () => {
  for (const w of [1280, 1440, 1920]) {
    const b = horizontalBudget(w, true, true, true, true);
    const claimed = (b.leftPanelMax > 0 ? b.leftPanelMax : SIDE_DOCK_BAR_WIDTH) +
      (b.rightPanelMax > 0 ? b.rightPanelMax : SIDE_DOCK_BAR_WIDTH);
    assert.equal(b.mapWidth, w - claimed);
    assert.ok(b.mapWidth >= mapMinWidth(w));
  }
});

test('below 1100 px the docks overlay the map as drawers and claim no width', () => {
  const b = fullBudget(1024, 700, 56, false, false, true, true, true, true);
  assert.equal(b.mapWidth, 1024);
  assert.equal(b.leftPanelMax, 0);
  assert.equal(b.rightPanelMax, 0);
});
