"""
Antarctic land mask built from real coastline geometry.

Source: Natural Earth 1:50m physical land (public domain), clipped to south of 59 S and
simplified with Douglas-Peucker to 97 polygons / 1698 vertices. Shipped in the repo so the
system has no runtime network dependency.

The A* route search calls is_land() hundreds of thousands of times, so the mask is built for
speed: a vectorised bounding-box reject over all polygons, then exact ray-casting only against
the handful of polygons that could contain the point, with a memo cache on the search lattice.
"""
from __future__ import annotations

import json
import math
from functools import lru_cache
from pathlib import Path
from typing import Dict, List, Sequence, Tuple

import numpy as np

from src.core.constants import M_PER_NM
from src.core.geo import to_epsg3031

_DATA_PATH = Path(__file__).with_name("antarctica_coast.json")


class LandMask:
    """Point-in-polygon land test over the Antarctic coastline."""

    def __init__(self, path: Path = _DATA_PATH) -> None:
        with open(path, "r", encoding="utf-8") as fh:
            self._geojson: Dict = json.load(fh)

        self.polygons: List[np.ndarray] = []
        for feature in self._geojson["features"]:
            ring = np.asarray(feature["geometry"]["coordinates"][0], dtype=np.float64)
            if ring.shape[0] >= 4:
                self.polygons.append(ring)

        # Bounding boxes as parallel arrays for a vectorised first-pass reject.
        self._min_lon = np.array([p[:, 0].min() for p in self.polygons])
        self._max_lon = np.array([p[:, 0].max() for p in self.polygons])
        self._min_lat = np.array([p[:, 1].min() for p in self.polygons])
        self._max_lat = np.array([p[:, 1].max() for p in self.polygons])

        self.northern_limit = float(self._max_lat.max())
        self._coast_tree = None
        self._coast_xy: np.ndarray | None = None

    # ---------------------------------------------------------------- land test
    @staticmethod
    def _point_in_ring(lon: float, lat: float, ring: np.ndarray) -> bool:
        """Ray casting, vectorised over the ring edges."""
        x, y = ring[:-1, 0], ring[:-1, 1]
        x2, y2 = ring[1:, 0], ring[1:, 1]
        straddles = (y > lat) != (y2 > lat)
        if not straddles.any():
            return False
        with np.errstate(divide="ignore", invalid="ignore"):
            x_cross = x + (lat - y) * (x2 - x) / (y2 - y)
        crossings = straddles & (lon < x_cross)
        return bool(np.count_nonzero(crossings) % 2 == 1)

    def is_land(self, lat: float, lon: float) -> bool:
        """True if the coordinate falls on charted Antarctic land or an ice shelf."""
        if lat > self.northern_limit:
            return False
        candidates = np.nonzero(
            (lon >= self._min_lon)
            & (lon <= self._max_lon)
            & (lat >= self._min_lat)
            & (lat <= self._max_lat)
        )[0]
        for idx in candidates:
            if self._point_in_ring(lon, lat, self.polygons[idx]):
                return True
        return False

    def any_land_on_segment(self, a: Tuple[float, float], b: Tuple[float, float], samples: int = 8) -> bool:
        """Sample a great-circle-ish segment for land. Used to reject grazing edges in A*."""
        for i in range(samples + 1):
            f = i / samples
            lat = a[0] + (b[0] - a[0]) * f
            lon = a[1] + (b[1] - a[1]) * f
            if self.is_land(lat, lon):
                return True
        return False

    # ------------------------------------------------------- distance to coast
    def _ensure_tree(self) -> None:
        if self._coast_tree is not None:
            return
        pts: List[Tuple[float, float]] = []
        for ring in self.polygons:
            for i in range(len(ring) - 1):
                lon1, lat1 = ring[i]
                lon2, lat2 = ring[i + 1]
                # Densify so vertex spacing stays under roughly 5 km.
                seg_deg = math.hypot(lat2 - lat1, (lon2 - lon1) * math.cos(math.radians(lat1)))
                steps = max(1, int(seg_deg / 0.045))
                for s in range(steps):
                    f = s / steps
                    pts.append(to_epsg3031(lat1 + (lat2 - lat1) * f, lon1 + (lon2 - lon1) * f))
        self._coast_xy = np.asarray(pts, dtype=np.float64)
        try:
            from scipy.spatial import cKDTree

            self._coast_tree = cKDTree(self._coast_xy)
        except Exception:  # pragma: no cover - scipy is a declared dependency
            self._coast_tree = False  # sentinel: fall back to brute force

    def distance_to_coast_nm(self, lat: float, lon: float) -> float:
        """
        Distance to the nearest charted coastline vertex, in nautical miles.
        Computed in EPSG:3031 metres, which is near-conformal over the Antarctic.
        Returns 0.0 when the point is itself on land.
        """
        if self.is_land(lat, lon):
            return 0.0
        self._ensure_tree()
        x, y = to_epsg3031(lat, lon)
        if self._coast_tree:
            dist_m, _ = self._coast_tree.query([x, y])
        else:  # pragma: no cover
            d = np.hypot(self._coast_xy[:, 0] - x, self._coast_xy[:, 1] - y)
            dist_m = float(d.min())
        return float(dist_m) / M_PER_NM

    # ------------------------------------------------------------------ export
    def geojson(self) -> Dict:
        """The raw coastline FeatureCollection, served to the frontend map engine."""
        return self._geojson

    def stats(self) -> Dict[str, object]:
        return {
            "polygons": len(self.polygons),
            "vertices": int(sum(len(p) for p in self.polygons)),
            "northern_limit_lat": round(self.northern_limit, 3),
            "source": self._geojson.get("attribution", "Natural Earth 1:50m physical land"),
        }


