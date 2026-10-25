from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr

from src.data.nsidc_sea_ice import read_nsidc_file


def make_v6_netcdf(path: Path, values_0_100: np.ndarray) -> Path:
    y_size, x_size = values_0_100.shape[-2:]
    dataset = xr.Dataset(
        {
            "cdr_seaice_conc": (
                ("time", "y", "x"),
                values_0_100[np.newaxis, ...],
            )
        },
        coords={
            "time": np.array(["2024-01-01"], dtype="datetime64[ns]"),
            "y": np.arange(y_size, dtype=np.float64) * 25_000.0,
            "x": np.arange(x_size, dtype=np.float64) * 25_000.0,
        },
    )
    dataset["cdr_seaice_conc"].attrs["units"] = "1"
    dataset["cdr_seaice_conc"].attrs["grid_mapping"] = "crs"
    dataset["cdr_seaice_conc"].attrs["valid_range"] = np.array([0, 100])
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


def test_g02202_v6_layout(tmp_path: Path):
    source = tmp_path / "sic_pss25_20240101_F17_v06r00.nc"
    make_v6_netcdf(source, np.array([[25, 100, 0]]))
    obs = read_nsidc_file(source)
    assert abs(obs.concentration[0, 0] - 0.25) < 1e-6
    assert obs.concentration[0, 1] == 1.0
    assert obs.concentration[0, 2] == 0.0


def test_g02202_v6_flags_become_nan(tmp_path: Path):
    source = tmp_path / "sic_pss25_20250101_am2_v06r00.nc"
    values = np.array([[50, 251]])  # 251 could be flag-like
    make_v6_netcdf(source, values)
    obs = read_nsidc_file(source)
    assert obs.concentration[0, 1] != obs.concentration[0, 1]  # NaN
