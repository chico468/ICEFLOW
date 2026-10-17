"""
Near-field tactical layer: a simulated X-band marine radar PPI sweep for growlers.

WHAT THIS IS, PLAINLY
---------------------
This is a *simulated* radar feed. There is no radar attached to this prototype. The module
stands in for two real shipboard sensors that a deployed system would consume directly: the
bridge X-band marine radar, read off its plan-position indicator as raw video, and a bridge
thermal camera looking over the bow. In production the detection step would be a YOLO-class
convolutional detector running on an edge computer against that raw PPI imagery and the
thermal frames, with the ARPA tracker supplying target motion. None of that exists here. What
exists here is a physically-shaped stand-in that produces the same *kind* of output, so the
rest of the system can be built and demonstrated against a realistic contact stream.

Everything this module emits is labelled `is_synthetic = True`, per build spec P2.

WHY BOTHER SIMULATING IT AT ALL
-------------------------------
Because growlers are the hazard that the strategic layer cannot see. A growler is a fragment
of glacial ice a few metres across showing less than a metre of freeboard. It carries the
density and hardness of glacial ice, so it will hole a hull, and it is far too small for
passive microwave or even SAR at the resolution an operational feed provides. It has to be
found in the last three miles, by radar and by eye, and in a rising sea it frequently is not
found at all. A decision-support system that quietly assumes every growler gets detected is
lying about the one hazard it is least able to help with.

So this module models **misses and false alarms explicitly**. A real target that the detection
model fails to see is generated, counted, and reported as a miss. Sea clutter generates
contacts that are not there. Both numbers are on the `RadarSweep`, and the honest reading of
a sweep in a four-metre sea is "the picture is mostly clutter and we are probably missing
growlers inside a mile".

HOW A SWEEP IS BUILT
--------------------
1.  Targets come from the local ice state, not from nowhere. `SeaIceModel.state()` is sampled
    at the own-ship position; the expected areal density of small ice targets scales with ice
    concentration and with the ridging factor, because ridged and rafted ice sheds far more
    broken fragments than undeformed level ice. Zero concentration means zero ice targets.
2.  Each target gets a waterline length from a decaying distribution, so growlers dominate and
    the occasional small berg appears, and a freeboard and radar cross-section from that
    length.
3.  Detection probability comes from a signal-to-interference ratio: the radar equation gives
    the returned power falling as the fourth power of range, sea clutter is added as an
    interference floor that grows with significant wave height and decays with range, and a
    logistic curve on the resulting margin gives the probability of a hit.
4.  Closest point of approach and time to CPA are computed against own course and speed using
    the geodesy helpers, with the target drifting at the local ice-drift velocity.
5.  Threat level combines CPA, TCPA and target size.

The sweep is fully deterministic. The same arguments always produce the same picture, because
a demo that changes underfoot is worse than no demo (build spec P3).
"""
from __future__ import annotations

import math
import zlib
from typing import Dict, List, Optional, Tuple

import numpy as np
from pydantic import BaseModel, Field

from src.core.constants import (
    GROWLER_ALERT_RANGE_NM,
    MS_PER_KNOT,
    RADAR_ANTENNA_RPM,
    RADAR_BAND_GHZ,
    RADAR_CLUTTER_WAVE_HEIGHT_M,
    RADAR_DETECTION_SNR_DB,
    RADAR_FALSE_ALARM_DENSITY_PER_NM2,
    RADAR_MAX_RANGE_NM,
    RADAR_REFERENCE_RCS_M2,
    RADAR_SEED,
    RADAR_SNR_SOFTNESS_DB,
    RADAR_TARGET_DENSITY_PER_NM2,
    SIZE_CLASS_THRESHOLDS_M,
)
from src.core.environment import EnvironmentModel, EnvSample, get_environment
from src.core.geo import destination_point, haversine_nm, initial_bearing_deg
from src.core.sea_ice import IceState, SeaIceModel, get_sea_ice_model

