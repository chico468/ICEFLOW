"""
Real-data iceberg drift dataset construction from the BYU/NIC consolidated database.

Data source: BYU/NIC consolidated Antarctic iceberg database v6
(https://www.scp.byu.edu/iceberg/consolidated_database_v6.zip).

Each file in the database describes one iceberg, with one row per day.
Columns vary by file because only sensors that observed that iceberg are
present.  Sensor triple pattern: ``<sensor>_1`` (latitude degrees),
``<sensor>_2`` (longitude degrees), ``<sensor>_3`` (1 = observation,
0 = interpolated).  Dates are Julian day numbers ``YYYYDDD``.

This module loads the zip, consolidates positions to one (lat, lon) per
day per iceberg by averaging all available sensor observations, drops
grounded segments (speed below GROUNDING_SPEED_THRESHOLD_KNOTS), and
produces supervised learning rows for per-lead (1, 3, 7 day) drift
prediction.  The target is the position residual (truth - baseline) in
degrees, and the metric is great-circle error in km.
"""
from __future__ import annotations

import csv
import io
import math
import zipfile
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Dict, List, Optional, Sequence, Tuple

import numpy as np

from src.core.constants import KM_PER_NM
from src.core.geo import haversine_km


ICELEAD_DAYS: Tuple[int, ...] = (1, 3, 7)

TRAIN_START_YEAR = 2005
TRAIN_END_YEAR = 2017
VAL_YEAR = 2018
TEST_START_YEAR = 2019
TEST_END_YEAR = 2022

GROUNDING_SPEED_THRESHOLD_KNOTS = 0.1

DEFAULT_DATABASE_PATH = Path(__file__).resolve().parents[2] / "data" / "raw" / "iceberg" / "consolidated_database_v6.zip"

FEATURE_NAMES_ICEBERG: Tuple[str, ...] = (
    "lat_t0",
    "lon_t0",
    "baseline_vel_lat",
    "baseline_vel_lon",
    "speed_3d_knots",
    "size_major_nm",
    "size_minor_nm",
    "sin_doy",
    "cos_doy",
    "sin_lon",
    "cos_lon",
)


@dataclass
class IcebergTrack:
    """Consolidated daily track for one iceberg.

    All arrays are sorted by date ascending.  ``dates`` are ``date`` objects.
    ``lat``/``lon`` are degrees, ``size_major``/``size_minor`` are nautical
    miles (NaN where unavailable).
    """

    berg_id: str
    dates: List[date]
    lat: np.ndarray
    lon: np.ndarray
    size_major_nm: np.ndarray
    size_minor_nm: np.ndarray

    def __len__(self) -> int:
        return len(self.dates)


@dataclass
class IcebergSplit:
    """One split of the iceberg drift problem.

    Rows are sampled at (iceberg, t0) pairs.  For each row:
      * ``X`` — feature matrix
      * ``y_lat`` — target residual in latitude (degrees): truth_lat - baseline_lat
      * ``y_lon`` — target residual in longitude (degrees): truth_lon - baseline_lon
      * ``baseline_lat``/``baseline_lon`` — baseline prediction position
      * ``truth_lat``/``truth_lon`` — observed position at t0+lead
      * ``baseline_error_km`` — great-circle error of baseline prediction (km)
      * ``berg_id`` — iceberg identifier per row (for block-CI by iceberg)
      * ``lead_days`` — lead time
      * ``month`` — calendar month (for block bootstrap)
    """

    X: np.ndarray
    y_lat: np.ndarray
    y_lon: np.ndarray
    baseline_lat: np.ndarray
    baseline_lon: np.ndarray
    truth_lat: np.ndarray
    truth_lon: np.ndarray
    baseline_error_km: np.ndarray
    baseline_damped_error_km: np.ndarray
    berg_id: np.ndarray
    lead_days: np.ndarray
    month: np.ndarray
    feature_names: Tuple[str, ...]
    window_years: Tuple[int, ...]

    def __len__(self) -> int:
        return int(self.X.shape[0])


