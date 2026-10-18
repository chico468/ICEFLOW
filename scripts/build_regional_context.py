"""
Build src/data/regional_context.json: land, country borders and country labels for the voyage
region, from Natural Earth (public domain, https://www.naturalearthdata.com).

    python -m scripts.build_regional_context

WHAT IT DOES
------------
Downloads two Natural Earth GeoJSON layers, clips them to the voyage region (see
src.data.regional_context.REGION), simplifies them to about 4 km, rounds coordinates to two
decimals and writes one compact JSON file. The output is *drawing data*: it is never read by the
land mask, the route optimiser or any safety calculation.

  land       ne_50m_land                    coastlines for the map
  countries  ne_110m_admin_0_countries      borders and label points

CERTIFICATES
------------
Downloads use Python's default certificate verification. The script uses the `certifi` bundle when
it is installed (it is, as a dependency of httpx), and the operating system's store otherwise.
Verification is never disabled. On macOS with a python.org build the system store is often empty;
that produces CERTIFICATE_VERIFY_FAILED, and the message printed below says how to fix it properly.

NO NETWORK? USE LOCAL FILES
---------------------------
    python -m scripts.build_regional_context --land-file ne_50m_land.geojson \
                                             --countries-file ne_110m_admin_0_countries.geojson

The default URLs point at the public natural-earth-vector repository. They were written without
network access to confirm them, so if Natural Earth moves its files, pass --land-url and
--countries-url, or use the local-file form above.

Standard library only. Exit codes: 0 success, 2 download failed, 3 data unusable.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import math
import os
import ssl
import sys
import tempfile
import urllib.error
import urllib.request
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, List, Optional, Sequence, Tuple

from src.data.regional_context import REGION, REGIONAL_FILE

LAND_URL = "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/ne_50m_land.geojson"
COUNTRIES_URL = (
    "https://raw.githubusercontent.com/nvkelso/natural-earth-vector/master/geojson/"
    "ne_110m_admin_0_countries.geojson"
)

ATTRIBUTION = "Made with Natural Earth. Free vector and raster map data at naturalearthdata.com (public domain)."
ACCURACY_NOTE = (
    "Context drawing only. Simplified to about 4 km and clipped to the voyage region. Not used by "
    "the land mask, coastal clearance or route optimiser, and not suitable for navigation."
)

MAX_DOWNLOAD_BYTES = 80 * 1024 * 1024

Point = Tuple[float, float]
Ring = List[Point]
BBox = Tuple[float, float, float, float]  # lon_min, lat_min, lon_max, lat_max


class BuildError(Exception):
    """A failure with a message fit to show the user. `code` is the process exit code."""

    def __init__(self, message: str, code: int) -> None:
        super().__init__(message)
        self.code = code


# --------------------------------------------------------------------------- geometry
def clip_ring(ring: Sequence[Point], bbox: BBox) -> Ring:
    """Sutherland-Hodgman clip of one ring to a lon/lat rectangle. Returns an open ring."""
    lon_min, lat_min, lon_max, lat_max = bbox

    def inside_fns():
        yield (lambda p: p[0] >= lon_min), lambda a, b: _at_x(a, b, lon_min)
        yield (lambda p: p[0] <= lon_max), lambda a, b: _at_x(a, b, lon_max)
        yield (lambda p: p[1] >= lat_min), lambda a, b: _at_y(a, b, lat_min)
        yield (lambda p: p[1] <= lat_max), lambda a, b: _at_y(a, b, lat_max)

    pts: Ring = [tuple(p) for p in ring]  # type: ignore[misc]
    if len(pts) > 1 and pts[0] == pts[-1]:
        pts = pts[:-1]
    for inside, cut in inside_fns():
        if not pts:
            break
        out: Ring = []
        prev = pts[-1]
        for cur in pts:
            if inside(cur):
                if not inside(prev):
                    out.append(cut(prev, cur))
                out.append(cur)
            elif inside(prev):
                out.append(cut(prev, cur))
            prev = cur
        pts = out
    return pts


def _at_x(a: Point, b: Point, x: float) -> Point:
    t = (x - a[0]) / (b[0] - a[0])
    return (x, a[1] + t * (b[1] - a[1]))


def _at_y(a: Point, b: Point, y: float) -> Point:
    t = (y - a[1]) / (b[1] - a[1])
    return (a[0] + t * (b[0] - a[0]), y)


def simplify_ring(ring: Sequence[Point], tolerance: float) -> Ring:
    """Douglas-Peucker, iterative so a long coastline cannot hit the recursion limit."""
    n = len(ring)
    if n < 4 or tolerance <= 0:
        return list(ring)
    keep = [False] * n
    keep[0] = keep[-1] = True
    stack = [(0, n - 1)]
    while stack:
        lo, hi = stack.pop()
        far, far_d = -1, -1.0
        for i in range(lo + 1, hi):
            d = _point_segment_distance(ring[i], ring[lo], ring[hi])
            if d > far_d:
                far, far_d = i, d
        if far_d > tolerance and far != -1:
            keep[far] = True
            stack.append((lo, far))
            stack.append((far, hi))
    return [p for p, k in zip(ring, keep) if k]


def _point_segment_distance(p: Point, a: Point, b: Point) -> float:
    dx, dy = b[0] - a[0], b[1] - a[1]
    if dx == 0.0 and dy == 0.0:
        return math.hypot(p[0] - a[0], p[1] - a[1])
    t = max(0.0, min(1.0, ((p[0] - a[0]) * dx + (p[1] - a[1]) * dy) / (dx * dx + dy * dy)))
    return math.hypot(p[0] - (a[0] + t * dx), p[1] - (a[1] + t * dy))


def iter_polygons(geometry: Optional[Dict[str, Any]]) -> Iterator[List[List[Sequence[float]]]]:
    """Yield each polygon (a list of rings, exterior first) of a Polygon or MultiPolygon."""
    if not geometry:
        return
    kind = geometry.get("type")
    coords = geometry.get("coordinates") or []
    if kind == "Polygon":
        yield coords
    elif kind == "MultiPolygon":
        for polygon in coords:
            yield polygon


def _bbox_area(ring: Sequence[Point]) -> float:
    xs = [p[0] for p in ring]
    ys = [p[1] for p in ring]
    return (max(xs) - min(xs)) * (max(ys) - min(ys)) if ring else 0.0


def process_polygon(polygon: Sequence[Sequence[Sequence[float]]], bbox: BBox, tolerance: float) -> List[Ring]:
    """Clip and simplify one polygon. Returns its surviving rings, exterior first; [] if gone."""
    rings: List[Ring] = []
    for index, raw in enumerate(polygon):
        clipped = clip_ring([(float(p[0]), float(p[1])) for p in raw], bbox)
        if len(clipped) < 3:
            if index == 0:
                return []  # the exterior is gone, so any hole is meaningless
            continue
        simple = simplify_ring(clipped + [clipped[0]], tolerance)[:-1]
        if len(simple) >= 3:
            rings.append(simple)
        elif index == 0:
            return []
    return rings


def _flatten(ring: Ring) -> List[float]:
    out: List[float] = []
    for lon, lat in ring:
        out.append(round(lon, 2))
        out.append(round(lat, 2))
    return out


# --------------------------------------------------------------------------- layers
def build_land(geojson: Dict[str, Any], bbox: BBox, tolerance: float) -> List[List[List[float]]]:
    """Land polygons as [polygon][ring] = flat [lon, lat, lon, lat, ...]."""
    out: List[List[List[float]]] = []
    for feature in geojson.get("features", []):
        for polygon in iter_polygons(feature.get("geometry")):
            rings = process_polygon(polygon, bbox, tolerance)
            if rings:
                out.append([_flatten(r) for r in rings])
    return out


def _country_name(props: Dict[str, Any]) -> str:
    for key in ("NAME", "name", "ADMIN", "admin", "NAME_EN", "name_en"):
        value = props.get(key)
        if isinstance(value, str) and value.strip():
            return value.strip()
    return ""


def build_countries(geojson: Dict[str, Any], bbox: BBox, tolerance: float) -> List[Dict[str, Any]]:
    """Country borders plus one label point each, placed on the largest visible piece."""
    out: List[Dict[str, Any]] = []
    for feature in geojson.get("features", []):
        name = _country_name(feature.get("properties") or {})
        polygons: List[List[Ring]] = []
        for polygon in iter_polygons(feature.get("geometry")):
            rings = process_polygon(polygon, bbox, tolerance)
            if rings:
                polygons.append(rings)
        if not name or not polygons:
            continue
        largest = max((p[0] for p in polygons), key=_bbox_area)
        xs = [p[0] for p in largest]
        ys = [p[1] for p in largest]
        out.append(
            {
                "name": name,
                "label": [round((min(xs) + max(xs)) / 2.0, 2), round((min(ys) + max(ys)) / 2.0, 2)],
                "label_rank": round(_bbox_area(largest), 2),
                "polygons": [[_flatten(r) for r in rings] for rings in polygons],
            }
        )
    out.sort(key=lambda c: -c["label_rank"])
    return out


def build_context(
    land_geojson: Dict[str, Any],
    countries_geojson: Dict[str, Any],
    sources: Optional[List[Dict[str, Any]]] = None,
    land_tolerance: float = 0.04,
    country_tolerance: float = 0.05,
    region: Optional[Dict[str, float]] = None,
    generated_utc: Optional[str] = None,
) -> Dict[str, Any]:
    """Assemble the output document. Pure: no network and no file access."""
    reg = region or REGION
    bbox: BBox = (reg["lon_min"], reg["lat_min"], reg["lon_max"], reg["lat_max"])
    land = build_land(land_geojson, bbox, land_tolerance)
    countries = build_countries(countries_geojson, bbox, country_tolerance)
    if not land:
        raise BuildError("The land layer produced no polygons inside the region. Is it the right file?", 3)
    return {
        "type": "RegionalContext",
        "region": dict(reg),
        "attribution": ATTRIBUTION,
        "accuracy_note": ACCURACY_NOTE,
        "generated_by": "scripts/build_regional_context.py",
        "generated_utc": generated_utc or datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "sources": sources or [],
        "simplification_degrees": {"land": land_tolerance, "countries": country_tolerance},
        "stats": {
            "land_polygons": len(land),
            "land_vertices": sum(len(r) // 2 for poly in land for r in poly),
            "countries": len(countries),
        },
        "land": land,
        "countries": countries,
    }


# --------------------------------------------------------------------------- download
def _ssl_context() -> ssl.SSLContext:
    """Default, verifying context. Prefers certifi's bundle when present; never disables checks."""
    try:
        import certifi  # type: ignore

        return ssl.create_default_context(cafile=certifi.where())
    except ImportError:
        return ssl.create_default_context()


