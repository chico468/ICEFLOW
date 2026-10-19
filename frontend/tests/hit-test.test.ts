import assert from 'node:assert/strict';
import { test } from 'node:test';
import { nearestWithin } from '../src/map/hitTest.ts';

const pts = [
  { id: 'A', x: 100, y: 100 },
  { id: 'B', x: 110, y: 100 },
  { id: 'C', x: 400, y: 300 },
];
const pos = (p: { x: number; y: number }) => p;

test('returns the nearest item within range', () => {
  assert.equal(nearestWithin(pts, pos, 108, 101, 12)?.item.id, 'B');
  assert.equal(nearestWithin(pts, pos, 99, 99, 12)?.item.id, 'A');
});

test('returns null when nothing is within range, and never picks something merely because it is the closest', () => {
  assert.equal(nearestWithin(pts, pos, 250, 200, 12), null);
  assert.equal(nearestWithin([], pos, 0, 0, 12), null);
});

test('range is inclusive, and a tie goes to the earlier item', () => {
  assert.equal(nearestWithin(pts, pos, 105, 100, 12)?.item.id, 'A');
  assert.ok(nearestWithin(pts, pos, 112, 100, 12));
  assert.equal(nearestWithin(pts, pos, 112, 100, 11.9)?.item.id, 'B');
});

test('items that are off-screen or have no valid position are ignored, not treated as at the origin', () => {
  const odd = [{ id: 'N', x: Number.NaN, y: 0 }, { id: 'Z', x: 0, y: 0 }];
  assert.equal(nearestWithin(odd, (p) => (p.id === 'Z' ? null : p), 0, 0, 50), null);
});