def _jd_to_date(jd_str: str) -> Optional[date]:
    """Parse a YYYYDDD Julian day string into a date, or None if invalid."""
    s = jd_str.strip()
    if len(s) != 7:
        return None
    try:
        return datetime.strptime(s, "%Y%j").date()
    except ValueError:
        return None


def _parse_float(value: Any) -> Optional[float]:
    """Parse a CSV cell into a float, returning None for empty or NaN.

    In the BYU/NIC consolidated database, the string ``"0"`` is the sentinel
    fill value for missing observations and must not be treated as a real
    coordinate.
    """
    if value is None:
        return None
    v = str(value).strip()
    if v == "" or v == "0":
        return None
    try:
        f = float(v)
        if not math.isfinite(f):
            return None
        return f
    except ValueError:
        return None


def _sensor_columns(header: List[str]) -> List[str]:
    """Extract sensor prefixes from the header.

    Sensor columns follow the pattern ``<sensor>_1`` (lat), ``<sensor>_2``
    (lon), ``<sensor>_3`` (obs/interp flag).  Returns the list of sensor
    prefix names found.
    """
    prefixes = []
    for h in header:
        if h.endswith("_1") and not h.startswith("size") and h != "date":
            prefix = h[:-2]
            if prefix not in prefixes:
                prefixes.append(prefix)
    return prefixes


def _consolidate_day(
    rows_for_day: List[Dict[str, str]],
    sensor_prefixes: List[str],
) -> Tuple[Optional[float], Optional[float]]:
    """Average lat/lon across all sensor observations for a single day.

    Returns (lat, lon) in degrees, or (None, None) if no valid observation.
    A sensor position of (0, 0) is treated as no-data.
    """
    lats: List[float] = []
    lons: List[float] = []
    for row in rows_for_day:
        for prefix in sensor_prefixes:
            lat = _parse_float(row.get(f"{prefix}_1", ""))
            lon = _parse_float(row.get(f"{prefix}_2", ""))
            if lat is not None and lon is not None:
                if lat == 0.0 and lon == 0.0:
                    continue
                lats.append(lat)
                lons.append(lon)
    if not lats:
        return None, None
    return float(np.mean(lats)), float(np.mean(lons))


def _read_berg_file(name: str, text: str) -> Optional[IcebergTrack]:
    """Parse one iceberg CSV file into an IcebergTrack (or None if unusable)."""
    reader = csv.DictReader(io.StringIO(text))
    header = [h.strip() for h in (reader.fieldnames or [])]
    if "date" not in header:
        return None

    sensor_prefixes = _sensor_columns(header)
    raw_rows = list(reader)

    first_col = header[0]
    if first_col.startswith("\ufeff"):
        header[0] = first_col.lstrip("\ufeff")
        reader2 = csv.DictReader(io.StringIO(text))
        reader2.fieldnames = header
        raw_rows = list(reader2)
        sensor_prefixes = _sensor_columns(header)

    by_date: Dict[str, List[Dict[str, str]]] = {}
    for row in raw_rows:
        raw_date = (row.get("date") or "").strip()
        if not raw_date:
            continue
        by_date.setdefault(raw_date, []).append(row)

    dates_sorted = sorted(by_date.keys())

    dates: List[date] = []
    lats: List[float] = []
    lons: List[float] = []
    sizes_major: List[float] = []
    sizes_minor: List[float] = []

    for ds in dates_sorted:
        dt = _jd_to_date(ds)
        if dt is None:
            continue
        if dt.year < 1976 or dt.year > 2022:
            continue
        lat, lon = _consolidate_day(by_date[ds], sensor_prefixes)
        if lat is None or lon is None:
            continue
        if abs(lat) > 90.0 or abs(lon) > 180.0:
            continue

        size_major: Optional[float] = None
        size_minor: Optional[float] = None
        for row in by_date[ds]:
            sm = _parse_float(row.get("size_1", ""))
            sn = _parse_float(row.get("size_2", ""))
            if size_major is None and sm is not None and sm > 0:
                size_major = sm
            if size_minor is None and sn is not None and sn > 0:
                size_minor = sn

        dates.append(dt)
        lats.append(lat)
        lons.append(lon)
        sizes_major.append(size_major if size_major is not None else float("nan"))
        sizes_minor.append(size_minor if size_minor is not None else float("nan"))

    if len(dates) < 2:
        return None

    return IcebergTrack(
        berg_id=Path(name).stem,
        dates=dates,
        lat=np.array(lats, dtype=np.float64),
        lon=np.array(lons, dtype=np.float64),
        size_major_nm=np.array(sizes_major, dtype=np.float64),
        size_minor_nm=np.array(sizes_minor, dtype=np.float64),
    )


