import assert from 'node:assert/strict';
import { test } from 'node:test';
import { iceMask } from '../src/lib/iceMask.ts';

function coveredFraction(grid: boolean[][]): number {
  const size = grid.length;
  let covered = 0;
  for (const row of grid) {
    for (const cell of row) {
      if (cell) covered++;
    }
  }
  return covered / (size * size);
}

test('iceMask covered fraction matches SIC within ±0.05 (several SIC values)', () => {
  const sics = [0.0, 0.1, 0.25, 0.3, 0.5, 0.7, 0.9, 1.0];
  const seeds = [0, 1, 42, 0x5eed_ed45, 12345];
  const sizes = [16, 32, 64];

  for (const sic of sics) {
    for (const seed of seeds) {
      for (const size of sizes) {
        const grid = iceMask(seed, sic, size);
        assert.strictEqual(grid.length, size);
        assert.strictEqual(grid[0].length, size);
        const actual = coveredFraction(grid);
        const diff = Math.abs(actual - sic);
        assert.ok(
          diff <= 0.05,
          `iceMask coverage off by ${diff.toFixed(4)} for sic=${sic} seed=${seed} size=${size} (actual=${actual.toFixed(4)})`
        );
      }
    }
  }
});

test('iceMask is deterministic for the same seed + sic + size', () => {
  const a = iceMask(0x5eed_ed45, 0.3, 16);
  const b = iceMask(0x5eed_ed45, 0.3, 16);
  assert.deepStrictEqual(a, b);

  const c = iceMask(1, 0.3, 16);
  assert.notDeepStrictEqual(a, c);
});

test('iceMask clamps SIC to [0, 1]', () => {
  assert.strictEqual(coveredFraction(iceMask(0, -0.5, 16)), 0);
  assert.strictEqual(coveredFraction(iceMask(0, 1.5, 16)), 1);
});

test('iceMask size 1 edge cases', () => {
  assert.strictEqual(iceMask(0, 0, 1)[0][0], false);
  assert.strictEqual(iceMask(0, 1, 1)[0][0], true);
});
