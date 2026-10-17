"""
ICEFLOW: physical constants, unit conversions and provenance metadata.

Every magic number used anywhere in the physics core lives here with a citation,
so a reviewer can audit the model without reading the algorithms.
"""
from __future__ import annotations

# --------------------------------------------------------------------------------------
# Version / provenance
# --------------------------------------------------------------------------------------
SYSTEM_NAME = "ICEFLOW"
SYSTEM_VERSION = "1.0.0"
PROBLEM_STATEMENT_ID = "26059"
ORGANIZATION = "Ministry of Earth Sciences (MoES)"
DEPARTMENT = "National Centre for Polar and Ocean Research (NCPOR)"

MODEL_VERSIONS = {
    "polaris_risk": "1.0.0 (IMO MSC.1/Circ.1519)",
    "lindqvist_model": "1.0.0 (Lindqvist 1989, POAC)",
    "iceberg_tracker": "1.0.0 (RK4 Lagrangian, Bigg et al. 1997 / Rackow et al. 2017)",
    "sea_ice": "1.0.0 (synthetic analysis + semi-Lagrangian forecast)",
    "environment": "1.0.0 (synthetic Southern Ocean forcing)",
    "route_optimizer": "1.0.0 (risk-constrained A*)",
    "growler_radar": "1.0.0 (X-band PPI simulation)",
}

# Honest provenance: what is real, and what stands in for a live feed.
DATA_PROVENANCE = {
    "coastline": {
        "status": "real",
        "source": "Natural Earth 1:50m physical land (public domain)",
        "note": "97 polygons, 1698 vertices, used as the hard land mask.",
    },
    "stations": {
        "status": "real",
        "source": "NCPOR published station coordinates",
        "note": "Maitri and Bharati positions are the published values.",
    },
    "iceberg_catalogue": {
        "status": "real-seed",
        "source": "US National Ice Center Antarctic iceberg tracking database",
        "note": "Real berg names and calving origins; positions are seeded then propagated by the drift model.",
    },
    "polaris_matrix": {
        "status": "real",
        "source": "IMO MSC.1/Circ.1519 Risk Value tables",
        "note": "Transcribed risk values; not simulated.",
    },
    "sea_ice_field": {
        "status": "synthetic",
        "source": "stands in for OSI-SAF OSI-401-b / AMSR2 / Sentinel-1 SAR",
        "note": "Physically-shaped seeded field. The models consuming it are real; the field is simulated.",
    },
    "atmosphere_ocean": {
        "status": "synthetic",
        "source": "stands in for ECMWF ERA5/HRES and CMEMS GLOBAL_ANALYSISFORECAST_PHY_001_024",
        "note": "Seeded synoptic + climatological forcing. Simulated.",
    },
}

# --------------------------------------------------------------------------------------
# Earth / geodesy
# --------------------------------------------------------------------------------------
EARTH_RADIUS_KM = 6371.0088          # IUGG mean radius
WGS84_A = 6378137.0                  # semi-major axis, m
WGS84_F = 1.0 / 298.257223563
WGS84_E = 0.08181919084262149        # first eccentricity
EPSG3031_STD_PARALLEL_DEG = -71.0    # Antarctic Polar Stereographic true-scale latitude
EPSG3031_CENTRAL_MERIDIAN_DEG = 0.0

OMEGA_EARTH = 7.2921159e-5           # rad/s, Earth rotation rate

# --------------------------------------------------------------------------------------
# Unit conversions
# --------------------------------------------------------------------------------------
KM_PER_NM = 1.852
M_PER_NM = 1852.0
NM_PER_KM = 1.0 / 1.852
MS_PER_KNOT = 0.514444
KNOTS_PER_MS = 1.0 / 0.514444
SECONDS_PER_HOUR = 3600.0

# --------------------------------------------------------------------------------------
# Fluid / material properties
# --------------------------------------------------------------------------------------
RHO_SEAWATER = 1027.0                # kg/m3, Southern Ocean surface
RHO_AIR = 1.35                       # kg/m3, cold polar air near 253 K
RHO_SEA_ICE = 920.0                  # kg/m3
RHO_GLACIAL_ICE = 850.0              # kg/m3, iceberg (firn-bearing)
GRAVITY = 9.81                       # m/s2

