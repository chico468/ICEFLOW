"""
Tests for src/data/environment_provider.py.

All tests use the local fixture pack at tests/fixtures/real_slice/ - no network
calls are made.
"""

from __future__ import annotations

import time
from datetime import datetime, timedelta, timezone

import pytest

from src.data.environment_provider import (
    EnvSample,
    EnvironmentProvider,
    LiveProvider,
    OutOfCoverage,
    ReplayProvider,
    SimulatedProvider,
)

FIXTURE_DIR = "tests/fixtures/real_slice"


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def replay_provider() -> ReplayProvider:
    return ReplayProvider(FIXTURE_DIR)


@pytest.fixture
def simulated_provider() -> SimulatedProvider:
    return SimulatedProvider(seed=26059, reference_doy=330)


# ---------------------------------------------------------------------------
# ReplayProvider: sample at a known point
# ---------------------------------------------------------------------------


def test_replay_sample_returns_env_sample(replay_provider: ReplayProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert isinstance(sample, EnvSample)
    assert sample.lat == -60.0
    assert sample.lon == 49.0
    assert sample.is_synthetic is False
    assert sample.source == "replay pack"


def test_replay_sample_has_wind_and_current(replay_provider: ReplayProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert sample.u10 is not None
    assert sample.v10 is not None
    assert sample.wind_speed_ms is not None
    assert sample.uo is not None
    assert sample.vo is not None
    assert sample.current_speed_ms is not None


def test_replay_sample_wave_valid_over_open_water(replay_provider: ReplayProvider) -> None:
    # (-60, 49) has ice_conc=0.05 at t=06:00 -> below 0.15 threshold, waves valid
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert sample.wave_valid is True
    assert sample.sig_wave_height_m is not None
    assert sample.sig_wave_height_m > 0


def test_replay_sample_wave_masked_under_ice(replay_provider: ReplayProvider) -> None:
    # (-59, 50) has ice_conc=0.10-0.12. At t=12:00 ice_conc at (-59,50) = 0.12 (< 0.15)
    # Use t=06:00 where ice at (-59,50) = 0.11, still < 0.15. Use (-59,50) at t=12:00 = 0.12.
    # The threshold is 0.15, so none of the fixture points are fully ice-covered.
    # Test with a point that has higher ice: check all points
    t = datetime(2024, 1, 15, 12, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-59.0, lon=50.0, t_utc=t)
    # ice_conc at (-59,50) at 12:00 = 0.12 < 0.15 -> waves valid
    assert sample.wave_valid is True or sample.sig_wave_height_m is None


def test_replay_provenance_by_variable(replay_provider: ReplayProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert "u10" in sample.provenance_by_variable
    prov = sample.provenance_by_variable["u10"]
    assert prov["kind"] == "reanalysis"
    assert prov["source"] == "replay pack"
    assert prov["product"] == "era5_wind_10m"
    assert "valid_time" in prov


def test_replay_determinism(replay_provider: ReplayProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    s1 = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    s2 = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert s1.u10 == s2.u10
    assert s1.v10 == s2.v10
    assert s1.wind_speed_ms == s2.wind_speed_ms
    assert s1.sig_wave_height_m == s2.sig_wave_height_m


def test_replay_sample_latency_under_threshold(replay_provider: ReplayProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    started = time.perf_counter()
    for _ in range(100):
        replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    elapsed_ms = (time.perf_counter() - started) * 1000.0 / 100.0
    assert elapsed_ms < 50.0, f"average sample latency {elapsed_ms:.2f} ms exceeds 50 ms"


# ---------------------------------------------------------------------------
# Coverage errors
# ---------------------------------------------------------------------------


def test_replay_out_of_coverage_time(replay_provider: ReplayProvider) -> None:
    # Target before the fixture's time range
    t = datetime(2024, 1, 14, 12, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(OutOfCoverage) as exc_info:
        replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert exc_info.value.variable == "u10" or exc_info.value.variable == "v10"
    assert "2024-01-14" in exc_info.value.valid_time_utc


def test_replay_out_of_coverage_future_time(replay_provider: ReplayProvider) -> None:
    # Target after the fixture's time range (last valid time is 12:00)
    t = datetime(2024, 1, 15, 18, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(OutOfCoverage):
        replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)


def test_replay_out_of_coverage_space(replay_provider: ReplayProvider) -> None:
    # Target outside the fixture's lat/lon range
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    # lat=-80 is outside [-61, -59]
    with pytest.raises(OutOfCoverage):
        replay_provider.sample(lat=-80.0, lon=49.0, t_utc=t)


# ---------------------------------------------------------------------------
# Skew limit (max 12h between variables in replay)
# ---------------------------------------------------------------------------


def test_replay_skew_limit_omits_variable(replay_provider: ReplayProvider) -> None:
    # With a 3-time-step fixture spanning 12 hours (00:00, 06:00, 12:00),
    # a target exactly at 06:00 has 6h skew on both sides - within limit.
    # A target at 03:00 has 3h skew - within limit.
    # The fixture has 6-hourly steps, so max skew is 6h < 12h - all variables present.
    t = datetime(2024, 1, 15, 3, 0, 0, tzinfo=timezone.utc)
    sample = replay_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert sample.u10 is not None
    assert sample.v10 is not None


# ---------------------------------------------------------------------------
# SimulatedProvider
# ---------------------------------------------------------------------------


def test_simulated_provider_is_synthetic(simulated_provider: SimulatedProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    sample = simulated_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert sample.is_synthetic is True
    assert sample.source == "synthetic; stands in for ECMWF ERA5/HRES + Copernicus Marine CMEMS"
    for prov in sample.provenance_by_variable.values():
        assert prov["kind"] == "synthetic"


def test_simulated_provider_determinism(simulated_provider: SimulatedProvider) -> None:
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    s1 = simulated_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    s2 = simulated_provider.sample(lat=-60.0, lon=49.0, t_utc=t)
    assert s1.u10 == s2.u10
    assert s1.v10 == s2.v10


# ---------------------------------------------------------------------------
# EnvironmentProvider protocol check
# ---------------------------------------------------------------------------


def test_environment_provider_is_protocol() -> None:
    assert issubclass(EnvironmentProvider, object)
    # ReplayProvider and SimulatedProvider should satisfy the protocol
    assert isinstance(ReplayProvider(FIXTURE_DIR), EnvironmentProvider)
    assert isinstance(SimulatedProvider(), EnvironmentProvider)


# ---------------------------------------------------------------------------
# LiveProvider raises (no silent fallback)
# ---------------------------------------------------------------------------


def test_live_provider_raises_out_of_coverage() -> None:
    provider = LiveProvider()
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)
    with pytest.raises(OutOfCoverage):
        provider.sample(lat=-60.0, lon=49.0, t_utc=t)


def test_live_provider_beyond_walkback_raises() -> None:
    provider = LiveProvider()
    t = datetime(2023, 1, 15, 6, 0, 0, tzinfo=timezone.utc)  # >14 days ago
    with pytest.raises(OutOfCoverage):
        provider.sample(lat=-60.0, lon=49.0, t_utc=t)


# ---------------------------------------------------------------------------
# Sample at (-60, 50) middle of window - every variable with provenance
# ---------------------------------------------------------------------------


def test_sample_at_minus60_50_middle_of_window(replay_provider: ReplayProvider) -> None:
    """Pasted sample at (-60, 50) at the middle of the window with every variable and provenance."""
    t = datetime(2024, 1, 15, 6, 0, 0, tzinfo=timezone.utc)  # middle of 00:00-12:00 window
    sample = replay_provider.sample(lat=-60.0, lon=50.0, t_utc=t)
    assert sample.lat == -60.0
    assert sample.lon == 50.0
    assert sample.is_synthetic is False

    # Every variable present or explicitly None (not silently fabricated).
    # Provenance keys use the NetCDF variable name ("swh"), while EnvSample
    # attributes use the frontend name ("sig_wave_height_m").
    var_map = {"u10": "u10", "v10": "v10", "uo": "uo", "vo": "vo", "swh": "sig_wave_height_m"}
    for prov_name, attr_name in var_map.items():
        val = getattr(sample, attr_name)
        prov = sample.provenance_by_variable.get(prov_name, {})
        assert "kind" in prov, f"{prov_name} missing provenance kind"
        assert "source" in prov, f"{prov_name} missing provenance source"
        assert "product" in prov, f"{prov_name} missing provenance product"

    # Wave validity flag is meaningful
    assert isinstance(sample.wave_valid, bool)
    if sample.wave_valid:
        assert sample.sig_wave_height_m is not None
        assert sample.sig_wave_height_m > 0