class CoastDistanceField:
    """
    A pre-computed, bilinearly interpolated grid of distance-to-coast.

    Gridded environmental layers need coast distance at thousands of points at once, which is
    far too slow one KD-tree query at a time. This builds the whole lookup in a single batched
    query, then samples it with vectorised bilinear interpolation.
    """

    LAT_MIN, LAT_MAX, LAT_STEP = -78.0, -50.0, 0.25
    LON_MIN, LON_MAX, LON_STEP = -180.0, 180.0, 0.5

    def __init__(self, mask: "LandMask") -> None:
        self._lats = np.arange(self.LAT_MIN, self.LAT_MAX + 1e-9, self.LAT_STEP)
        self._lons = np.arange(self.LON_MIN, self.LON_MAX + 1e-9, self.LON_STEP)
        mask._ensure_tree()

        lon_g, lat_g = np.meshgrid(self._lons, self._lats)
        flat_lat, flat_lon = lat_g.ravel(), lon_g.ravel()

        # Vectorised forward projection of the whole grid.
        phi = np.radians(-flat_lat)
        lam = np.radians(flat_lon)
        from src.core.constants import WGS84_A, WGS84_E
        from src.core.geo import _M_C, _T_C  # noqa: PLC2701 - deliberate reuse of the fitted constants

        e = WGS84_E
        sin_phi = np.sin(phi)
        t = np.tan(np.pi / 4.0 - phi / 2.0) / (((1.0 - e * sin_phi) / (1.0 + e * sin_phi)) ** (e / 2.0))
        rho = WGS84_A * _M_C * t / _T_C
        xy = np.column_stack([rho * np.sin(lam), rho * np.cos(lam)])

        if mask._coast_tree:
            dist_m, _ = mask._coast_tree.query(xy, workers=-1)
        else:  # pragma: no cover
            dist_m = np.array([np.hypot(mask._coast_xy[:, 0] - p[0], mask._coast_xy[:, 1] - p[1]).min() for p in xy])

        self._grid = (dist_m / M_PER_NM).reshape(lat_g.shape)

        # Points inside land get a negative distance, so callers can test the sign.
        land_flags = np.array([mask.is_land(la, lo) for la, lo in zip(flat_lat, flat_lon)])
        self._grid = np.where(land_flags.reshape(lat_g.shape), -self._grid, self._grid)

    def sample(self, lat, lon):
        """Vectorised bilinear lookup. Negative results mean the point is inland."""
        lat = np.asarray(lat, dtype=np.float64)
        lon = np.asarray(lon, dtype=np.float64)
        fi = np.clip((lat - self.LAT_MIN) / self.LAT_STEP, 0, len(self._lats) - 1.001)
        fj = np.clip((((lon + 180.0) % 360.0) - 0.0) / self.LON_STEP, 0, len(self._lons) - 1.001)
        i0, j0 = fi.astype(np.int64), fj.astype(np.int64)
        di, dj = fi - i0, fj - j0
        i1 = np.minimum(i0 + 1, len(self._lats) - 1)
        j1 = np.minimum(j0 + 1, len(self._lons) - 1)
        g = self._grid
        return (
            g[i0, j0] * (1 - di) * (1 - dj)
            + g[i1, j0] * di * (1 - dj)
            + g[i0, j1] * (1 - di) * dj
            + g[i1, j1] * di * dj
        )


_MASK: LandMask | None = None
_COAST_FIELD: CoastDistanceField | None = None


def get_coast_field() -> CoastDistanceField:
    """Lazily built once per process; takes roughly a second, then every lookup is free."""
    global _COAST_FIELD
    if _COAST_FIELD is None:
        _COAST_FIELD = CoastDistanceField(get_land_mask())
    return _COAST_FIELD


def get_land_mask() -> LandMask:
    """Process-wide singleton. Loading parses 45 KB of JSON, so we do it once."""
    global _MASK
    if _MASK is None:
        _MASK = LandMask()
    return _MASK


@lru_cache(maxsize=200_000)
def is_land_cached(lat_q: float, lon_q: float) -> bool:
    """
    Memoised land test on quantised coordinates.

    The route search walks a fixed lattice, so quantising to 0.05 degrees turns hundreds of
    thousands of polygon tests into a few thousand.
    """
    return get_land_mask().is_land(lat_q, lon_q)


def is_land(lat: float, lon: float) -> bool:
    return is_land_cached(round(lat * 20.0) / 20.0, round(lon * 20.0) / 20.0)


@lru_cache(maxsize=100_000)
def distance_to_coast_nm(lat_q: float, lon_q: float) -> float:
    return get_land_mask().distance_to_coast_nm(lat_q, lon_q)


def coast_clearance_nm(lat: float, lon: float) -> float:
    return distance_to_coast_nm(round(lat * 10.0) / 10.0, round(lon * 10.0) / 10.0)


def polygon_vertices() -> Sequence[np.ndarray]:
    return get_land_mask().polygons