# --------------------------------------------------------------------------------------
# Sensor model constants, kept local because they describe this simulated sensor rather
# than a physical property of the world.
# --------------------------------------------------------------------------------------
#: Reference signal-to-noise margin, in dB, of a 1 m2 target at 1 nm in a flat calm. Chosen so
#: that a 3 m growler is reliably painted inside a mile and marginal near three miles, which is
#: what bridge officers report from a 25 kW X-band set with a 6 ft open array.
_SNR_REFERENCE_DB = 30.0
#: Sea clutter interference at zero range and saturated sea state, in dB.
_CLUTTER_PEAK_DB = 30.0
#: Range scale over which clutter decays, in nm. Clutter is a grazing-incidence return, so it
#: is worst close in and thins out with range; 2 nm is representative of a heavy sea.
_CLUTTER_RANGE_SCALE_NM = 2.0
#: Radius within which clutter-driven false alarms are generated, in nm.
_FALSE_ALARM_RADIUS_NM = 3.0
#: Freeboard as a fraction of waterline length. Growlers show well under a metre; this ratio
#: puts a 3 m growler at 0.45 m and a 10 m bergy bit at 1.5 m, which matches the WMO
#: descriptions of the two classes.
_FREEBOARD_RATIO = 0.15
#: Mean of the exponential tail on waterline length, in m, above a 1 m floor.
_LENGTH_SCALE_M = 3.0
#: Extra target density per unit of ridging factor. Deformed ice sheds far more rubble.
_RIDGING_TARGET_GAIN = 0.8
#: Reference growler length used when reporting a single effective detection range, in m.
_REFERENCE_GROWLER_M = 3.0


class RadarContact(BaseModel):
    """
    One contact on the plan-position indicator.

    `is_true_target` is the field that makes this module worth having. It is False for a
    clutter-driven false alarm, and the interface should be able to show the operator that the
    picture contains both. A production build would not have this field, because nothing on a
    real bridge knows the ground truth; it exists here so the simulation can be audited.
    """

    contact_id: str
    bearing_deg: float = Field(ge=0.0, lt=360.0, description="True bearing from own ship")
    relative_bearing_deg: float = Field(ge=0.0, lt=360.0, description="Bearing relative to own head")
    range_nm: float = Field(ge=0.0, description="Slant range from own ship")

    size_class: str = Field(description="growler, bergy_bit or small_berg")
    estimated_length_m: float = Field(description="Estimated waterline length")
    estimated_freeboard_m: float = Field(description="Estimated height above the waterline")
    radar_cross_section_m2: float

    detection_confidence: float = Field(ge=0.0, le=1.0, description="Detector confidence, 0 to 1")
    signal_to_clutter_db: float

    tcpa_minutes: float = Field(description="Minutes to closest point of approach; 0 if opening")
    cpa_nm: float = Field(description="Predicted closest point of approach")
    threat_level: str = Field(description="LOW, MODERATE, HIGH or CRITICAL")

    is_true_target: bool = Field(description="False for a clutter-driven false alarm")

    latitude: float
    longitude: float


class RadarSweep(BaseModel):
    """
    One complete antenna revolution, with the honest accounting attached.

    `estimated_missed_targets` is the count of real ice targets inside the nominal range that
    the detection model did not paint. In this simulation it is known exactly, because the
    targets were generated here. On a real bridge it would be an estimate produced by the same
    detection model, and it should still be shown, because "we see four growlers" and "we see
    four growlers and probably missed three" are different pieces of advice.
    """

    contacts: List[RadarContact]
    sea_clutter_level: float = Field(ge=0.0, le=1.0, description="0 calm, 1 saturated clutter")
    detection_range_nm: float = Field(description="Range at which a 3 m growler is still 50 percent likely")
    sweep_time_hours: float = Field(description="Simulation time the sweep is valid for")

    own_position: Dict[str, float]
    own_heading_deg: float
    own_speed_knots: float

    false_alarm_count: int
    estimated_missed_targets: int
    missed_within_alert_range: int = Field(
        description="Undetected real targets inside the near-field perimeter. The dangerous ones."
    )
    true_target_count: int
    detected_true_count: int

    # Context the picture depends on, exposed so the interface can show why it looks like it does.
    ice_concentration: float
    ice_ridging_factor: float
    sig_wave_height_m: float
    wind_speed_ms: float
    max_range_nm: float = RADAR_MAX_RANGE_NM
    antenna_rpm: float = RADAR_ANTENNA_RPM
    band_ghz: float = RADAR_BAND_GHZ
    seed: int

    is_synthetic: bool = True
    source: str = (
        "synthetic; stands in for a shipboard X-band marine radar PPI and bridge thermal "
        "camera processed by an edge YOLO-class detector"
    )