def load_database(
    path: Optional[Path] = None,
) -> List[IcebergTrack]:
    """Load all iceberg tracks from the BYU/NIC consolidated database zip.

    Returns a list of ``IcebergTrack`` objects, one per iceberg, each with
    consolidated daily positions.  Icebergs with fewer than 2 valid days
    are skipped.
    """
    if path is None:
        path = DEFAULT_DATABASE_PATH
    path = Path(path)
    if not path.is_file():
        raise FileNotFoundError(f"Iceberg database not found at {path}")

    tracks: List[IcebergTrack] = []
    with zipfile.ZipFile(path, "r") as zf:
        csv_names = sorted(
            n for n in zf.namelist()
            if n.endswith(".csv") and "/" in n
            and "README" not in n.upper()
        )
        for name in csv_names:
            text = zf.read(name).decode("utf-8", errors="replace")
            track = _read_berg_file(name, text)
            if track is not None:
                tracks.append(track)
    return tracks


def nearest_at_or_before(
    tracks: Sequence[IcebergTrack], t0: date,
) -> Dict[str, Dict[str, Any]]:
    """Latest on-or-before-``t0`` observation for each iceberg track.

    Dates are matched exactly - the source stores Julian days ``YYYYDDD`` and
    there is no approximate, interpolated, or nearest-neighbour matching.
    Icebergs with no observation on or before ``t0`` are omitted: a berg is
    never invented.

    Returns ``{berg_id: {"latitude", "longitude", "last_obs": date,
    "size_major_nm", "size_minor_nm"}}`` where sizes are nautical miles or
    ``None`` when unavailable.
    """
    out: Dict[str, Dict[str, Any]] = {}
    for track in tracks:
        idx: Optional[int] = None
        for i, d in enumerate(track.dates):
            if d <= t0:
                idx = i
            else:
                break  # dates are sorted ascending
        if idx is None:
            continue
        size_major = float(track.size_major_nm[idx])
        size_minor = float(track.size_minor_nm[idx])
        out[track.berg_id] = {
            "latitude": float(track.lat[idx]),
            "longitude": float(track.lon[idx]),
            "last_obs": track.dates[idx],
            "size_major_nm": size_major if math.isfinite(size_major) else None,
            "size_minor_nm": size_minor if math.isfinite(size_minor) else None,
        }
    return out


def _speed_between_consecutive(track: IcebergTrack) -> np.ndarray:
    """Speed in knots between consecutive daily positions.

    Returns an array of length len(dates)-1.  NaN for invalid displacements
    (e.g. zero position, antimeridian wrap).
    """
    n = len(track.dates)
    speeds = np.full(n - 1, np.nan)
    for i in range(n - 1):
        lat1, lon1 = track.lat[i], track.lon[i]
        lat2, lon2 = track.lat[i + 1], track.lon[i + 1]
        if lat1 == 0.0 and lon1 == 0.0:
            continue
        if lat2 == 0.0 and lon2 == 0.0:
            continue
        dt_days = (track.dates[i + 1] - track.dates[i]).days
        if dt_days <= 0:
            continue
        dist_km = haversine_km(lat1, lon1, lat2, lon2)
        speed_knots = dist_km / KM_PER_NM / 24.0 / dt_days
        if math.isfinite(speed_knots) and speed_knots > 0:
            speeds[i] = speed_knots
    return speeds


