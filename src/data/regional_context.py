"""
Regional geographic context: land, country borders and labels for the voyage region.

THIS IS DRAWING DATA, NOT NAVIGATION DATA
-----------------------------------------
The file served here is built by scripts/build_regional_context.py from Natural Earth (public
domain), clipped to the voyage region and simplified to roughly 4 km. It exists so the regional
map can show Africa, India, Australia and the ocean between them. It is deliberately separate from
src/data/landmask.py: the route optimiser's land test, coastal clearance and the coast-distance
field never read this file, because a 4 km simplification has not been validated for that use.

The file is generated, not committed by default. When it is absent this module says so plainly
and tells the caller how to build it, so the interface can show a setup message rather than a
blank map.

Standard library only.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, Optional

#: The voyage region, in degrees. It spans Cape Town, Goa, Fremantle and Hobart, and the Antarctic
#: margin down to 75 S. Antarctica below 75 S is the polar chart's job.
REGION: Dict[str, float] = {"lon_min": -30.0, "lon_max": 165.0, "lat_min": -75.0, "lat_max": 40.0}

REGIONAL_FILE = Path(__file__).resolve().parent / "regional_context.json"

_SETUP = [
    "python -m scripts.build_regional_context",
    "If the download fails on a certificate error, see the message the script prints. "
    "Certificate verification is never disabled.",
    "Or download ne_50m_land.geojson and ne_110m_admin_0_countries.geojson yourself and run: "
    "python -m scripts.build_regional_context --land-file <path> --countries-file <path>",
]

_cache: Dict[str, Any] = {"key": None, "doc": None}


def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "reason": reason,
        "setup": _SETUP,
        "region": REGION,
        "land": [],
        "countries": [],
    }


def load_regional(path: Optional[Path] = None) -> Dict[str, Any]:
    """The regional context document, or an explicit 'not built' answer."""
    target = Path(path) if path is not None else REGIONAL_FILE
    if not target.is_file():
        return _unavailable(f"{target.name} has not been built yet.")

    stat = target.stat()
    key = (str(target), stat.st_mtime_ns, stat.st_size)
    if _cache["key"] == key and _cache["doc"] is not None:
        return _cache["doc"]

    try:
        with open(target, "r", encoding="utf-8") as handle:
            doc = json.load(handle)
    except (OSError, ValueError) as exc:
        return _unavailable(f"{target.name} could not be read: {type(exc).__name__}: {exc}")

    if not isinstance(doc, dict) or "land" not in doc:
        return _unavailable(f"{target.name} is not a regional context file (no 'land' key).")

    doc = dict(doc)
    doc["available"] = True
    doc.setdefault("region", REGION)
    _cache.update(key=key, doc=doc)
    return doc