# --------------------------------------------------------------------------------------
# Sensor physics
# --------------------------------------------------------------------------------------
def _size_class(length_m: float) -> str:
    """WMO/IIP size classes, using the thresholds already defined in constants."""
    if length_m < SIZE_CLASS_THRESHOLDS_M["growler"]:
        return "growler"
    if length_m < SIZE_CLASS_THRESHOLDS_M["bergy_bit"]:
        return "bergy_bit"
    return "small_berg"


def _radar_cross_section_m2(length_m: float) -> float:
    """
    Radar cross-section of a low-freeboard ice fragment at X-band.

    Ice is a poor reflector and a growler presents almost nothing above the waterline, so what
    the radar sees is roughly the projected vertical face, length times freeboard, scaled by a
    reflectivity factor. This puts a 3 m growler near 1.4 m2 and a 10 m bergy bit near 15 m2,
    which is the right order for what bridge crews report. It is a coarse model: real returns
    swing with aspect, wetting and whether the fragment is spinning.
    """
    freeboard = _FREEBOARD_RATIO * length_m
    return max(0.05, RADAR_REFERENCE_RCS_M2 * length_m * freeboard)


def sea_clutter_level(env: EnvSample) -> float:
    """
    Sea clutter as a number between 0 and 1, driven by significant wave height.

    Clutter at X-band is backscatter from the wave field itself, so it grows with sea state.
    Wave height carries most of the signal; wind adds a little because it roughens the small
    scale structure the radar actually sees, independently of the swell that is already there.
    """
    wave = min(1.0, max(0.0, env.sig_wave_height_m / RADAR_CLUTTER_WAVE_HEIGHT_M))
    wind = min(1.0, max(0.0, env.wind_speed_ms / 25.0))
    return float(min(1.0, 0.8 * wave + 0.2 * wind))


def _clutter_db(range_nm: float, clutter_level: float) -> float:
    """
    Clutter interference floor in dB at a given range.

    Clutter is a grazing-incidence return, so it is worst close to the ship and thins with
    range. That is exactly the wrong shape for growler detection: the interference peaks in the
    band where a small target has to be found in time to alter course.
    """
    denominator = 1.0 + (max(0.0, range_nm) / _CLUTTER_RANGE_SCALE_NM) ** 2
    return _CLUTTER_PEAK_DB * clutter_level / denominator


def _signal_to_clutter_db(rcs_m2: float, range_nm: float, clutter_level: float) -> float:
    """Detection margin in dB: radar equation less the clutter floor."""
    r = max(0.02, range_nm)
    return (
        _SNR_REFERENCE_DB
        + 10.0 * math.log10(max(1.0e-3, rcs_m2))
        - 40.0 * math.log10(r)
        - _clutter_db(r, clutter_level)
    )


def detection_probability(rcs_m2: float, range_nm: float, clutter_level: float) -> float:
    """
    Probability of painting a target on one sweep.

    A logistic on the detection margin. The softness constant stands in for everything the
    margin does not capture: aspect changes, sea spray on the radome, an operator's gain and
    rain-clutter settings, and the recall of the detector itself.
    """
    margin = _signal_to_clutter_db(rcs_m2, range_nm, clutter_level)
    return float(1.0 / (1.0 + math.exp(-(margin - RADAR_DETECTION_SNR_DB) / RADAR_SNR_SOFTNESS_DB)))


def effective_detection_range_nm(clutter_level: float) -> float:
    """
    Furthest range at which a reference 3 m growler is still an even bet.

    Reported rather than assumed, because it is the single number that tells a bridge officer
    how much warning the radar is actually giving. In a flat calm it is about three miles; in a
    five-metre sea it collapses to well under a mile, which is less than two minutes of warning
    at twelve knots.
    """
    rcs = _radar_cross_section_m2(_REFERENCE_GROWLER_M)
    ranges = np.linspace(0.05, RADAR_MAX_RANGE_NM, 240)
    best = 0.0
    for r in ranges:
        if detection_probability(rcs, float(r), clutter_level) >= 0.5:
            best = float(r)
    return round(best, 2)