def filter_moving_segments(
    tracks: List[IcebergTrack],
    min_days: int = 2,
) -> List[IcebergTrack]:
    """Drop grounded icebergs and their grounded segments.

    An iceberg is considered grounded if its average speed is below
    ``GROUNDING_SPEED_THRESHOLD_KNOTS`` (0.1 kt).  This threshold is justified
    by the physics of scatterometer tracking: a berg moving slower than 0.1 kt
    (~0.185 km/day) is either grounded or too small to produce a reliable
    scatterometer return, so its reported position is dominated by noise rather
    than signal.

    Individual grounded segments (leading/trailing days below the threshold)
    are also trimmed.
    """
    result: List[IcebergTrack] = []
    for t in tracks:
        if len(t.dates) < min_days:
            continue

        speeds = _speed_between_consecutive(t)
        valid_speeds = speeds[~np.isnan(speeds)]
        if len(valid_speeds) == 0:
            continue

        avg_speed = float(np.mean(valid_speeds))
        if avg_speed < GROUNDING_SPEED_THRESHOLD_KNOTS:
            continue

        moving_mask = speeds >= GROUNDING_SPEED_THRESHOLD_KNOTS
        if not np.any(moving_mask):
            continue

        first_moving = next(i for i, m in enumerate(moving_mask) if m)
        last_moving = max(i for i, m in enumerate(moving_mask) if m)
        end_idx = last_moving + 1

        if end_idx >= len(t.dates):
            end_idx = len(t.dates) - 1

        trimmed = IcebergTrack(
            berg_id=t.berg_id,
            dates=t.dates[first_moving:end_idx + 1],
            lat=t.lat[first_moving:end_idx + 1],
            lon=t.lon[first_moving:end_idx + 1],
            size_major_nm=t.size_major_nm[first_moving:end_idx + 1],
            size_minor_nm=t.size_minor_nm[first_moving:end_idx + 1],
        )
        result.append(trimmed)

    return result


def _baseline_velocity_window(
    track: IcebergTrack, idx: int, window: int,
) -> Tuple[float, float]:
    """Constant velocity (deg/day) from the last ``window`` days before t0.

    Returns (delta_lat_per_day, delta_lon_per_day).  Falls back to fewer
    days if not enough history.  Returns (0, 0) if no history.

    Longitude differences are normalised to [-180, 180) so that icebergs
    crossing the antimeridian (±180°) do not produce spurious ~360° jumps.
    """
    start = max(0, idx - window)
    dt_days = (track.dates[idx] - track.dates[start]).days
    if dt_days <= 0:
        return 0.0, 0.0
    dlat = track.lat[idx] - track.lat[start]
    dlon = track.lon[idx] - track.lon[start]
    dlon = ((dlon + 180.0) % 360.0) - 180.0
    return dlat / dt_days, dlon / dt_days


def _baseline_velocity_7d_damped(
    track: IcebergTrack, idx: int, damping: float = 0.5,
) -> Tuple[float, float]:
    """Constant velocity from the last 7 days, damped by ``damping``.

    Returns (delta_lat_per_day, delta_lon_per_day) in degrees/day.

    Longitude differences are normalised to [-180, 180) so that icebergs
    crossing the antimeridian do not produce spurious ~360° jumps.
    """
    start = max(0, idx - 7)
    dt_days = (track.dates[idx] - track.dates[start]).days
    if dt_days <= 0:
        return 0.0, 0.0
    dlat = track.lat[idx] - track.lat[start]
    dlon = track.lon[idx] - track.lon[start]
    dlon = ((dlon + 180.0) % 360.0) - 180.0
    return (dlat / dt_days) * damping, (dlon / dt_days) * damping