_CERT_HELP = (
    "The HTTPS certificate could not be verified, so nothing was downloaded. Certificate checking is "
    "left ON deliberately. Fixes, in order of preference:\n"
    "  1. macOS python.org install: run  /Applications/Python\\ 3.x/Install\\ Certificates.command\n"
    "  2. pip install --upgrade certifi   (this script uses certifi automatically when present)\n"
    "  3. Corporate proxy: ask IT for its CA certificate and set SSL_CERT_FILE to it.\n"
    "  4. Download the two .geojson files in a browser and use --land-file / --countries-file."
)


def fetch_json(url: str, timeout: float = 60.0) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    """Download and parse one GeoJSON file. Returns (document, source-record)."""
    request = urllib.request.Request(url, headers={"User-Agent": "ICEFLOW-build-regional-context/1.0"})
    try:
        with urllib.request.urlopen(request, timeout=timeout, context=_ssl_context()) as response:
            payload = response.read(MAX_DOWNLOAD_BYTES + 1)
    except urllib.error.HTTPError as exc:
        raise BuildError(f"{url}\n  server answered HTTP {exc.code} {exc.reason}.", 2) from exc
    except urllib.error.URLError as exc:
        if isinstance(exc.reason, ssl.SSLCertVerificationError):
            raise BuildError(f"{url}\n  {exc.reason}\n{_CERT_HELP}", 2) from exc
        raise BuildError(f"{url}\n  could not connect: {exc.reason}. Check the network, or use --land-file.", 2) from exc
    except ssl.SSLCertVerificationError as exc:
        raise BuildError(f"{url}\n  {exc}\n{_CERT_HELP}", 2) from exc
    except (TimeoutError, OSError) as exc:
        raise BuildError(f"{url}\n  download failed: {type(exc).__name__}: {exc}", 2) from exc

    if len(payload) > MAX_DOWNLOAD_BYTES:
        raise BuildError(f"{url}\n  response is larger than {MAX_DOWNLOAD_BYTES // (1024 * 1024)} MB; refusing it.", 3)
    return _parse(payload, url, url)


