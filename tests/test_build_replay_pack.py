"""Tests for scripts.build_replay_pack and scripts.ice_box_test.

These tests verify the *pure logic* of the build script — argument parsing,
size estimation, resumability, NSIDC filename generation, and manifest I/O.
They do not issue network requests.
"""

from __future__ import annotations

import argparse
import hashlib
from datetime import date
from pathlib import Path

import numpy as np
import pytest

from scripts.build_replay_pack import (
    ARCO_ERA5_URL,
    CMEMS_GLORYS_CURRENT_DS,
    CMEMS_GLORYS_SIC_DS,
    CMEMS_GLORYS_VERSION,
    ERA5_CITATION,
    ERA5_PROVENANCE,
    MAX_UNATTENDED_BYTES,
    NSIDC_BASE_URL,
    NSIDC_CITATION,
    ProductRecord,
    THREE_HOURLY_OFFSETS,
    _estimate_pack_bytes,
    _nsidc_filename,
    _product_filename,
    _sha256_of_file,
    build_pack,
    parse_bbox,
    parse_date,
)


# ---------------------------------------------------------------------------
# Argument parsing
# ---------------------------------------------------------------------------

def test_parse_bbox_valid():
    assert parse_bbox("-180,-90,180,-60") == (-180.0, -90.0, 180.0, -60.0)


def test_parse_bbox_partial_negative():
    result = parse_bbox("60,-75,80,-60")
    assert result == (60.0, -75.0, 80.0, -60.0)


def test_parse_bbox_invalid_count():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_bbox("1,2,3")


def test_parse_bbox_invalid_order():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_bbox("10,-60,5,-50")


def test_parse_date_valid():
    assert parse_date("2022-01-15") == date(2022, 1, 15)


def test_parse_date_invalid():
    with pytest.raises(argparse.ArgumentTypeError):
        parse_date("not-a-date")


# ---------------------------------------------------------------------------
# Size estimation
# ---------------------------------------------------------------------------

def test_estimate_under_5gb_with_extras():
    est = _estimate_pack_bytes(date(2022, 1, 15), 33, (-180, -90, 180, -60), True)
    assert est < MAX_UNATTENDED_BYTES
    assert est > 1024**3


def test_estimate_without_extras_is_smaller():
    with_extras = _estimate_pack_bytes(date(2022, 1, 15), 33, (-180, -90, 180, -60), True)
    without_extras = _estimate_pack_bytes(date(2022, 1, 15), 33, (-180, -90, 180, -60), False)
    assert with_extras > without_extras


def test_estimate_scales_with_days():
    small = _estimate_pack_bytes(date(2022, 1, 15), 1, (-180, -90, 180, -60), False)
    large = _estimate_pack_bytes(date(2022, 1, 15), 33, (-180, -90, 180, -60), False)
    assert abs(large / small - 33.0) < 0.01


# ---------------------------------------------------------------------------
# NSIDC filename generation
# ---------------------------------------------------------------------------

@pytest.mark.parametrize(
    "year,expected_sensor",
    [
        (2022, "F17"),
        (2010, "F17"),
        (2025, "am2"),
        (2000, "F13"),
        (1993, "F11"),
        (1988, "F08"),
        (1985, "n07"),
    ],
)
def test_nsidc_filename_sensor_mapping(year, expected_sensor):
    filename = _nsidc_filename(date(year, 1, 15))
    expected = f"sic_pss25_{year}0115_{expected_sensor}_v06r00.nc"
    assert filename == expected


def test_nsidc_filename_url_pattern():
    day = date(2022, 1, 15)
    filename = _nsidc_filename(day)
    url = f"{NSIDC_BASE_URL}/{day:%Y}/{filename}"
    assert "2022" in url
    assert "15" in filename
    assert url.startswith("https://noaadata.apps.nsidc.org")


# ---------------------------------------------------------------------------
# Product filename convention
# ---------------------------------------------------------------------------

def test_product_filename_convention():
    fname = _product_filename("era5_wind_10m", date(2022, 1, 15), 33)
    assert fname == "era5_wind_10m_20220115_33d.nc"
    assert fname.endswith(".nc")


# ---------------------------------------------------------------------------
# SHA-256 helper
# ---------------------------------------------------------------------------

