"""
Tests for the simulated X-band growler radar.

Two properties matter most here. The sweep has to be deterministic, because a demo that
changes underfoot is worse than no demo and because a voyage replay must reproduce the picture
the bridge saw. And the sensor has to degrade honestly: sea clutter must grow with sea state,
detection range must fall as it does, and real targets must sometimes be missed. A radar
simulation that always sees everything would be worse than useless, because it would teach the
operator to trust a picture that cannot be trusted.
"""
from __future__ import annotations

import json

import pytest

from src.core.constants import RADAR_MAX_RANGE_NM
from src.core.environment import EnvSample
from src.core.growler_radar import (
    RadarSweep,
    detection_probability,
    effective_detection_range_nm,
    expected_target_density_per_nm2,
    highest_threat,
    sea_clutter_level,
    simulate_sweep,
)
from src.core.polaris_risk import IceType
from src.core.sea_ice import IceState

# A point inside the Prydz Bay pack, on the approach to Bharati, at 36 simulated hours.
IN_THE_PACK = dict(lat=-66.0, lon=76.0, heading_deg=190.0, speed_knots=8.0, t_hours=36.0)


def _env(sig_wave_height_m: float, wind_speed_ms: float = 10.0) -> EnvSample:
    """A minimal EnvSample carrying only the fields the clutter model reads."""
    return EnvSample(
        lat=-60.0,
        lon=30.0,
        valid_time_hours=0.0,
        u10=wind_speed_ms,
        v10=0.0,
        wind_speed_ms=wind_speed_ms,
        wind_dir_from_deg=270.0,
        wind_gust_ms=wind_speed_ms * 1.3,
        uo=0.1,
        vo=0.0,
        current_speed_ms=0.1,
        current_dir_to_deg=90.0,
        sst_c=-1.0,
        t2m_c=-5.0,
        msl_hpa=985.0,
        sig_wave_height_m=sig_wave_height_m,
        visibility_km=10.0,
        katabatic_component_ms=0.0,
    )


def _ice(concentration: float, ridging: float = 0.2) -> IceState:
    """A minimal IceState carrying only the fields the target-density model reads."""
    return IceState(
        lat=-66.0,
        lon=76.0,
        valid_time_hours=0.0,
        lead_hours=0.0,
        concentration=concentration,
        concentration_tenths=int(round(concentration * 10)),
        thickness_m=1.0,
        ice_type=IceType.MEDIUM_FIRST_YEAR,
        stage_of_development="Medium first-year ice",
        drift_u_ms=0.1,
        drift_v_ms=-0.05,
        drift_speed_ms=0.112,
        drift_dir_to_deg=117.0,
        divergence_per_s=-1.0e-6,
        compression_index=0.4,
        besetting_risk="MODERATE",
        ridging_factor=ridging,
        is_polynya=False,
        freezing_degree_days=400.0,
        concentration_uncertainty=0.04,
    )


# --------------------------------------------------------------------------------------
# Determinism
# --------------------------------------------------------------------------------------
def test_same_arguments_give_the_same_sweep():
    first = simulate_sweep(**IN_THE_PACK)
    second = simulate_sweep(**IN_THE_PACK)
    assert first.model_dump() == second.model_dump()


def test_explicit_seed_is_reproducible():
    first = simulate_sweep(**IN_THE_PACK, seed=4242)
    second = simulate_sweep(**IN_THE_PACK, seed=4242)
    assert first.model_dump() == second.model_dump()


def test_different_seeds_give_different_pictures():
    first = simulate_sweep(**IN_THE_PACK, seed=1)
    second = simulate_sweep(**IN_THE_PACK, seed=2)
    assert first.model_dump() != second.model_dump()


def test_moving_the_ship_changes_the_target_field():
    """Neighbouring positions must not share a target field, or the pack looks painted on."""
    here = simulate_sweep(**IN_THE_PACK)
    there = simulate_sweep(**{**IN_THE_PACK, "lat": -66.4})
    assert here.seed != there.seed


