"""
Observed iceberg snapshot: the USNIC-format CSV in data/raw/iceberg/.

WHAT THIS IS, AND WHAT IT IS NOT
--------------------------------
This is a single dated table of iceberg positions and sizes. It is an *observation*, but it is
not live and it is not a forecast:

  * it carries one date per row (the "Last Update" column), so the snapshot is only as current
    as that date. Age is computed against the clock when the file is read, and a snapshot older
    than OBSERVED_STALE_AFTER_DAYS is reported as stale rather than quietly presented as current;
  * it has no position-uncertainty column, so none is shown or implied;
  * it is NOT merged into the simulated catalogue (src/data/icebergs.py), NOT drifted forward and
    NOT used by the route optimiser or the closest-approach alerts. It exists to be drawn and
    read, clearly labelled, next to the simulation.

The file's own origin is not recorded in the repository. Its column layout matches the public
US National Ice Center iceberg table, which is what the source label says, but nothing in the file
proves that, so the label states it as "USNIC-format" and says the origin is unconfirmed.

This module depends on the standard library only, so it can be tested without the web stack.
"""
from __future__ import annotations

import csv
import math
import re
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional

# A display convention, not a validated limit: iceberg tables of this kind are refreshed on the
# order of weekly, so a week-old table is treated as the edge of "current".
OBSERVED_STALE_AFTER_DAYS = 7

DEFAULT_DIRECTORY = Path(__file__).resolve().parents[2] / "data" / "raw" / "iceberg"
_FILENAME_PATTERN = "AntarcticIcebergs_*.csv"
_FILENAME_DATE = re.compile(r"(\d{8})")

_REQUIRED = ("Iceberg", "Length (NM)", "Width (NM)", "Latitude", "Longitude", "Area (sqNM)", "Area (sqKM)", "Last Update")

_SOURCE = (
    "USNIC-format Antarctic iceberg table (column layout of the US National Ice Center iceberg "
    "list). The file's origin and retrieval date are not recorded in this repository."
)

_LIMITATIONS = [
    "Observation snapshot, not a live feed and not a forecast.",
    "The source gives no position uncertainty; none is shown.",
    "Footprints are drawn as equivalent-area circles because orientation is not provided.",
    "Not merged with the simulated catalogue, not drifted forward, and not used by the route "
    "planner or the iceberg alerts.",
]


def find_snapshot(directory: Optional[Path] = None) -> Optional[Path]:
    """The newest AntarcticIcebergs_YYYYMMDD.csv in the directory, or None."""
    folder = Path(directory) if directory is not None else DEFAULT_DIRECTORY
    if not folder.is_dir():
        return None
    candidates = sorted(folder.glob(_FILENAME_PATTERN), key=_filename_sort_key)
    return candidates[-1] if candidates else None


def _filename_sort_key(path: Path) -> str:
    match = _FILENAME_DATE.search(path.name)
    return match.group(1) if match else path.name


def _unavailable(reason: str) -> Dict[str, Any]:
    return {
        "available": False,
        "kind": "observed",
        "reason": reason,
        "setup": (
            "Place a USNIC-format CSV named AntarcticIcebergs_YYYYMMDD.csv in data/raw/iceberg/ "
            "with the columns: " + ", ".join(_REQUIRED) + "."
        ),
        "icebergs": [],
        "count": 0,
        "used_for_routing": False,
    }


def _finite(value: str) -> float:
    number = float(value)
    if not math.isfinite(number):
        raise ValueError("not a finite number")
    return number