# Ice mechanics (Timco & Weeks 2010 ranges)
ICE_FLEXURAL_STRENGTH_KPA = 500.0    # sigma_f, first-year sea ice
ICE_ELASTIC_MODULUS_MPA = 2000.0     # E, effective
ICE_CRUSHING_STRENGTH_KPA = 1800.0

# Thermodynamics
LATENT_HEAT_FUSION_ICE = 3.34e5      # J/kg
ICE_THERMAL_CONDUCTIVITY = 2.03      # W/m/K
STEFAN_GROWTH_COEFF = 0.0334         # m / sqrt(freezing degree-day), empirical Anderson (1961)
SEAWATER_FREEZING_POINT_C = -1.86    # at 34 psu

# --------------------------------------------------------------------------------------
# Iceberg drift coefficients (Bigg et al. 1997; Rackow et al. 2017)
# --------------------------------------------------------------------------------------
ICEBERG_AIR_DRAG_COEFF = 1.3         # Ca, form drag on the sail
ICEBERG_WATER_DRAG_COEFF = 0.9       # Cw, form drag on the keel
ICEBERG_ADDED_MASS_COEFF = 0.5       # Ma = 0.5 M
ICEBERG_WAVE_RADIATION_COEFF = 0.06

# Deterioration (Bigg et al. 1997 / El-Tahan et al. 1987), m/day per unit forcing
MELT_BASAL_TURBULENT_COEFF = 0.58
MELT_BUOYANT_CONVECTION_COEFF = 7.62e-3
MELT_WAVE_EROSION_COEFF = 0.000146

# Size classification thresholds (WMO / IIP), waterline length in metres
SIZE_CLASS_THRESHOLDS_M = {
    "growler": 5.0,
    "bergy_bit": 15.0,
    "small": 60.0,
    "medium": 120.0,
    "large": 200.0,
    "very_large": 400.0,
}

# --------------------------------------------------------------------------------------
# Propulsion and fuel
# --------------------------------------------------------------------------------------
MGO_CO2_FACTOR = 3.206               # kg CO2 per kg marine gas oil (IMO MEPC.308(73))
MGO_SOX_FACTOR = 0.002               # kg SOx per kg MGO at 0.1% sulphur
MGO_DENSITY_KG_PER_L = 0.86
MGO_PRICE_USD_PER_TONNE = 780.0      # indicative bunker price for ROI arithmetic
USD_TO_INR = 87.5

# --------------------------------------------------------------------------------------
# Operational thresholds
# --------------------------------------------------------------------------------------
RIO_NORMAL_THRESHOLD = 0             # RIO >= 0: normal operation
RIO_PROHIBITED_THRESHOLD = -10       # RIO < -10: operation prohibited
MIN_COAST_CLEARANCE_NM = 8.0         # keep-off distance from charted land
ICEBERG_EXCLUSION_RADIUS_NM = 12.0   # hard avoidance around a tracked tabular berg
GROWLER_ALERT_RANGE_NM = 3.0         # near-field tactical perimeter
COMPRESSION_BESETTING_THRESHOLD = 0.6  # compression index above which besetting risk is flagged

# Deterministic seeds so a demo never changes underfoot
GLOBAL_SEED = 26059
ENV_SEED = GLOBAL_SEED + 1
ICE_SEED = GLOBAL_SEED + 2
RADAR_SEED = GLOBAL_SEED + 3
ENSEMBLE_SEED = GLOBAL_SEED + 4

# --------------------------------------------------------------------------------------
# Lindqvist (1989) ice resistance
#
# Coefficients transcribed from the published form of the method (Lindqvist, POAC'89, as
# reproduced by Fan et al., Advances in Polar Science 30(4), 2019, eqs. 1-4). They are kept
# here rather than inline so a reviewer can check them against the paper in one place.
# --------------------------------------------------------------------------------------
LINDQVIST_BENDING_COEFF = 37.0 / 64.0    # leading constant on the bending term
LINDQVIST_SPEED_COEFF_BREAKING = 1.4     # (1 + 1.4 v / sqrt(g h)) on crushing + bending
LINDQVIST_SPEED_COEFF_SUBMERGENCE = 9.4  # (1 + 9.4 v / sqrt(g L)) on submergence
ICE_POISSON_RATIO = 0.30                 # nu, sea ice (Timco & Weeks 2010)

