from datetime import date

import numpy as np
import pytest
import xarray as xr
from fastapi.testclient import TestClient
from pyproj import Transformer

from src.api.main import app
from src.api.routers import observed_ice


@pytest.fixture
def client():
    with TestClient(app) as test_client:
        yield test_client


def write_grid(path, values):
    x0, y0 = Transformer.from_crs(
        "EPSG:4326", "EPSG:3412", always_xy=True
    ).transform(0.0, -70.0)
    ds = xr.Dataset(
        {"cdr_seaice_conc": (("time", "y", "x"), values[np.newaxis])},
        coords={
            "time": np.array(["2026-10-21"], dtype="datetime64[ns]"),
            "y": y0 + np.arange(values.shape[0]) * 25_000.0,
            "x": x0 + np.arange(values.shape[1]) * 25_000.0,
        },
    )
    ds["cdr_seaice_conc"].attrs["units"] = "1"
    ds["cdr_seaice_conc"].attrs["grid_mapping"] = "crs"
    ds["x"].attrs["units"] = "meters"
    ds["y"].attrs["units"] = "meters"
    ds["crs"] = xr.DataArray(0)
    ds["crs"].attrs.update(
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
    ds.to_netcdf(path, engine="netcdf4")
    ds.close()


def test_observed_endpoint_reads_cached_grid_and_reports_provenance(
    tmp_path, monkeypatch, client
):
    file = tmp_path / "sic_pss25_20261021_am2_icdr_v04r00.nc"
    write_grid(file, np.array([[0.4, 0.6], [0.7, 0.8]]))
    monkeypatch.setattr(observed_ice, "default_cache_dir", lambda: tmp_path)

    response = client.get(
        "/api/v1/observations/sea-ice/point",
        params={"date": "2026-10-21", "lat": -70, "lon": 0},
    )

    assert response.status_code == 200
    body = response.json()
    assert body["available"] is True
    assert body["concentration"] == pytest.approx(0.4)
    assert body["provenance"]["is_observed"] is True
    assert body["provenance"]["is_synthetic"] is False
    assert body["provenance"]["retrieved_from_cache"] is True
    assert body["provenance"]["crs"] == "EPSG:3412"
    assert body["provenance"]["cached_file_modified_at"]


def test_observed_endpoint_reports_missing_file_and_missing_cell(
    tmp_path, monkeypatch, client
):
    monkeypatch.setattr(observed_ice, "default_cache_dir", lambda: tmp_path)
    params = {"date": "2026-10-21", "lat": -70, "lon": 0}
    missing_file = client.get("/api/v1/observations/sea-ice/point", params=params)
    assert missing_file.status_code == 200
    assert missing_file.json()["available"] is False
    assert missing_file.json()["is_observed"] is False
    assert "No local NSIDC file" in missing_file.json()["reason"]

    file = tmp_path / "sic_pss25_20261021_am2_icdr_v04r00.nc"
    write_grid(file, np.array([[np.nan, 0.6], [0.7, 0.8]]))
    missing_cell = client.get("/api/v1/observations/sea-ice/point", params=params)
    assert missing_cell.json()["available"] is False
    assert "missing or invalid" in missing_cell.json()["reason"]
    assert missing_cell.json()["provenance"]["is_observed"] is True


def test_observed_endpoint_rejects_dates_outside_nrt_retention(client):
    old_date = date.today().replace(year=date.today().year - 1)
    response = client.get(
        "/api/v1/observations/sea-ice/point",
        params={"date": old_date.isoformat(), "lat": -70, "lon": 0},
    )
    assert response.status_code == 200
    assert response.json()["available"] is False
    assert "retention window" in response.json()["reason"]


@pytest.mark.parametrize(
    "params",
    [
        {"date": "not-a-date", "lat": -70, "lon": 0},
        {"date": "2026-10-21", "lat": 0, "lon": 0},
        {"date": "2026-10-21", "lat": -70, "lon": 181},
    ],
)
def test_observed_endpoint_validates_requests(client, params):
    response = client.get("/api/v1/observations/sea-ice/point", params=params)
    assert response.status_code == 422


def test_existing_synthetic_ice_contract_remains_unchanged(client):
    response = client.get("/api/v1/ice/point", params={"lat": -70, "lon": 0})
    assert response.status_code == 200
    assert response.json()["is_synthetic"] is True
    assert 0 <= response.json()["concentration"] <= 1

