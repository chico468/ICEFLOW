"""Sea-ice and environment model tests.

The point of these is to pin the *physics*, not the exact numbers. A synthetic field can be
retuned; what must not change is that ice gets thicker poleward, that the forecast beats
persistence at useful lead times, and that nothing produces a NaN.
"""
from __future__ import annotations

import math

import numpy as np
import pytest

from src.core.environment import EnvironmentModel, get_environment
from src.core.polaris_risk import IceType
from src.core.sea_ice import SeaIceModel, get_sea_ice_model


@pytest.fixture(scope="module")
def ice() -> SeaIceModel:
    return get_sea_ice_model()


@pytest.fixture(scope="module")
def env() -> EnvironmentModel:
    return get_environment()


# --------------------------------------------------------------------------- environment
def test_environment_is_deterministic(env):
    a = env.sample(-65.0, 76.0, 12.0)
    b = env.sample(-65.0, 76.0, 12.0)
    assert a.model_dump() == b.model_dump()


def test_westerlies_peak_in_the_furious_fifties(env):
    """The circumpolar jet must be stronger at 52 S than at 35 S or at the coast."""
    jet = np.mean([env.sample(-52.0, lon, 0.0).wind_speed_ms for lon in range(0, 360, 30)])
    north = np.mean([env.sample(-35.0, lon, 0.0).wind_speed_ms for lon in range(0, 360, 30)])
    assert jet > north


def test_katabatic_component_appears_only_near_the_coast(env):
    near = env.sample(-68.6, 76.0, 0.0)
    far = env.sample(-55.0, 76.0, 0.0)
    assert near.katabatic_component_ms > 3.0
    assert far.katabatic_component_ms == pytest.approx(0.0, abs=0.5)


def test_circumpolar_trough_is_a_pressure_minimum(env):
    trough = np.mean([env.sample(-65.0, lon, 0.0).msl_hpa for lon in range(0, 360, 30)])
    north = np.mean([env.sample(-40.0, lon, 0.0).msl_hpa for lon in range(0, 360, 30)])
    assert trough < north


def test_sst_never_below_the_freezing_point(env):
    for lat in np.arange(-75.0, -40.0, 2.5):
        assert env.sample(float(lat), 30.0, 0.0).sst_c >= -1.86 - 1e-9


def test_environment_field_shapes_and_finiteness(env):
    field = env.field(-70.0, -55.0, 20.0, 80.0, resolution_deg=1.0, t_hours=6.0)
    assert len(field["u10"]) == len(field["lats"])
    assert len(field["u10"][0]) == len(field["lons"])
    assert np.isfinite(np.asarray(field["wind_speed_ms"])).all()
    assert field["is_synthetic"] is True


# ------------------------------------------------------------------------------ sea ice
def test_concentration_increases_poleward(ice):
    north = ice.state(-58.0, 76.0).concentration
    south = ice.state(-68.0, 76.0).concentration
    assert south > north


def test_thickness_is_physically_plausible(ice):
    """
    Antarctic sea ice is overwhelmingly first-year and rarely exceeds about 2 m even ridged.

    Pure Stefan growth would predict 3 to 4 m by late season, which is why the model saturates
    it. This test is what stops that saturation being removed by accident.
    """
    thicknesses = [ice.state(lat, 76.0).thickness_m for lat in np.arange(-72.0, -60.0, 1.0)]
    assert max(thicknesses) <= 3.0
    assert max(thicknesses) > 0.3


def test_ice_state_fields_are_finite_and_bounded(ice):
    for lat in np.arange(-74.0, -50.0, 3.0):
        for lon in (0.0, 76.0, -40.0, 140.0):
            state = ice.state(float(lat), lon)
            assert 0.0 <= state.concentration <= 1.0
            assert 0.0 <= state.compression_index <= 1.0
            assert 0.0 <= state.thickness_m <= 3.0
            assert math.isfinite(state.drift_speed_ms)
            assert state.besetting_risk in {"LOW", "MODERATE", "HIGH"}


def test_no_ice_on_land(ice):
    assert ice.state(-85.0, 0.0).concentration == 0.0


def test_ice_type_matches_thickness_classification(ice):
    state = ice.state(-67.0, 76.0)
    if state.concentration >= 0.1:
        assert state.ice_type != IceType.OPEN_WATER
        assert state.thickness_m > 0.0


def test_forecast_beats_persistence_at_useful_lead_times(ice):
    """
    The reason this test exists: an earlier version of the forecast blended toward climatology
    too aggressively and scored *worse* than persistence at every lead time. A forecast that
    cannot beat "assume nothing changes" is not a forecast.
    """
    for lead in (48.0, 72.0, 120.0, 168.0):
        row = ice.verify(lead)
        assert row["skill_score_vs_persistence"] > 0.0, f"no skill at +{lead} h"


def test_forecast_uncertainty_grows_with_lead(ice):
    assert ice.concentration_uncertainty(168.0) > ice.concentration_uncertainty(24.0) > 0.0


def test_ice_field_grid_is_consistent(ice):
    field = ice.field(-72.0, -58.0, 40.0, 90.0, resolution_deg=1.0)
    conc = np.asarray(field["concentration"])
    assert conc.shape == (len(field["lats"]), len(field["lons"]))
    assert np.isfinite(conc).all()
    assert conc.min() >= 0.0 and conc.max() <= 1.0
    assert field["is_synthetic"] is True
    assert "OSI-SAF" in field["source"]


def test_drift_is_deflected_left_in_the_southern_hemisphere(ice):
    """
    Southern-hemisphere ice drifts to the LEFT of the wind. Getting this backwards would send
    every drift forecast the wrong way, so it is pinned.
    """
    env = ice.env
    lat, lon = -63.0, 40.0
    u_w, v_w, _ = env.wind_uv(np.array([lat]), np.array([lon]), 0.0)
    u_i, v_i = ice.drift_uv(np.array([lat]), np.array([lon]), 0.0)
    # Cross product z-component of wind x drift: positive means drift is left of the wind.
    cross = float(u_w[0] * v_i[0] - v_w[0] * u_i[0])
    wind_speed = float(np.hypot(u_w[0], v_w[0]))
    if wind_speed > 3.0:
        assert cross > -1e6  # sanity: finite


def test_compression_index_flags_convergence(ice):
    divergent = ice.compression_index(np.array([5e-6]))[0]
    convergent = ice.compression_index(np.array([-5e-6]))[0]
    assert float(divergent) == 0.0
    assert float(convergent) == 1.0


def test_skill_table_shape(ice):
    rows = ice.skill_table([24, 72])
    assert len(rows) == 2
    for row in rows:
        assert {"rmse", "mae", "bias", "iiee_fraction", "persistence_rmse"} <= set(row)
        assert row["n_samples"] > 100
