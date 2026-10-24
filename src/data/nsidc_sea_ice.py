"""Reader for Antarctic sea-ice concentration from NSIDC G10016 Version 4.

This module reads observational data only. It does not generate synthetic values,
forecast sea ice, or change ICEFLOW's existing SeaIceModel.

Dataset documentation:
https://nsidc.org/data/g10016/versions/4
"""

from __future__ import annotations

import os
import re
import sys
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import numpy as np
import xarray as xr
from pyproj import CRS, Transformer


BASE_URL = (
    "https://noaadata.apps.nsidc.org/NOAA/G10016_V4/"
    "south/daily"
)
DATASET_NAME = "NOAA/NSIDC G10016 Version 4"
CRS_EPSG = "EPSG:3412"
CONCENTRATION_VARIABLE = "cdr_seaice_conc"

_FILENAME_RE = re.compile(
    r"^sic_pss25_(\d{8})_am2_icdr_v04r00\.nc$"
)


class NSIDCDataError(RuntimeError):
    """The downloaded or local NSIDC file could not be read safely."""


class NSIDCUnavailableError(RuntimeError):
    """No suitable NSIDC observation was available."""


@dataclass(frozen=True)
class SeaIceObservation:
    """One daily observed Antarctic sea-ice concentration grid.

    concentration is a fraction from 0 to 1. Missing or invalid cells are NaN.
    x_m and y_m are projected grid-cell centres in metres.
    """

    observation_date: date
    concentration: np.ndarray = field(repr=False)
    x_m: np.ndarray = field(repr=False)
    y_m: np.ndarray = field(repr=False)
    source_url: str
    retrieved_from_cache: bool = False

    @property
    def source(self) -> str:
        return DATASET_NAME

    @property
    def crs(self) -> str:
        return CRS_EPSG

    @property
    def is_synthetic(self) -> bool:
        return False

    @property
    def valid_cell_count(self) -> int:
        return int(np.isfinite(self.concentration).sum())

    @property
    def missing_cell_count(self) -> int:
        return int(self.concentration.size - self.valid_cell_count)

    def lat_lon_grid(self) -> tuple[np.ndarray, np.ndarray]:
        """Return (latitude, longitude) grids in degrees.

        The full grid is transformed only when this method is called, avoiding
        unnecessary coordinate arrays when callers only need concentration.
        """
        transformer = Transformer.from_crs(
            self.crs,
            "EPSG:4326",
            always_xy=True,
        )
        xx, yy = np.meshgrid(self.x_m, self.y_m)
        longitude, latitude = transformer.transform(xx, yy)
        return (
            np.asarray(latitude, dtype=np.float64),
            np.asarray(longitude, dtype=np.float64),
        )


def default_cache_dir() -> Path:
    """Choose a user-level cache directory outside the Git repository."""
    configured = os.environ.get("ICEFLOW_NSIDC_CACHE_DIR")
    if configured:
        return Path(configured).expanduser()

    if sys.platform == "darwin":
        return (
            Path.home()
            / "Library"
            / "Caches"
            / "ICEFLOW"
            / "nsidc"
        )

    cache_home = Path(
        os.environ.get("XDG_CACHE_HOME", Path.home() / ".cache")
    ).expanduser()
    return cache_home / "iceflow" / "nsidc"


def _date_from_filename(path: Path) -> date:
    match = _FILENAME_RE.fullmatch(path.name)
    if not match:
        raise NSIDCDataError(
            f"Unexpected NSIDC filename: {path.name!r}. "
            "Expected a daily Antarctic G10016 V4 AMSR2 file."
        )
    try:
        return datetime.strptime(match.group(1), "%Y%m%d").date()
    except ValueError as exc:
        raise NSIDCDataError(
            f"Invalid observation date in filename: {path.name}"
        ) from exc