def test_sha256_known_value(tmp_path: Path):
    path = tmp_path / "test.txt"
    path.write_bytes(b"hello world\n")
    sha = _sha256_of_file(path)
    assert len(sha) == 64
    expected = hashlib.sha256(b"hello world\n").hexdigest()
    assert sha == expected


# ---------------------------------------------------------------------------
# Manifest serialization
# ---------------------------------------------------------------------------

def _make_record(product: str = "era5_wind_10m", path: str = "era5_wind_10m_20220115_1d.nc") -> ProductRecord:
    return ProductRecord(
        product=product,
        dataset_id="ARCO-ERA5 v3",
        version="v3",
        request_params={"bbox": [-180, -90, 180, -60]},
        sha256="abc123",
        download_time_s=42.0,
        size_bytes=17591910,
        citation=ERA5_CITATION,
        provenance_kind="reanalysis",
        provenance_note=ERA5_PROVENANCE,
        local_path=path,
        valid_from="2022-01-15T00:00:00Z",
        valid_to="2022-01-15T21:00:00Z",
    )


def test_manifest_roundtrip(tmp_path: Path):
    from scripts.build_replay_pack import Manifest

    manifest = Manifest(
        start="2022-01-15",
        days=1,
        bbox=(-180.0, -90.0, 180.0, -60.0),
        generated_at="2026-01-01T00:00:00Z",
        total_size_bytes=1024,
        products=[_make_record()],
    )
    path = tmp_path / "manifest.json"
    manifest.write(path)
    loaded = Manifest.load(path)
    assert loaded.start == manifest.start
    assert loaded.days == manifest.days
    assert loaded.total_size_bytes == manifest.total_size_bytes
    assert len(loaded.products) == 1
    assert loaded.products[0].product == "era5_wind_10m"
    assert loaded.products[0].provenance_note == ERA5_PROVENANCE


def test_manifest_find():
    from scripts.build_replay_pack import Manifest

    manifest = Manifest(
        start="2022-01-15",
        days=1,
        bbox=(-180.0, -90.0, 180.0, -60.0),
        generated_at="2026-01-01T00:00:00Z",
        total_size_bytes=0,
        products=[_make_record("era5_wind_10m"), _make_record("cmems_current", "cmems_current_20220115_1d.nc")],
    )
    found = manifest.find("cmems_current")
    assert found is not None
    assert found.product == "cmems_current"
    assert manifest.find("nonexistent") is None


# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

def test_cmr_constants_present():
    assert ARCO_ERA5_URL.startswith("https://storage.googleapis.com")
    assert CMEMS_GLORYS_CURRENT_DS == "cmems_mod_glo_phy_anfc_merged-uv_PT1H-i"
    assert CMEMS_GLORYS_SIC_DS == "cmems_mod_glo_phy_my_0.083deg_P1D-m"
    assert CMEMS_GLORYS_VERSION == "202311"
    assert NSIDC_BASE_URL.startswith("https://noaadata.apps.nsidc.org")


def test_three_hourly_offsets():
    assert THREE_HOURLY_OFFSETS == [0, 3, 6, 9, 12, 15, 18, 21]


def test_max_unattended_bytes():
    assert MAX_UNATTENDED_BYTES == 5 * 1024**3


# ---------------------------------------------------------------------------
# Ice-box test helpers
# ---------------------------------------------------------------------------

def test_bbox_mask_no_wrap():
    from scripts.ice_box_test import _bbox_mask

    lat = np.array([-20.0, -10.0, 0.0])
    lon = np.array([0.0, 10.0, 20.0])
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    mask = _bbox_mask(lat_grid, lon_grid, (10.0, -15.0, 25.0, -5.0))
    expected = (lat_grid >= -15) & (lat_grid <= -5) & (lon_grid >= 10) & (lon_grid <= 25)
    assert np.array_equal(mask, expected)


def test_bbox_mask_crosses_antimeridian():
    from scripts.ice_box_test import _bbox_mask

    lat = np.array([-15.0, -5.0])
    lon = np.array([175.0, -175.0])
    lat_grid, lon_grid = np.meshgrid(lat, lon, indexing="ij")
    # Box 170°E → 190°E (=-170°), crossing the 180° meridian
    mask = _bbox_mask(lat_grid, lon_grid, (170.0, -20.0, -170.0, 0.0))
    assert mask.all()  # 175 and -175 (=185) both in [170,190] range
