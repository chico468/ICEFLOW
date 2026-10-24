from __future__ import annotations

import io
from datetime import date
from pathlib import Path
from urllib.error import HTTPError

import numpy as np
import pytest
import xarray as xr

from src.data.nsidc_sea_ice import (
    NSIDCSeaIceReader,
    NSIDCUnavailableError,
    read_nsidc_file,
)


def make_netcdf(path: Path, values: np.ndarray) -> Path:
    """Build a small NetCDF file using the official daily filename pattern."""
    y_size, x_size = values.shape[-2:]
    dataset = xr.Dataset(
        {
            "cdr_seaice_conc": (
                ("time", "y", "x"),
                values[np.newaxis, ...],
            )
        },
        coords={
            "time": np.array(["2026-10-21"], dtype="datetime64[ns]"),
            "y": np.arange(y_size, dtype=np.float64) * 25_000.0,
            "x": np.arange(x_size, dtype=np.float64) * 25_000.0,
        },
    )
    dataset["cdr_seaice_conc"].attrs["units"] = "1"
    dataset["cdr_seaice_conc"].attrs["grid_mapping"] = "crs"
    dataset["x"].attrs["units"] = "meters"
    dataset["y"].attrs["units"] = "meters"
    dataset["crs"] = xr.DataArray(0)
    dataset["crs"].attrs.update(
        {
            "grid_mapping_name": "polar_stereographic",
            "latitude_of_projection_origin": -90.0,
            "straight_vertical_longitude_from_pole": 0.0,
            "standard_parallel": -70.0,
            "false_easting": 0.0,
            "false_northing": 0.0,
            "semi_major_axis": 6378273.0,
            "inverse_flattening": 298.279411123064,
        }
    )
    dataset.to_netcdf(path, engine="netcdf4")
    dataset.close()
    return path


def test_reader_preserves_missing_and_invalid_values(tmp_path: Path) -> None:
    source = tmp_path / "sic_pss25_20261021_am2_icdr_v04r00.nc"
    values = np.array([[0.25, np.nan, 0.50, 1.01, -0.1]])
    make_netcdf(source, values)

    observation = read_nsidc_file(source)

    assert observation.observation_date == date(2026, 10, 21)
    assert observation.source == "NOAA/NSIDC G10016 Version 4"
    assert observation.crs == "EPSG:3412"
    assert observation.is_synthetic is False
    assert observation.valid_cell_count == 2
    assert observation.missing_cell_count == 3
    assert observation.concentration[0, 0] == pytest.approx(0.25)
    assert np.isnan(observation.concentration[0, 1])
    assert observation.concentration[0, 2] == pytest.approx(0.50)
    assert np.isnan(observation.concentration[0, 3])
    assert np.isnan(observation.concentration[0, 4])


def test_projected_grid_can_be_transformed_to_latitude_longitude(
    tmp_path: Path,
) -> None:
    source = tmp_path / "sic_pss25_20261021_am2_icdr_v04r00.nc"
    make_netcdf(source, np.full((2, 3), 0.5))
    observation = read_nsidc_file(source)

    latitude, longitude = observation.lat_lon_grid()

    assert latitude.shape == (2, 3)
    assert longitude.shape == (2, 3)
    assert np.isfinite(latitude).all()
    assert np.isfinite(longitude).all()
    assert (latitude < 0).all()


def test_fetch_downloads_and_parses_a_daily_file(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    filename = "sic_pss25_20261021_am2_icdr_v04r00.nc"
    source = tmp_path / filename
    make_netcdf(source, np.full((2, 3), 0.65))
    payload = source.read_bytes()

    def fake_urlopen(request, timeout):
        assert request.full_url.endswith(filename)
        return io.BytesIO(payload)

    monkeypatch.setattr(
        "src.data.nsidc_sea_ice.urllib.request.urlopen",
        fake_urlopen,
    )

    reader = NSIDCSeaIceReader(
        cache_dir=tmp_path / "cache",
        max_age_days=3,
    )
    observation = reader.fetch_latest(today=date(2026, 10, 22))

    assert observation.observation_date == date(2026, 10, 21)
    assert observation.retrieved_from_cache is False
    assert observation.valid_cell_count == 6
    assert observation.concentration.mean() == pytest.approx(0.65)
    assert (tmp_path / "cache" / filename).is_file()


def test_download_failure_raises_instead_of_generating_synthetic_data(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    attempts = []

    def fake_not_found(request, timeout):
        attempts.append(request.full_url)
        raise HTTPError(
            request.full_url,
            404,
            "Not Found",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(
        "src.data.nsidc_sea_ice.urllib.request.urlopen",
        fake_not_found,
    )

    cache_dir = tmp_path / "cache"
    reader = NSIDCSeaIceReader(
        cache_dir=cache_dir,
        max_age_days=3,
    )

    with pytest.raises(NSIDCUnavailableError, match="No usable recent"):
        reader.fetch_latest(today=date(2026, 10, 22))

    assert len(attempts) == 3
    assert not list(cache_dir.glob("*.nc"))