# Lindqvist is a *level ice* method, valid at 10/10 concentration. In a broken field the
# ship spends part of its time in leads, so the resistance is scaled by concentration
# raised to this exponent. Values between 1.5 and 2.0 are used in the literature for
# floe fields; 1.8 is the mid-range value the v0.1 model already used.
ICE_CONCENTRATION_EXPONENT = 1.8

# --------------------------------------------------------------------------------------
# Open-water resistance (ITTC-1957 friction line plus a residuary term)
# --------------------------------------------------------------------------------------
SEAWATER_KINEMATIC_VISCOSITY = 1.83e-6   # m2/s at 0 C, 35 psu (ITTC 1978 property tables)
ITTC57_NUMERATOR = 0.075                 # Cf = 0.075 / (log10(Re) - 2)^2
HULL_FORM_FACTOR = 1.30                  # (1 + k); blunt icebreaking bows sit high, 0.25-0.35
DENNY_MUMFORD_COEFF = 1.7                # S = 1.7 L T + Cb L B, the Denny-Mumford estimate
DEFAULT_BLOCK_COEFFICIENT = 0.65         # typical ice-strengthened cargo / resupply hull
RESIDUARY_CR_AT_FN_REF = 2.5e-3          # residuary coefficient at the reference Froude number
RESIDUARY_FN_REF = 0.20                  # reference Froude number for the residuary fit
RESIDUARY_FN_EXPONENT = 4.0              # thin-ship theory gives Rw ~ Fn^4 well below the hump

# --------------------------------------------------------------------------------------
# Propulsion: bollard pull and propeller-ice interaction
#
# T = Ke * (P_D * D)^(2/3) is the net-thrust relation of the Finnish-Swedish Ice Class
# Rules; the speed decay (1 - v/3v_ow - 2(v/v_ow)^2/3) is the same rules' thrust curve.
# --------------------------------------------------------------------------------------
BOLLARD_PULL_COEFF_OPEN_PROP = 0.78      # Ke, open propeller
BOLLARD_PULL_COEFF_NOZZLE = 0.98         # Ke, propeller in a nozzle
SHAFT_TRANSMISSION_EFFICIENCY = 0.97     # brake power to delivered power
ICE_PROPULSION_EFFICIENCY_LOSS = 0.25    # maximum fractional loss of QPC from propeller-ice work
MIN_PROPULSIVE_EFFICIENCY = 0.30         # floor, so the power balance can never blow up
MAX_SHIP_SPEED_KNOTS = 18.0              # search ceiling for the attainable-speed bisection

# --------------------------------------------------------------------------------------
# X-band growler radar simulation
# --------------------------------------------------------------------------------------
RADAR_MAX_RANGE_NM = 6.0                 # PPI range-ring limit modelled by the near-field layer
RADAR_BAND_GHZ = 9.41                    # X-band marine radar centre frequency
RADAR_ANTENNA_RPM = 24.0                 # 2.5 s per sweep, typical open-array magnetron set
RADAR_TARGET_DENSITY_PER_NM2 = 0.25      # small ice targets per square nm at 10/10 concentration
RADAR_FALSE_ALARM_DENSITY_PER_NM2 = 0.08 # clutter-driven false contacts per square nm at full clutter
RADAR_DETECTION_SNR_DB = 12.0            # signal-to-clutter-plus-noise needed for a 50 percent hit
RADAR_SNR_SOFTNESS_DB = 3.0              # logistic width of the detection curve
RADAR_REFERENCE_RCS_M2 = 1.0             # RCS of a 1 m waterline-length growler at zero freeboard
RADAR_CLUTTER_WAVE_HEIGHT_M = 5.0        # Hs at which sea clutter saturates the near-field picture

# Below this speed a ship has no steerage way: the rudder stops biting, the propeller is
# effectively at bollard, and the resistance model's own precision no longer supports the
# answer. Treated as beset rather than reported as a fraction of a knot.
MIN_STEERAGE_SPEED_KNOTS = 0.25