def test_seed_is_stable_under_floating_point_noise():
    """Arguments are quantised before hashing, so caller round-off cannot change the sweep."""
    base = simulate_sweep(**IN_THE_PACK)
    nudged = simulate_sweep(**{**IN_THE_PACK, "lat": -66.0 + 1e-9})
    assert base.seed == nudged.seed


# --------------------------------------------------------------------------------------
# Clutter and detection
# --------------------------------------------------------------------------------------
def test_clutter_rises_with_significant_wave_height():
    levels = [sea_clutter_level(_env(hs)) for hs in (0.0, 0.5, 1.5, 3.0, 4.5, 6.0)]
    assert all(later >= earlier for earlier, later in zip(levels, levels[1:]))
    assert levels[0] < levels[-1]
    assert 0.0 <= levels[0] <= 1.0 and 0.0 <= levels[-1] <= 1.0


def test_clutter_also_responds_to_wind():
    calm_wind = sea_clutter_level(_env(2.0, wind_speed_ms=3.0))
    strong_wind = sea_clutter_level(_env(2.0, wind_speed_ms=22.0))
    assert strong_wind > calm_wind


def test_detection_range_collapses_as_clutter_rises():
    """
    The point of the module in one assertion.

    A growler visible three miles out in a flat calm is visible for well under a mile in a
    heavy sea, which at twelve knots is under three minutes of warning.
    """
    ranges = [effective_detection_range_nm(c) for c in (0.0, 0.25, 0.5, 0.75, 1.0)]
    assert all(later <= earlier for earlier, later in zip(ranges, ranges[1:]))
    assert ranges[0] > 2.5
    assert ranges[-1] < 1.5


def test_detection_probability_falls_with_range():
    probabilities = [detection_probability(2.0, r, 0.1) for r in (0.5, 1.0, 2.0, 4.0, 6.0)]
    assert all(later < earlier for earlier, later in zip(probabilities, probabilities[1:]))


def test_detection_probability_rises_with_target_size():
    growler = detection_probability(1.4, 3.0, 0.2)     # about a 3 m growler
    bergy_bit = detection_probability(15.0, 3.0, 0.2)  # about a 10 m bergy bit
    small_berg = detection_probability(240.0, 3.0, 0.2)
    assert growler < bergy_bit < small_berg
    assert small_berg > 0.9


def test_detection_probability_is_a_probability():
    for rcs in (0.1, 1.0, 100.0):
        for rng_nm in (0.1, 3.0, 6.0):
            for clutter in (0.0, 0.5, 1.0):
                assert 0.0 <= detection_probability(rcs, rng_nm, clutter) <= 1.0


# --------------------------------------------------------------------------------------
# Targets come from the ice, not from nowhere
# --------------------------------------------------------------------------------------
def test_target_density_is_derived_from_ice_concentration():
    densities = [expected_target_density_per_nm2(_ice(c)) for c in (0.0, 0.2, 0.5, 0.8, 1.0)]
    assert densities[0] == 0.0
    assert all(later > earlier for earlier, later in zip(densities, densities[1:]))


def test_ridged_ice_sheds_more_targets_than_level_ice():
    level = expected_target_density_per_nm2(_ice(0.8, ridging=0.0))
    ridged = expected_target_density_per_nm2(_ice(0.8, ridging=1.5))
    assert ridged > level


def test_open_water_produces_no_ice_targets():
    """Zero ice concentration means zero real targets. Any contact is then clutter."""
    sweep = simulate_sweep(lat=-50.0, lon=30.0, heading_deg=180.0, speed_knots=12.0, t_hours=12.0)
    assert sweep.ice_concentration == 0.0
    assert sweep.true_target_count == 0
    assert all(contact.is_true_target is False for contact in sweep.contacts)


# --------------------------------------------------------------------------------------
# Honest accounting: misses and false alarms
# --------------------------------------------------------------------------------------
def test_misses_are_counted_and_the_books_balance():
    sweep = simulate_sweep(**IN_THE_PACK)
    assert sweep.true_target_count == sweep.detected_true_count + sweep.estimated_missed_targets
    assert sweep.detected_true_count == sum(1 for c in sweep.contacts if c.is_true_target)
    assert sweep.false_alarm_count == sum(1 for c in sweep.contacts if not c.is_true_target)
    assert 0 <= sweep.missed_within_alert_range <= sweep.estimated_missed_targets