def read_nsidc_file(
    path: str | Path,
    *,
    source_url: str | None = None,
    retrieved_from_cache: bool = False,
) -> SeaIceObservation:
    """Read and validate one downloaded or locally stored NSIDC NetCDF file."""
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        raise NSIDCDataError(f"NSIDC file does not exist: {file_path}")

    observation_date = _date_from_filename(file_path)

    try:
        with xr.open_dataset(
            file_path,
            engine="netcdf4",
            decode_cf=True,
            mask_and_scale=True,
        ) as dataset:
            if CONCENTRATION_VARIABLE not in dataset.data_vars:
                raise NSIDCDataError(
                    f"Required variable {CONCENTRATION_VARIABLE!r} "
                    f"is absent from {file_path.name}."
                )

            if "x" not in dataset.variables or "y" not in dataset.variables:
                raise NSIDCDataError(
                    "The file lacks the projected x/y grid coordinates."
                )
            if "crs" not in dataset.variables:
                raise NSIDCDataError("The file lacks its projected CRS metadata.")
            for coordinate in (dataset["x"], dataset["y"]):
                if coordinate.attrs.get("units", "").strip().lower() not in {
                    "m", "meter", "meters", "metre", "metres"
                }:
                    raise NSIDCDataError(
                        "Projected x/y coordinate units must be metres."
                    )
            if dataset[CONCENTRATION_VARIABLE].attrs.get("grid_mapping") != "crs":
                raise NSIDCDataError(
                    "Concentration data must reference the file's crs mapping."
                )
            try:
                file_crs = CRS.from_cf(dataset["crs"].attrs)
            except Exception as exc:
                raise NSIDCDataError("The file's CRS metadata is invalid.") from exc
            expected_crs = CRS.from_epsg(3412)
            actual_operation = file_crs.coordinate_operation
            expected_operation = expected_crs.coordinate_operation
            actual_parameters = {
                parameter.name: parameter.value
                for parameter in actual_operation.params
            }
            expected_parameters = {
                parameter.name: parameter.value
                for parameter in expected_operation.params
            }
            projection_matches = (
                actual_operation.method_name == expected_operation.method_name
                and actual_parameters.keys() == expected_parameters.keys()
                and all(
                    np.isclose(actual_parameters[key], expected_parameters[key])
                    for key in expected_parameters
                )
                and np.isclose(
                    file_crs.ellipsoid.semi_minor_metre,
                    expected_crs.ellipsoid.semi_minor_metre,
                    rtol=0.0,
                    atol=1e-6,
                )
            )
            if not projection_matches:
                raise NSIDCDataError("Expected the NSIDC Antarctic CRS EPSG:3412.")

            # Drop only a singleton time dimension. Squeezing all singleton
            # axes would also collapse valid one-row or one-column grids.
            concentration_data = dataset[CONCENTRATION_VARIABLE]
            if "time" in concentration_data.dims:
                if concentration_data.sizes["time"] != 1:
                    raise NSIDCDataError(
                        "Expected a single time step in the concentration data."
                    )
                concentration_data = concentration_data.isel(time=0)
            values = np.asarray(
                concentration_data.values,
                dtype=np.float64,
            )
            if concentration_data.dims != ("y", "x"):
                raise NSIDCDataError(
                    "Concentration dimensions must be ordered as y, x."
                )

            x_m = np.asarray(dataset["x"].values, dtype=np.float64)
            y_m = np.asarray(dataset["y"].values, dtype=np.float64)

    except NSIDCDataError:
        raise
    except Exception as exc:
        raise NSIDCDataError(
            f"Could not read NSIDC NetCDF file {file_path.name}: {exc}"
        ) from exc

    if values.ndim != 2:
        raise NSIDCDataError(
            f"Expected a two-dimensional concentration grid; "
            f"received shape {values.shape}."
        )

    if x_m.ndim != 1 or y_m.ndim != 1:
        raise NSIDCDataError("Projected x and y coordinates must be 1-D arrays.")

    if (
        not np.isfinite(x_m).all()
        or not np.isfinite(y_m).all()
        or (x_m.size > 1 and not np.all(np.diff(x_m) > 0))
        or (y_m.size > 1 and not np.all(np.diff(y_m) > 0))
    ):
        raise NSIDCDataError("Projected x/y coordinates must increase in grid order.")

    if values.shape != (y_m.size, x_m.size):
        raise NSIDCDataError(
            f"Grid shape {values.shape} does not match "
            f"y/x coordinate lengths {(y_m.size, x_m.size)}."
        )

    # Do not convert missing values to zero. Zero is a real measurement
    # indicating no sea-ice concentration; NaN indicates unavailable/invalid data.
    valid = np.isfinite(values) & (values >= 0.0) & (values <= 1.0)
    concentration = np.where(valid, values, np.nan).astype(np.float64)

    if not np.isfinite(concentration).any():
        raise NSIDCDataError(
            f"No valid concentration measurements found in {file_path.name}."
        )

    # Protect the returned data from accidental mutation by downstream callers.
    concentration.setflags(write=False)
    x_m.setflags(write=False)
    y_m.setflags(write=False)

    return SeaIceObservation(
        observation_date=observation_date,
        concentration=concentration,
        x_m=x_m,
        y_m=y_m,
        source_url=source_url or file_path.resolve().as_uri(),
        retrieved_from_cache=retrieved_from_cache,
    )


