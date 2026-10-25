from __future__ import annotations

import sys
from types import SimpleNamespace

import numpy as np

from src.data.real_flow import read_gfs_grib
from src.data import fetch_copernicus_current


def test_gfs_reader_accepts_ec_codes_canonical_wind_units(tmp_path, monkeypatch):
    messages = ["10u", "10v"]
    grids = {
        "10u": np.array([4.0, 5.0, 6.0, 7.0]),
        "10v": np.array([-2.0, -1.0, 0.0, 1.0]),
    }

    def next_message(_stream):
        return messages.pop(0) if messages else None

    def get(message, key):
        return {
            "shortName": message,
            "typeOfLevel": "heightAboveGround",
            "level": 10,
            "units": "ms**-1",
            "dataDate": 20261023,
            "dataTime": 0,
            "validityDate": 20261023,
            "validityTime": 0,
            "forecastTime": 0,
        }[key]

    eccodes = SimpleNamespace(
        codes_grib_new_from_file=next_message,
        codes_get=get,
        codes_get_array=lambda message, key: {
            "latitudes": [-25.0, -25.0, -26.0, -26.0],
            "longitudes": [0.0, 1.0, 0.0, 1.0],
            "values": grids[message],
        }[key],
        codes_release=lambda _message: None,
    )
    monkeypatch.setitem(sys.modules, "eccodes", eccodes)
    path = tmp_path / "wind.grib2"
    path.write_bytes(b"GRIB")

    lats, lons, u, v, metadata = read_gfs_grib(path)

    assert lats.tolist() == [-26.0, -25.0]
    assert lons.tolist() == [0.0, 1.0]
    assert u.shape == v.shape == (2, 2)
    assert metadata["units"] == "m/s"
    assert metadata["classification"] == "model_analysis"
    assert metadata["valid_time"] == "2026-10-23T00:00:00+00:00"


def test_copernicus_fetch_reports_missing_toolbox_clearly(monkeypatch):
    monkeypatch.setattr(fetch_copernicus_current, "_find_copernicus_executable", lambda: None)
    spawned = []
    monkeypatch.setattr(fetch_copernicus_current.subprocess, "run", lambda *args, **kwargs: spawned.append((args, kwargs)) or SimpleNamespace(returncode=0))
    try:
        fetch_copernicus_current.fetch("2026-10-23")
    except RuntimeError as exc:
        assert "requirements-optional.txt" in str(exc)
    else:
        raise AssertionError("missing Copernicus Toolbox must be reported before attempting a fetch")
    assert spawned == []