def test_a_pack_ice_sweep_actually_misses_some_targets():
    """
    Growlers at the edge of the range are routinely not painted. If a sweep in close pack ever
    reported a perfect detection rate, the sensor model would be lying.
    """
    sweep = simulate_sweep(**IN_THE_PACK)
    assert sweep.true_target_count > 0
    assert sweep.estimated_missed_targets > 0


def test_clutter_generates_false_alarms():
    """Across a heavy-sea transect at least one clutter spike must paint as a contact."""
    sweeps = [
        simulate_sweep(lat=-52.0, lon=lon, heading_deg=180.0, speed_knots=10.0, t_hours=24.0)
        for lon in range(0, 60, 4)
    ]
    assert max(s.sea_clutter_level for s in sweeps) > 0.5
    assert sum(s.false_alarm_count for s in sweeps) > 0


# --------------------------------------------------------------------------------------
# Contact geometry and shape of the payload
# --------------------------------------------------------------------------------------
def test_contacts_are_inside_the_range_rings_and_well_formed():
    sweep = simulate_sweep(**IN_THE_PACK)
    for contact in sweep.contacts:
        assert 0.0 <= contact.range_nm <= RADAR_MAX_RANGE_NM
        assert 0.0 <= contact.bearing_deg < 360.0
        assert 0.0 <= contact.relative_bearing_deg < 360.0
        assert 0.0 <= contact.detection_confidence <= 1.0
        assert contact.size_class in ("growler", "bergy_bit", "small_berg")
        assert contact.threat_level in ("LOW", "MODERATE", "HIGH", "CRITICAL")
        assert contact.cpa_nm >= 0.0
        assert contact.tcpa_minutes >= 0.0
        # CPA can never exceed the present range for a closing contact, and equals it when the
        # contact is already opening.
        assert contact.cpa_nm <= contact.range_nm + 1e-6


def test_contacts_are_sorted_by_range():
    sweep = simulate_sweep(**IN_THE_PACK)
    ranges = [c.range_nm for c in sweep.contacts]
    assert ranges == sorted(ranges)


def test_a_contact_dead_ahead_closes_and_one_astern_does_not():
    sweep = simulate_sweep(**IN_THE_PACK)
    ahead = [c for c in sweep.contacts if c.relative_bearing_deg < 30.0 or c.relative_bearing_deg > 330.0]
    astern = [c for c in sweep.contacts if 150.0 < c.relative_bearing_deg < 210.0]
    assert all(c.tcpa_minutes > 0.0 for c in ahead)
    assert all(c.cpa_nm == pytest.approx(c.range_nm, abs=0.01) for c in astern)


def test_highest_threat_picks_the_worst_contact():
    sweep = simulate_sweep(**IN_THE_PACK)
    worst = highest_threat(sweep)
    if worst is None:
        assert all(c.threat_level == "LOW" for c in sweep.contacts)
    else:
        order = {"LOW": 0, "MODERATE": 1, "HIGH": 2, "CRITICAL": 3}
        assert order[worst.threat_level] == max(order[c.threat_level] for c in sweep.contacts)


def test_sweep_is_labelled_synthetic_and_serialises():
    """Build spec P2: a simulated feed must say so in the payload that carries it."""
    sweep = simulate_sweep(**IN_THE_PACK)
    assert isinstance(sweep, RadarSweep)
    assert sweep.is_synthetic is True
    assert "synthetic" in sweep.source
    assert "X-band" in sweep.source
    payload = json.loads(sweep.model_dump_json())
    assert payload["own_position"] == {"lat": -66.0, "lon": 76.0}
    assert payload["own_heading_deg"] == 190.0
    assert payload["max_range_nm"] == RADAR_MAX_RANGE_NM