# --------------------------------------------------------------------------------------
# Geometry
# --------------------------------------------------------------------------------------
def _cpa_tcpa(
    own_lat: float,
    own_lon: float,
    own_heading_deg: float,
    own_speed_knots: float,
    target_lat: float,
    target_lon: float,
    target_drift_east_kn: float,
    target_drift_north_kn: float,
) -> Tuple[float, float]:
    """
    Closest point of approach in nm and time to it in minutes.

    Worked in a local east-north frame anchored on own ship, with the target's position taken
    from the geodesic range and bearing so that the answer stays consistent with the coordinates
    the rest of the system uses. The target moves at the local ice drift, which is slow next to
    the ship but not negligible for a fragment already close to the track.

    A negative time to CPA means the range is already opening. In that case CPA is the present
    range and TCPA is reported as zero, because a warning about a hazard astern is noise.
    """
    rng_nm = haversine_nm(own_lat, own_lon, target_lat, target_lon)
    brg = math.radians(initial_bearing_deg(own_lat, own_lon, target_lat, target_lon))
    rx = rng_nm * math.sin(brg)          # east, nm
    ry = rng_nm * math.cos(brg)          # north, nm

    head = math.radians(own_heading_deg)
    own_east = own_speed_knots * math.sin(head)
    own_north = own_speed_knots * math.cos(head)

    wx = target_drift_east_kn - own_east   # relative velocity, knots = nm per hour
    wy = target_drift_north_kn - own_north
    w2 = wx * wx + wy * wy

    if w2 < 1.0e-9:
        return round(rng_nm, 3), 0.0

    tcpa_hours = -(rx * wx + ry * wy) / w2
    if tcpa_hours <= 0.0:
        return round(rng_nm, 3), 0.0

    cx = rx + wx * tcpa_hours
    cy = ry + wy * tcpa_hours
    return round(math.hypot(cx, cy), 3), round(tcpa_hours * 60.0, 2)


def _threat_level(cpa_nm: float, tcpa_minutes: float, size_class: str, confidence: float) -> str:
    """
    Threat banding, weighted toward how much time the bridge has rather than raw distance.

    A growler two miles off with twenty minutes to run is a plot to watch. The same growler
    with three minutes to run is a helm order. Size raises the band because a bergy bit will
    do structural damage where a growler damages a propeller, and low confidence lowers it,
    because acting on a probable clutter spike costs distance and fuel too.
    """
    if tcpa_minutes <= 0.0 and cpa_nm > GROWLER_ALERT_RANGE_NM:
        return "LOW"

    closing = tcpa_minutes > 0.0
    big = size_class in ("bergy_bit", "small_berg")

    if closing and cpa_nm <= 0.25 and tcpa_minutes <= 8.0:
        level = "CRITICAL"
    elif closing and cpa_nm <= 0.5 and tcpa_minutes <= 15.0:
        level = "HIGH" if not big else "CRITICAL"
    elif closing and cpa_nm <= 1.0 and tcpa_minutes <= 30.0:
        level = "MODERATE" if not big else "HIGH"
    elif cpa_nm <= GROWLER_ALERT_RANGE_NM:
        level = "LOW" if not big else "MODERATE"
    else:
        level = "LOW"

    if confidence < 0.4 and level in ("CRITICAL", "HIGH"):
        order = ["LOW", "MODERATE", "HIGH", "CRITICAL"]
        level = order[max(0, order.index(level) - 1)]
    return level


# --------------------------------------------------------------------------------------
# Sweep
# --------------------------------------------------------------------------------------
def _sweep_seed(
    lat: float, lon: float, heading_deg: float, speed_knots: float, t_hours: float, base_seed: int
) -> int:
    """
    Derive a reproducible 32-bit seed from the sweep arguments.

    Quantised before hashing so that floating-point noise in the caller cannot change the
    picture, and hashed rather than added so that neighbouring positions get uncorrelated
    target fields instead of a slowly sliding one.
    """
    key = (
        round(float(lat), 3),
        round(float(lon), 3),
        round(float(heading_deg), 1),
        round(float(speed_knots), 2),
        round(float(t_hours), 3),
    )
    digest = zlib.crc32(repr(key).encode("utf-8"))
    return int((int(base_seed) + digest) % (2 ** 32))


def expected_target_density_per_nm2(ice: IceState) -> float:
    """
    Expected number of detectable ice fragments per square nautical mile.

    Derived from the ice state rather than invented: fragments come from the ice field, so the
    density scales with concentration, and superlinearly, because a nearly closed field is also
    a field that has been grinding against itself. Ridging adds more, since deformed ice sheds
    rubble that level ice does not.

    Zero concentration gives zero ice targets. That is deliberate. Real open water near a
    calving front carries growlers with no sea ice around them at all, and a production system
    would add a berg-debris term driven by the iceberg catalogue; this module does not invent
    one, because the point of the honest-labelling rule is that every target has a stated
    provenance.
    """
    conc = min(1.0, max(0.0, ice.concentration))
    ridging = max(0.0, ice.ridging_factor)
    return RADAR_TARGET_DENSITY_PER_NM2 * (conc ** 1.5) * (1.0 + _RIDGING_TARGET_GAIN * ridging)