def read_json_file(path: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        payload = Path(path).read_bytes()
    except OSError as exc:
        raise BuildError(f"{path}\n  could not be read: {exc}", 3) from exc
    return _parse(payload, path, f"file:{Path(path).name}")


def _parse(payload: bytes, label: str, source: str) -> Tuple[Dict[str, Any], Dict[str, Any]]:
    try:
        doc = json.loads(payload.decode("utf-8-sig"))
    except (UnicodeDecodeError, ValueError) as exc:
        raise BuildError(f"{label}\n  is not valid JSON ({exc}). A saved HTML error page looks like this.", 3) from exc
    if not isinstance(doc, dict) or doc.get("type") != "FeatureCollection" or not doc.get("features"):
        raise BuildError(f"{label}\n  is not a non-empty GeoJSON FeatureCollection.", 3)
    record = {
        "source": source,
        "sha256": hashlib.sha256(payload).hexdigest(),
        "bytes": len(payload),
        "retrieved_utc": datetime.now(timezone.utc).isoformat(timespec="seconds"),
    }
    return doc, record


def write_atomic(path: Path, document: Dict[str, Any]) -> int:
    """Write via a temp file and rename, so a failed run never leaves a half-written map."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=str(path.parent), prefix=".regional_", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as handle:
            json.dump(document, handle, separators=(",", ":"), ensure_ascii=False)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise
    return path.stat().st_size


# --------------------------------------------------------------------------- cli
def main(argv: Optional[Iterable[str]] = None) -> int:
    parser = argparse.ArgumentParser(description="Build the regional map context from Natural Earth.")
    parser.add_argument("--out", default=str(REGIONAL_FILE), help="output file (default: %(default)s)")
    parser.add_argument("--land-url", default=LAND_URL)
    parser.add_argument("--countries-url", default=COUNTRIES_URL)
    parser.add_argument("--land-file", help="use a local ne_50m_land GeoJSON instead of downloading")
    parser.add_argument("--countries-file", help="use a local ne_110m_admin_0_countries GeoJSON instead")
    parser.add_argument("--timeout", type=float, default=60.0)
    args = parser.parse_args(list(argv) if argv is not None else None)

    try:
        sources: List[Dict[str, Any]] = []
        if args.land_file:
            land, rec = read_json_file(args.land_file)
        else:
            print(f"Downloading {args.land_url}")
            land, rec = fetch_json(args.land_url, args.timeout)
        sources.append({"layer": "land", "dataset": "ne_50m_land", **rec})

        if args.countries_file:
            countries, rec = read_json_file(args.countries_file)
        else:
            print(f"Downloading {args.countries_url}")
            countries, rec = fetch_json(args.countries_url, args.timeout)
        sources.append({"layer": "countries", "dataset": "ne_110m_admin_0_countries", **rec})

        document = build_context(land, countries, sources=sources)
        size = write_atomic(Path(args.out), document)
    except BuildError as exc:
        print(f"\nERROR: {exc}", file=sys.stderr)
        return exc.code

    stats = document["stats"]
    print(
        f"Wrote {args.out}  ({size / 1024:.0f} KB): {stats['land_polygons']} land polygons, "
        f"{stats['land_vertices']} vertices, {stats['countries']} countries."
    )
    print("Attribution kept in the file: " + ATTRIBUTION)
    return 0


if __name__ == "__main__":
    sys.exit(main())
