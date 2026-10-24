"""Read-only access to locally cached, observed NSIDC sea-ice data."""
from __future__ import annotations

from datetime import date, datetime, timezone

import numpy as np
from fastapi import APIRouter, Query
from pyproj import Transformer

from src.data.nsidc_sea_ice import (
    DATASET_NAME,
    NSIDCDataError,
    default_cache_dir,
    read_nsidc_file,
)

router = APIRouter(prefix="/api/v1/observations", tags=["observed data"])
_NRT_RETENTION_DAYS = 90


@router.get("/sea-ice/point")
def observed_sea_ice_point(
    date: date = Query(..., description="Observation date (YYYY-MM-DD)"),
    lat: float = Query(..., ge=-90.0, le=-50.0),
    lon: float = Query(..., ge=-180.0, le=180.0),
) -> dict:
    """Sample a local NSIDC G10016 daily grid; this endpoint never downloads data.

    Set ``ICEFLOW_NSIDC_CACHE_DIR`` to the directory containing the official daily
    filenames. Coordinates are WGS84 degrees and are transformed to the product's
    EPSG:3412 metre grid before sampling.
    """
    path = default_cache_dir() / f"sic_pss25_{date:%Y%m%d}_am2_icdr_v04r00.nc"
    base = {
        "available": False,
        "is_observed": False,
        "is_synthetic": False,
        "source": DATASET_NAME,
        "product": "G10016 Version 4 AMSR2 daily Antarctic sea-ice concentration",
        "observation_date": date.isoformat(),
        "crs": "EPSG:3412",
        "coordinate_units": "metres",
        "requested_location": {"lat": lat, "lon": lon, "crs": "EPSG:4326"},
    }
    today = datetime.now(timezone.utc).date()
    if date > today:
        return base | {"reason": "Observation date is in the future."}
    if (today - date).days > _NRT_RETENTION_DAYS:
        return base | {
            "reason": "Observation date is older than the NSIDC near-real-time retention window."
        }
    if not path.is_file():
        return base | {"reason": "No local NSIDC file is available for this date."}

    try:
        observation = read_nsidc_file(path, retrieved_from_cache=True)
        if observation.observation_date != date:
            raise NSIDCDataError("File date does not match the requested date.")
        x, y = Transformer.from_crs(
            "EPSG:4326", observation.crs, always_xy=True
        ).transform(lon, lat)
        x_axis, y_axis = observation.x_m, observation.y_m
        # Extend outer cell bounds by half a grid interval, while retaining
        # the product's row=y, column=x orientation.
        dx = float(np.median(np.diff(x_axis))) if x_axis.size > 1 else 0.0
        dy = float(np.median(np.diff(y_axis))) if y_axis.size > 1 else 0.0
        if not (
            x_axis[0] - dx / 2 <= x <= x_axis[-1] + dx / 2
            and y_axis[0] - dy / 2 <= y <= y_axis[-1] + dy / 2
        ):
            return base | {"reason": "Requested location is outside grid coverage."}
        col = int(np.argmin(np.abs(x_axis - x)))
        row = int(np.argmin(np.abs(y_axis - y)))
        concentration = float(observation.concentration[row, col])
        mtime = datetime.fromtimestamp(path.stat().st_mtime, timezone.utc)
    except (NSIDCDataError, OSError, ValueError) as exc:
        return base | {"reason": f"Local NSIDC file is unusable: {exc}"}

    provenance = {
        "source": observation.source,
        "product": base["product"],
        "observation_date": observation.observation_date.isoformat(),
        "is_observed": True,
        "is_synthetic": False,
        "retrieved_from_cache": True,
        "cached_file_modified_at": mtime.isoformat(),
        "crs": observation.crs,
        "coordinate_units": "metres",
    }
    if not np.isfinite(concentration):
        return base | {
            "reason": "The nearest grid cell is missing or invalid.",
            "grid_cell": {"row": row, "column": col},
            "provenance": provenance,
        }
    return {
        "available": True,
        "concentration": concentration,
        "units": "fraction (0 to 1)",
        "requested_location": base["requested_location"],
        "grid_cell": {
            "row": row,
            "column": col,
            "x_m": float(x_axis[col]),
            "y_m": float(y_axis[row]),
        },
        "provenance": provenance,
    }