def simulate_sweep(
    lat: float,
    lon: float,
    heading_deg: float,
    speed_knots: float,
    t_hours: float = 0.0,
    sea_ice_model: Optional[SeaIceModel] = None,
    environment: Optional[EnvironmentModel] = None,
    seed: Optional[int] = None,
    ice_state: Optional[IceState] = None,
    env_sample: Optional[EnvSample] = None,
) -> RadarSweep:
    """
    One X-band PPI sweep out to the range-ring limit, with misses and false alarms.

    Deterministic in its arguments: the same call always returns the same sweep, so a voyage
    replay and a live demo agree.

    Sampling the ice and environment fields costs about a hundred milliseconds, which dominates
    the sweep. A caller that has already sampled them for the same position and time, as the
    voyage engine does on every tick, should hand them in through `ice_state` and `env_sample`
    rather than pay for them twice. The result is identical either way.
    """
    ice_model = sea_ice_model or get_sea_ice_model()
    env_model = environment or get_environment()

    heading_deg = float(heading_deg) % 360.0
    speed_knots = max(0.0, float(speed_knots))

    ice = ice_state if ice_state is not None else ice_model.state(lat, lon, t_hours)
    env = (
        env_sample
        if env_sample is not None
        else env_model.sample(lat, lon, t_hours, ice_concentration=ice.concentration)
    )

    clutter = sea_clutter_level(env)
    det_range = effective_detection_range_nm(clutter)

    base_seed = RADAR_SEED if seed is None else int(seed)
    sweep_seed = _sweep_seed(lat, lon, heading_deg, speed_knots, t_hours, base_seed)
    rng = np.random.default_rng(sweep_seed)

    # Ice fragments drift with the pack, which is what makes a contact abeam still worth
    # watching: it is not stationary relative to the track.
    drift_east_kn = ice.drift_u_ms / MS_PER_KNOT
    drift_north_kn = ice.drift_v_ms / MS_PER_KNOT

    swept_area_nm2 = math.pi * RADAR_MAX_RANGE_NM ** 2
    lam = expected_target_density_per_nm2(ice) * swept_area_nm2
    n_true = int(rng.poisson(lam))

    contacts: List[RadarContact] = []
    missed = 0
    missed_near = 0
    detected_true = 0

    for i in range(n_true):
        # Uniform over the disc: sqrt of a uniform gives equal area per unit probability, so
        # targets are not artificially crowded near the ship.
        rng_nm = RADAR_MAX_RANGE_NM * math.sqrt(float(rng.random()))
        bearing = float(rng.random()) * 360.0
        length_m = float(min(60.0, 1.0 + rng.exponential(_LENGTH_SCALE_M)))
        rcs = _radar_cross_section_m2(length_m)

        p_detect = detection_probability(rcs, rng_nm, clutter)
        if float(rng.random()) >= p_detect:
            # A real growler the radar did not paint. This is the hazard the module exists to
            # be honest about, so it is counted rather than quietly dropped.
            missed += 1
            if rng_nm <= GROWLER_ALERT_RANGE_NM:
                missed_near += 1
            continue

        detected_true += 1
        t_lat, t_lon = destination_point(lat, lon, bearing, rng_nm)
        cpa, tcpa = _cpa_tcpa(
            lat, lon, heading_deg, speed_knots, t_lat, t_lon, drift_east_kn, drift_north_kn
        )
        # Detector confidence tracks detection probability but is not identical to it: a
        # convolutional detector is noisily calibrated, and this is what the bridge would see.
        confidence = float(np.clip(p_detect + rng.normal(0.0, 0.06), 0.05, 0.99))
        size = _size_class(length_m)

        contacts.append(
            RadarContact(
                contact_id=f"T{i:03d}",
                bearing_deg=round(bearing, 1),
                relative_bearing_deg=round((bearing - heading_deg) % 360.0, 1),
                range_nm=round(rng_nm, 3),
                size_class=size,
                estimated_length_m=round(length_m, 1),
                estimated_freeboard_m=round(_FREEBOARD_RATIO * length_m, 2),
                radar_cross_section_m2=round(rcs, 2),
                detection_confidence=round(confidence, 3),
                signal_to_clutter_db=round(_signal_to_clutter_db(rcs, rng_nm, clutter), 1),
                tcpa_minutes=tcpa,
                cpa_nm=cpa,
                threat_level=_threat_level(cpa, tcpa, size, confidence),
                is_true_target=True,
                latitude=round(t_lat, 5),
                longitude=round(t_lon, 5),
            )
        )

    # False alarms. Clutter spikes survive the detector's threshold and paint as contacts. They
    # cluster close in, where clutter is strongest, which is also where they are most likely to
    # provoke an unnecessary helm order.
    fa_area = math.pi * _FALSE_ALARM_RADIUS_NM ** 2
    fa_lambda = RADAR_FALSE_ALARM_DENSITY_PER_NM2 * fa_area * (clutter ** 2)
    n_false = int(rng.poisson(fa_lambda))

    for j in range(n_false):
        rng_nm = _FALSE_ALARM_RADIUS_NM * math.sqrt(float(rng.random()))
        bearing = float(rng.random()) * 360.0
        # A clutter spike has no object behind it, so its apparent size is whatever the
        # detector's bounding box happened to be. Small, and reported with low confidence.
        length_m = float(np.clip(rng.normal(3.0, 1.2), 0.8, 8.0))
        rcs = _radar_cross_section_m2(length_m)
        t_lat, t_lon = destination_point(lat, lon, bearing, rng_nm)
        cpa, tcpa = _cpa_tcpa(
            lat, lon, heading_deg, speed_knots, t_lat, t_lon, drift_east_kn, drift_north_kn
        )
        confidence = float(np.clip(rng.uniform(0.15, 0.55), 0.0, 1.0))
        size = _size_class(length_m)

        contacts.append(
            RadarContact(
                contact_id=f"F{j:03d}",
                bearing_deg=round(bearing, 1),
                relative_bearing_deg=round((bearing - heading_deg) % 360.0, 1),
                range_nm=round(rng_nm, 3),
                size_class=size,
                estimated_length_m=round(length_m, 1),
                estimated_freeboard_m=round(_FREEBOARD_RATIO * length_m, 2),
                radar_cross_section_m2=round(rcs, 2),
                detection_confidence=round(confidence, 3),
                signal_to_clutter_db=round(_signal_to_clutter_db(rcs, rng_nm, clutter), 1),
                tcpa_minutes=tcpa,
                cpa_nm=cpa,
                threat_level=_threat_level(cpa, tcpa, size, confidence),
                is_true_target=False,
                latitude=round(t_lat, 5),
                longitude=round(t_lon, 5),
            )
        )

    contacts.sort(key=lambda c: c.range_nm)

    return RadarSweep(
        contacts=contacts,
        sea_clutter_level=round(clutter, 3),
        detection_range_nm=det_range,
        sweep_time_hours=round(float(t_hours), 3),
        own_position={"lat": round(float(lat), 5), "lon": round(float(lon), 5)},
        own_heading_deg=round(heading_deg, 1),
        own_speed_knots=round(speed_knots, 2),
        false_alarm_count=n_false,
        estimated_missed_targets=missed,
        missed_within_alert_range=missed_near,
        true_target_count=n_true,
        detected_true_count=detected_true,
        ice_concentration=round(ice.concentration, 3),
        ice_ridging_factor=round(ice.ridging_factor, 3),
        sig_wave_height_m=round(env.sig_wave_height_m, 2),
        wind_speed_ms=round(env.wind_speed_ms, 2),
        seed=sweep_seed,
    )


def highest_threat(sweep: RadarSweep) -> Optional[RadarContact]:
    """
    The contact the bridge should act on first, or None if the picture is clear.

    Ordered by threat band, then by time to CPA, because among equally-banded contacts the one
    that runs out of time first is the one that decides the helm order.
    """
    order = {"CRITICAL": 3, "HIGH": 2, "MODERATE": 1, "LOW": 0}
    active = [c for c in sweep.contacts if order[c.threat_level] > 0]
    if not active:
        return None
    return sorted(
        active,
        key=lambda c: (-order[c.threat_level], c.tcpa_minutes if c.tcpa_minutes > 0 else 1.0e9),
    )[0]