def _parse_row(row: Dict[str, str]) -> Dict[str, Any]:
    """Validate one CSV row. Raises ValueError with a short reason when it is unusable."""
    ident = (row.get("Iceberg") or "").strip()
    if not ident:
        raise ValueError("missing iceberg id")
    lat = _finite(row["Latitude"])
    lon = _finite(row["Longitude"])
    if not -90.0 <= lat <= 90.0:
        raise ValueError(f"latitude {lat} out of range")
    if not -180.0 <= lon <= 180.0:
        raise ValueError(f"longitude {lon} out of range")
    length_nm = _finite(row["Length (NM)"])
    width_nm = _finite(row["Width (NM)"])
    area_sqnm = _finite(row["Area (sqNM)"])
    area_sqkm = _finite(row["Area (sqKM)"])
    if length_nm <= 0 or width_nm <= 0 or area_sqnm <= 0 or area_sqkm <= 0:
        raise ValueError("non-positive size")
    try:
        observed = datetime.strptime(row["Last Update"].strip(), "%m/%d/%Y").date()
    except ValueError as exc:
        raise ValueError(f"unreadable date {row['Last Update']!r}") from exc
    return {
        "id": ident,
        "latitude": lat,
        "longitude": lon,
        "length_nm": length_nm,
        "width_nm": width_nm,
        "area_sqnm": area_sqnm,
        "area_sqkm": area_sqkm,
        "observed_date": observed.isoformat(),
    }


def load_snapshot(path: Optional[Path] = None, today: Optional[date] = None) -> Dict[str, Any]:
    """
    Read and validate the snapshot.

    `today` exists so tests can fix the clock; in service it is the current UTC date. Rows that
    fail validation are reported in `rejected` rather than dropped silently.
    """
    target = Path(path) if path is not None else find_snapshot()
    if target is None or not target.is_file():
        return _unavailable("No observed-iceberg CSV was found in data/raw/iceberg/.")

    try:
        # utf-8-sig: the file carries a byte-order mark that would otherwise corrupt the first header.
        with open(target, "r", encoding="utf-8-sig", newline="") as handle:
            reader = csv.DictReader(handle)
            header = [h.strip() for h in (reader.fieldnames or [])]
            missing = [col for col in _REQUIRED if col not in header]
            if missing:
                return _unavailable(f"{target.name} is missing required columns: {', '.join(missing)}.")
            raw_rows = list(reader)
    except (OSError, UnicodeDecodeError, csv.Error) as exc:
        return _unavailable(f"{target.name} could not be read: {type(exc).__name__}: {exc}")

    icebergs: List[Dict[str, Any]] = []
    rejected: List[Dict[str, str]] = []
    for row in raw_rows:
        try:
            icebergs.append(_parse_row(row))
        except (ValueError, KeyError, TypeError) as exc:
            rejected.append({"id": (row.get("Iceberg") or "?").strip(), "reason": str(exc)})

    if not icebergs:
        return _unavailable(f"{target.name} contained no valid rows ({len(rejected)} rejected).")

    clock = today or datetime.now(timezone.utc).date()
    newest = max(date.fromisoformat(b["observed_date"]) for b in icebergs)
    age_days = (clock - newest).days
    warnings: List[str] = []
    if age_days < 0:
        warnings.append("The snapshot date is in the future relative to this server's clock; age is shown as 0.")
        age_days = 0
    stale = age_days > OBSERVED_STALE_AFTER_DAYS

    return {
        "available": True,
        "kind": "observed",
        "source": _SOURCE,
        "file": target.name,
        "observed_date": newest.isoformat(),
        "age_days": age_days,
        "stale": stale,
        "stale_after_days": OBSERVED_STALE_AFTER_DAYS,
        "stale_note": (
            f"Observed {newest.isoformat()}, {age_days} days before this server's date. "
            + (
                "That is older than the one-week currency convention used here, so these "
                "positions are STALE and must not be read as where the bergs are now."
                if stale
                else "Within the one-week currency convention used here."
            )
        ),
        "position_uncertainty": "not provided by the source",
        "used_for_routing": False,
        "count": len(icebergs),
        "rejected": rejected,
        "warnings": warnings,
        "limitations": _LIMITATIONS,
        "icebergs": icebergs,
    }