def _find_date(
    dates: List[date], target: date, start: int,
) -> Optional[int]:
    """Binary search for the exact ``target`` date in ``dates`` from index ``start``.

    Returns None when the target date is absent from the track.  Approximate
    (±1 day) matching was removed because it silently substitutes a nearby
    day as ground truth, inflating step counts and corrupting error metrics
    when a track has a date gap at t0+lead.
    """
    lo, hi = start, len(dates) - 1
    while lo <= hi:
        mid = (lo + hi) // 2
        if dates[mid] == target:
            return mid
        if dates[mid] < target:
            lo = mid + 1
        else:
            hi = mid - 1
    return None


def build_iceberg_dataset(
    tracks: List[IcebergTrack],
    start_date: date,
    end_date: date,
    leads: Sequence[int] = ICELEAD_DAYS,
    baseline_window_days: int = 3,
    rng_seed: int = 26059,
) -> IcebergSplit:
    """Build a supervised dataset from iceberg tracks for the date window.

    For each iceberg and each t0 in [start_date, end_date] where t0+lead is
    available in that iceberg's track:
      * Baseline (b): constant velocity from the last 3 days.
      * Baseline prediction: t0_pos + lead * vel_3d (in lat/lon degrees).
      * Truth: actual position at t0+lead.
      * Target: truth_pos - baseline_pos (lat/lon residual in degrees).

    The model learns the residual (truth - baseline) and the full forecast
    is baseline + residual.  Errors are measured as great-circle distance
    in km.
    """
    rows_X: List[np.ndarray] = []
    rows_y_lat: List[float] = []
    rows_y_lon: List[float] = []
    rows_base_lat: List[float] = []
    rows_base_lon: List[float] = []
    rows_truth_lat: List[float] = []
    rows_truth_lon: List[float] = []
    rows_base_err: List[float] = []
    rows_damped_err: List[float] = []
    rows_berg: List[str] = []
    rows_lead: List[int] = []
    rows_month: List[int] = []
    window_years: set = set()

    for track in tracks:
        if len(track.dates) < max(leads) + 2:
            continue

        for i in range(len(track.dates)):
            t0 = track.dates[i]
            if t0 < start_date or t0 > end_date:
                continue
            if i < baseline_window_days:
                continue

            window_years.add(t0.year)

            lat_t0 = float(track.lat[i])
            lon_t0 = float(track.lon[i])
            if abs(lat_t0) > 90.0 or abs(lon_t0) > 180.0:
                continue
            if lat_t0 == 0.0 and lon_t0 == 0.0:
                continue

            vel_lat, vel_lon = _baseline_velocity_window(track, i, baseline_window_days)
            dt_nm = math.hypot(
                abs(vel_lat * KM_PER_NM * 24.0),
                abs(vel_lon * KM_PER_NM * 24.0) * abs(math.cos(math.radians(lat_t0))),
            )
            speed_knots = dt_nm / 24.0  # deg/day -> nm/day -> knots

            size_major = float(track.size_major_nm[i]) if np.isfinite(track.size_major_nm[i]) else 5.0
            size_minor = float(track.size_minor_nm[i]) if np.isfinite(track.size_minor_nm[i]) else 2.0

            doy = t0.timetuple().tm_yday
            sin_doy = math.sin(2.0 * math.pi * doy / 365.25)
            cos_doy = math.cos(2.0 * math.pi * doy / 365.25)
            lon_for_enc = ((lon_t0 + 180.0) % 360.0) - 180.0
            sin_lon = math.sin(2.0 * math.pi * (lon_for_enc + 180.0) / 360.0)
            cos_lon = math.cos(2.0 * math.pi * (lon_for_enc + 180.0) / 360.0)

            feats = [
                lat_t0, lon_t0,
                vel_lat, vel_lon,
                speed_knots,
                size_major, size_minor,
                sin_doy, cos_doy, sin_lon, cos_lon,
            ]

            for lead in leads:
                target_date = t0 + timedelta(days=lead)
                found_idx = _find_date(track.dates, target_date, i)
                if found_idx is None:
                    continue

                lat_target = float(track.lat[found_idx])
                lon_target = float(track.lon[found_idx])
                if lat_target == 0.0 and lon_target == 0.0:
                    continue
                if abs(lat_target) > 90.0 or abs(lon_target) > 180.0:
                    continue

                pred_lat = lat_t0 + vel_lat * lead
                pred_lon = lon_t0 + vel_lon * lead
                base_err = haversine_km(pred_lat, pred_lon, lat_target, lon_target)

                damped_vel_lat, damped_vel_lon = _baseline_velocity_7d_damped(track, i)
                damped_pred_lat = lat_t0 + damped_vel_lat * lead
                damped_pred_lon = ((lon_t0 + damped_vel_lon * lead + 180.0) % 360.0) - 180.0
                damped_pred_lat = max(-90.0, min(90.0, damped_pred_lat))
                damped_err = haversine_km(damped_pred_lat, damped_pred_lon, lat_target, lon_target)

                rows_X.append(np.array(feats, dtype=np.float64))
                rows_y_lat.append(lat_target - pred_lat)
                rows_y_lon.append(lon_target - pred_lon)
                rows_base_lat.append(pred_lat)
                rows_base_lon.append(pred_lon)
                rows_truth_lat.append(lat_target)
                rows_truth_lon.append(lon_target)
                rows_base_err.append(base_err)
                rows_damped_err.append(damped_err)
                rows_berg.append(track.berg_id)
                rows_lead.append(lead)
                rows_month.append(t0.month)

    if not rows_X:
        return IcebergSplit(
            X=np.empty((0, len(FEATURE_NAMES_ICEBERG)), dtype=np.float64),
            y_lat=np.empty((0,), dtype=np.float64),
            y_lon=np.empty((0,), dtype=np.float64),
            baseline_lat=np.empty((0,), dtype=np.float64),
            baseline_lon=np.empty((0,), dtype=np.float64),
            truth_lat=np.empty((0,), dtype=np.float64),
            truth_lon=np.empty((0,), dtype=np.float64),
            baseline_error_km=np.empty((0,), dtype=np.float64),
            baseline_damped_error_km=np.empty((0,), dtype=np.float64),
            berg_id=np.empty((0,), dtype=object),
            lead_days=np.empty((0,), dtype=np.float64),
            month=np.empty((0,), dtype=np.float64),
            feature_names=FEATURE_NAMES_ICEBERG,
            window_years=tuple(),
        )

    return IcebergSplit(
        X=np.stack(rows_X, axis=0),
        y_lat=np.array(rows_y_lat, dtype=np.float64),
        y_lon=np.array(rows_y_lon, dtype=np.float64),
        baseline_lat=np.array(rows_base_lat, dtype=np.float64),
        baseline_lon=np.array(rows_base_lon, dtype=np.float64),
        truth_lat=np.array(rows_truth_lat, dtype=np.float64),
        truth_lon=np.array(rows_truth_lon, dtype=np.float64),
        baseline_error_km=np.array(rows_base_err, dtype=np.float64),
        baseline_damped_error_km=np.array(rows_damped_err, dtype=np.float64),
        berg_id=np.array(rows_berg, dtype=object),
        lead_days=np.array(rows_lead, dtype=np.float64),
        month=np.array(rows_month, dtype=np.float64),
        feature_names=FEATURE_NAMES_ICEBERG,
        window_years=tuple(sorted(window_years)),
    )
