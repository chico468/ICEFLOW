"""
Deterministic gradient noise used to give the synthetic environmental fields realistic
spatial structure (eddies, floes, leads) instead of smooth analytic blobs.

This is a standard Perlin-style implementation over a seeded permutation table, so results
are byte-identical on every platform and every run. That determinism is a demo requirement:
the same voyage request must always produce the same answer.

Everything is vectorised over NumPy arrays so map-sized grids stay fast.
"""
from __future__ import annotations

import numpy as np

_PERM_SIZE = 256


class FractalNoise3D:
    """Value-gradient noise in (x, y, t) with fractal Brownian motion octave stacking."""

    def __init__(self, seed: int) -> None:
        rng = np.random.default_rng(seed)
        perm = rng.permutation(_PERM_SIZE).astype(np.int32)
        self._perm = np.concatenate([perm, perm])
        # 16 unit-ish gradient vectors on the cube edges (Perlin's improved gradient set).
        self._grad = np.array(
            [
                [1, 1, 0], [-1, 1, 0], [1, -1, 0], [-1, -1, 0],
                [1, 0, 1], [-1, 0, 1], [1, 0, -1], [-1, 0, -1],
                [0, 1, 1], [0, -1, 1], [0, 1, -1], [0, -1, -1],
                [1, 1, 0], [0, -1, 1], [-1, 1, 0], [0, -1, -1],
            ],
            dtype=np.float64,
        )

    @staticmethod
    def _fade(t: np.ndarray) -> np.ndarray:
        return t * t * t * (t * (t * 6.0 - 15.0) + 10.0)

    def _hash(self, xi: np.ndarray, yi: np.ndarray, zi: np.ndarray) -> np.ndarray:
        p = self._perm
        return p[(p[(p[xi & 255] + (yi & 255)) & 511] + (zi & 255)) & 511] & 15

    def _dot_grad(self, h: np.ndarray, dx: np.ndarray, dy: np.ndarray, dz: np.ndarray) -> np.ndarray:
        g = self._grad[h]
        return g[..., 0] * dx + g[..., 1] * dy + g[..., 2] * dz

    def noise(self, x, y, z):
        """Single-octave Perlin noise in roughly [-1, 1]."""
        x = np.asarray(x, dtype=np.float64)
        y = np.asarray(y, dtype=np.float64)
        z = np.asarray(z, dtype=np.float64)

        xi = np.floor(x).astype(np.int64)
        yi = np.floor(y).astype(np.int64)
        zi = np.floor(z).astype(np.int64)
        xf, yf, zf = x - xi, y - yi, z - zi
        u, v, w = self._fade(xf), self._fade(yf), self._fade(zf)

        def corner(dx: int, dy: int, dz: int) -> np.ndarray:
            h = self._hash(xi + dx, yi + dy, zi + dz)
            return self._dot_grad(h, xf - dx, yf - dy, zf - dz)

        c000, c100 = corner(0, 0, 0), corner(1, 0, 0)
        c010, c110 = corner(0, 1, 0), corner(1, 1, 0)
        c001, c101 = corner(0, 0, 1), corner(1, 0, 1)
        c011, c111 = corner(0, 1, 1), corner(1, 1, 1)

        x00 = c000 + u * (c100 - c000)
        x10 = c010 + u * (c110 - c010)
        x01 = c001 + u * (c101 - c001)
        x11 = c011 + u * (c111 - c011)
        y0 = x00 + v * (x10 - x00)
        y1 = x01 + v * (x11 - x01)
        return y0 + w * (y1 - y0)

    def fbm(self, x, y, z, octaves: int = 4, lacunarity: float = 2.0, gain: float = 0.5):
        """Fractal Brownian motion: stacked octaves, normalised to roughly [-1, 1]."""
        total = np.zeros_like(np.asarray(x, dtype=np.float64))
        amplitude = 1.0
        frequency = 1.0
        norm = 0.0
        for _ in range(octaves):
            total = total + amplitude * self.noise(
                np.asarray(x) * frequency, np.asarray(y) * frequency, np.asarray(z) * frequency
            )
            norm += amplitude
            amplitude *= gain
            frequency *= lacunarity
        return total / max(norm, 1e-9)

    def ridged(self, x, y, z, octaves: int = 4):
        """Ridged multifractal, in [0, 1]. Good for pressure ridges and floe edges."""
        return 1.0 - np.abs(self.fbm(x, y, z, octaves=octaves))


def smoothstep(edge0: float, edge1: float, x):
    """Hermite interpolation clamped to [0, 1]."""
    t = np.clip((np.asarray(x, dtype=np.float64) - edge0) / (edge1 - edge0 + 1e-12), 0.0, 1.0)
    return t * t * (3.0 - 2.0 * t)
