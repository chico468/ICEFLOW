/**
 * iceMask: pure function returning a boolean floe grid.
 *
 * The covered fraction matches `sic` within ±0.05 (bounded by rounding to a
 * whole cell). Deterministic given `seed` + `sic` + `size` via a Fisher-Yates
 * shuffle driven by an LCG. No React / WebGL dependency — safe to unit test
 * directly.
 */
export function iceMask(seed: number, sic: number, size: number): boolean[][] {
  const grid: boolean[][] = Array.from({ length: size }, () => Array(size).fill(false));
  const target = Math.max(0, Math.min(1, sic));
  const targetCount = Math.round(target * size * size);
  if (targetCount === 0 || targetCount >= size * size) {
    // Fully open or fully covered: no shuffle needed.
    for (let i = 0; i < size; i++) {
      for (let j = 0; j < size; j++) {
        grid[i][j] = targetCount >= size * size;
      }
    }
    return grid;
  }

  // All cell positions, then a deterministic Fisher-Yates shuffle via LCG.
  const positions: [number, number][] = [];
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      positions.push([i, j]);
    }
  }

  let x = seed >>> 0;
  const next = (): number => {
    x = (x * 16807 + 12345) % 2147483647;
    return x / 2147483647;
  };
  for (let i = positions.length - 1; i > 0; i--) {
    const j = Math.floor(next() * (i + 1));
    [positions[i], positions[j]] = [positions[j], positions[i]];
  }

  // Mark the first targetCount positions as floes -> exactly targetCount floes.
  for (let k = 0; k < targetCount; k++) {
    const [i, j] = positions[k];
    grid[i][j] = true;
  }
  return grid;
}
