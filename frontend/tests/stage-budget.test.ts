import assert from 'node:assert/strict';
import { test } from 'node:test';
import { DOCK_BAR_HEIGHT, DOCK_PANEL_MAX, DOCK_PANEL_MIN, MAP_MIN_HEIGHT, budget } from '../src/components/stageBudget.ts';

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