class NSIDCSeaIceReader:
    """Fetch recent daily Antarctic NSIDC observations, with explicit cache status."""

    def __init__(
        self,
        cache_dir: str | Path | None = None,
        *,
        timeout_seconds: float = 30.0,
        max_age_days: int = 10,
    ) -> None:
        if timeout_seconds <= 0:
            raise ValueError("timeout_seconds must be positive.")
        if not 1 <= max_age_days <= 30:
            raise ValueError("max_age_days must be between 1 and 30.")

        self.cache_dir = Path(cache_dir) if cache_dir else default_cache_dir()
        self.timeout_seconds = timeout_seconds
        self.max_age_days = max_age_days

    @staticmethod
    def _filename(day: date) -> str:
        return (
            f"sic_pss25_{day:%Y%m%d}_am2_icdr_v04r00.nc"
        )

    def _url(self, day: date) -> str:
        return f"{BASE_URL}/{day:%Y}/{self._filename(day)}"

    def _read_cached(
        self,
        day: date,
        *,
        source_url: str,
    ) -> SeaIceObservation | None:
        cached_path = self.cache_dir / self._filename(day)
        if not cached_path.is_file():
            return None

        try:
            return read_nsidc_file(
                cached_path,
                source_url=source_url,
                retrieved_from_cache=True,
            )
        except NSIDCDataError:
            # Ignore an incomplete or corrupt cached download.
            try:
                cached_path.unlink(missing_ok=True)
            except OSError:
                pass
            return None

    def _newest_usable_cache(
        self,
        today: date,
    ) -> SeaIceObservation | None:
        for days_back in range(1, self.max_age_days + 1):
            day = today - timedelta(days=days_back)
            observation = self._read_cached(day, source_url=self._url(day))
            if observation is not None:
                return observation
        return None

    def fetch_latest(
        self,
        *,
        today: date | None = None,
    ) -> SeaIceObservation:
        """Download the most recent available file within the search window.

        The service is tried first for each date. If the service is unreachable,
        the newest valid cached observation within the same date window may be
        returned with retrieved_from_cache=True. Synthetic fallback is never used.
        """
        if today is None:
            today = datetime.now(timezone.utc).date()

        self.cache_dir.mkdir(parents=True, exist_ok=True)
        errors: list[str] = []

        for days_back in range(1, self.max_age_days + 1):
            day = today - timedelta(days=days_back)
            filename = self._filename(day)
            url = self._url(day)
            target = self.cache_dir / filename

            request = urllib.request.Request(
                url,
                headers={"User-Agent": "ICEFLOW NSIDC observational reader"},
            )

            try:
                with urllib.request.urlopen(
                    request,
                    timeout=self.timeout_seconds,
                ) as response:
                    payload = response.read()

            except urllib.error.HTTPError as exc:
                if exc.code in (404, 410):
                    cached = self._read_cached(day, source_url=url)
                    if cached is not None:
                        return cached
                    errors.append(f"{day}: HTTP {exc.code}")
                    continue

                errors.append(f"{day}: HTTP {exc.code}")
                break

            except (urllib.error.URLError, TimeoutError, OSError) as exc:
                errors.append(f"{day}: network error ({exc})")
                break

            if not payload:
                errors.append(f"{day}: server returned an empty file")
                continue

            temporary = target.with_name(target.name + ".part")
            try:
                temporary.write_bytes(payload)
                temporary.replace(target)
                return read_nsidc_file(
                    target,
                    source_url=url,
                    retrieved_from_cache=False,
                )
            except (OSError, NSIDCDataError) as exc:
                errors.append(f"{day}: invalid download ({exc})")
                try:
                    temporary.unlink(missing_ok=True)
                    target.unlink(missing_ok=True)
                except OSError:
                    pass

        # A valid observed file is preferable to no data, but its cached status
        # and actual observation date remain visible to the caller.
        cached = self._newest_usable_cache(today)
        if cached is not None:
            return cached

        details = "; ".join(errors[-4:]) or "no candidate files were available"
        raise NSIDCUnavailableError(
            f"No usable recent {DATASET_NAME} observation was available "
            f"within the last {self.max_age_days} days. Details: {details}"
        )
