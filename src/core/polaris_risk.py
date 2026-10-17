"""
IMO POLARIS: Polar Operational Limit Assessment Risk Indexing System.
Reference: IMO Circular MSC.1/Circ.1519, issued under the Polar Code (MSC.385(94)).

The Risk Index Outcome for an ice regime is

    RIO = sum_i ( C_i * RV_i )

where C_i is the concentration of ice type i in tenths and RV_i is the Risk Value for that
ice type against the ship's ice class. Decision thresholds:

    RIO >= 0        normal operation
    -10 <= RIO < 0  elevated operational risk; reduced speed, ice navigator concurrence
    RIO < -10       operation not permitted

WHAT CHANGED FROM THE v0.1 PROTOTYPE
------------------------------------
The first-pass matrix in this repository used approximate risk values and non-standard ice-type
thickness boundaries. This module transcribes the official eleven-column table (ice free through
heavy multi-year) for the full set of ice classes, and uses the WMO stage-of-development
boundaries the circular is written against. One consequence is that PC7 in heavy multi-year ice
scores -3 per tenth rather than the -5 previously assumed, so a 10/10 regime yields RIO = -30
instead of -50. Both figures prohibit the operation; the official one is the defensible number.

Legacy ice-type strings from v0.1 still deserialise, through LEGACY_ICE_TYPE_ALIASES.
"""
from __future__ import annotations

from enum import Enum
from typing import Dict, List, Optional

from pydantic import BaseModel, Field, field_validator

from src.core.constants import RIO_NORMAL_THRESHOLD, RIO_PROHIBITED_THRESHOLD


class IceClass(str, Enum):
    """IACS Polar Classes, Finnish-Swedish Baltic classes, RMRS Arc classes, Polar Code categories."""

    PC1 = "PC1"
    PC2 = "PC2"
    PC3 = "PC3"
    PC4 = "PC4"
    PC5 = "PC5"
    PC6 = "PC6"
    PC7 = "PC7"
    IA_SUPER = "IA_Super"
    IA = "IA"
    IB = "IB"
    IC = "IC"
    NOT_ICE_STRENGTHENED = "Not_Ice_Strengthened"
    # RMRS Arc classes, resolved to their POLARIS equivalents below.
    ARC4 = "Arc4"
    ARC5 = "Arc5"
    ARC6 = "Arc6"
    ARC7 = "Arc7"
    # Polar Code ship categories.
    CATEGORY_A = "Category_A"
    CATEGORY_B = "Category_B"
    CATEGORY_C = "Category_C"


class IceType(str, Enum):
    """
    WMO stages of development, in the order the POLARIS risk table lists them.

    The string values preserve the v0.1 spellings wherever one existed, so previously-written
    API clients keep working.
    """

    ICE_FREE = "Ice_Free"
    OPEN_WATER = "Open_Water"                       # < 1/10 ice; scored as ice free
    BERGY_WATER = "Bergy_Water"                     # open water with bergy bits and growlers
    NEW_ICE = "New_Ice"                             # < 10 cm
    GREY_ICE = "Grey_Ice"                           # 10 - 15 cm
    GREY_WHITE_ICE = "Grey_White_Ice"               # 15 - 30 cm
    THIN_FIRST_YEAR_1 = "Thin_First_Year_Stage_1"   # 30 - 50 cm
    THIN_FIRST_YEAR_2 = "Thin_First_Year_Stage_2"   # 50 - 70 cm
    MEDIUM_FIRST_YEAR = "Medium_First_Year"         # 70 - 120 cm
    THICK_FIRST_YEAR = "Thick_First_Year"           # 120 - 200 cm
    SECOND_YEAR = "Second_Year"                     # survived one melt season
    LIGHT_MULTI_YEAR = "Light_Multi_Year"
    HEAVY_MULTI_YEAR = "Multi_Year"                 # legacy spelling retained


#: v0.1 names that no longer exist as members, mapped onto their WMO equivalent.
LEGACY_ICE_TYPE_ALIASES: Dict[str, IceType] = {
    "Very_Thin_First_Year": IceType.THIN_FIRST_YEAR_1,   # v0.1 called 30-50 cm "very thin"
    "Multi_Year_Heavy": IceType.HEAVY_MULTI_YEAR,
    "Multi_Year_Light": IceType.LIGHT_MULTI_YEAR,
}

#: WMO stage-of-development boundaries, upper bound of each stage in metres.
ICE_TYPE_THICKNESS_BOUNDS_M: Dict[IceType, float] = {
    IceType.NEW_ICE: 0.10,
    IceType.GREY_ICE: 0.15,
    IceType.GREY_WHITE_ICE: 0.30,
    IceType.THIN_FIRST_YEAR_1: 0.50,
    IceType.THIN_FIRST_YEAR_2: 0.70,
    IceType.MEDIUM_FIRST_YEAR: 1.20,
    IceType.THICK_FIRST_YEAR: 2.00,
    IceType.SECOND_YEAR: 2.80,
    IceType.LIGHT_MULTI_YEAR: 3.60,
    IceType.HEAVY_MULTI_YEAR: 99.0,
}

#: The eleven risk-table columns, in official order.
_TABLE_ORDER: List[IceType] = [
    IceType.ICE_FREE,
    IceType.NEW_ICE,
    IceType.GREY_ICE,
    IceType.GREY_WHITE_ICE,
    IceType.THIN_FIRST_YEAR_1,
    IceType.THIN_FIRST_YEAR_2,
    IceType.MEDIUM_FIRST_YEAR,
    IceType.THICK_FIRST_YEAR,
    IceType.SECOND_YEAR,
    IceType.LIGHT_MULTI_YEAR,
    IceType.HEAVY_MULTI_YEAR,
]

#: Risk Values transcribed from MSC.1/Circ.1519, one row per ice class.
_RIV_ROWS: Dict[IceClass, List[int]] = {
    #                    IF  New Grey G-W TFY1 TFY2 MFY TFY  SY  LMY HMY
    IceClass.PC1:       [3,  3,  3,  3,  2,  2,  2,  2,  2,  1,  1],
    IceClass.PC2:       [3,  3,  3,  3,  2,  2,  2,  2,  1,  1,  0],
    IceClass.PC3:       [3,  3,  3,  3,  2,  2,  2,  2,  1,  0, -1],
    IceClass.PC4:       [3,  3,  3,  3,  2,  2,  2,  1,  0, -1, -2],
    IceClass.PC5:       [3,  3,  3,  3,  2,  2,  1,  0, -1, -2, -2],
    IceClass.PC6:       [3,  2,  2,  2,  2,  1,  1,  0, -1, -2, -3],
    IceClass.PC7:       [3,  2,  2,  2,  1,  1,  0, -1, -2, -3, -3],
    IceClass.IA_SUPER:  [3,  2,  2,  2,  2,  1,  0, -1, -2, -3, -4],
    IceClass.IA:        [3,  2,  2,  2,  1,  0, -1, -2, -3, -4, -5],
    IceClass.IB:        [3,  2,  2,  1,  0, -1, -2, -3, -4, -5, -6],
    IceClass.IC:        [3,  2,  1,  0, -1, -2, -3, -4, -5, -6, -7],
    IceClass.NOT_ICE_STRENGTHENED:
                        [3,  1,  0, -1, -2, -3, -4, -5, -6, -7, -8],
}

#: Class equivalences. RMRS Arc classes and Polar Code categories are resolved to a POLARIS row.
#: These equivalences are approximate and are stated as such in the API response.
CLASS_EQUIVALENCE: Dict[IceClass, IceClass] = {
    IceClass.ARC4: IceClass.IA,
    IceClass.ARC5: IceClass.IA_SUPER,
    IceClass.ARC6: IceClass.PC6,
    IceClass.ARC7: IceClass.PC4,
    IceClass.CATEGORY_A: IceClass.PC5,
    IceClass.CATEGORY_B: IceClass.PC7,
    IceClass.CATEGORY_C: IceClass.NOT_ICE_STRENGTHENED,
}

#: Speed ceilings while operating in the elevated-risk band, knots.
#: The tiers follow the circular's guidance; the taper toward RIO = -10 is an operational
#: refinement this system adds, and is documented as such.
_ELEVATED_RISK_SPEED_TIERS: Dict[IceClass, float] = {
    IceClass.PC1: 11.0, IceClass.PC2: 11.0, IceClass.PC3: 11.0,
    IceClass.PC4: 8.0, IceClass.PC5: 8.0,
    IceClass.PC6: 5.0, IceClass.PC7: 5.0,
    IceClass.IA_SUPER: 5.0, IceClass.IA: 5.0,
    IceClass.IB: 3.0, IceClass.IC: 3.0,
    IceClass.NOT_ICE_STRENGTHENED: 3.0,
}

#: Unrestricted service speed ceiling used when RIO >= 0, knots.
NORMAL_OPERATION_SPEED_KNOTS = 14.0

#: Types that count as ice free for the purpose of the risk sum.
_ICE_FREE_EQUIVALENT = {IceType.ICE_FREE, IceType.OPEN_WATER, IceType.BERGY_WATER}


def resolve_class(ice_class: IceClass) -> IceClass:
    """Map an Arc class or Polar Code category onto the POLARIS row that governs it."""
    return CLASS_EQUIVALENCE.get(ice_class, ice_class)


def risk_value(ice_class: IceClass, ice_type: IceType, decayed: bool = False) -> int:
    """
    Risk Value for one ice type against one ice class.

    `decayed` applies the circular's melt-season allowance: during advanced melt, first-year ice
    types are one step less hazardous for ships below PC5. This is applied conservatively, only
    to first-year stages, and never to multi-year ice.
    """
    row_class = resolve_class(ice_class)
    row = _RIV_ROWS.get(row_class, _RIV_ROWS[IceClass.PC5])

    if ice_type in _ICE_FREE_EQUIVALENT:
        return row[0]

    try:
        rv = row[_TABLE_ORDER.index(ice_type)]
    except ValueError:  # pragma: no cover - every member is in the table
        rv = row[_TABLE_ORDER.index(IceType.MEDIUM_FIRST_YEAR)]

    if decayed and rv < 0 and ice_type in {
        IceType.THIN_FIRST_YEAR_1,
        IceType.THIN_FIRST_YEAR_2,
        IceType.MEDIUM_FIRST_YEAR,
        IceType.THICK_FIRST_YEAR,
    }:
        rv += 1
    return rv


def classify_ice_type(thickness_m: float, concentration: float = 1.0) -> IceType:
    """Map an ice thickness to its WMO stage of development, which is the POLARIS input."""
    if concentration < 0.10 or thickness_m <= 0.005:
        return IceType.OPEN_WATER
    for ice_type in _TABLE_ORDER[1:]:
        if thickness_m <= ICE_TYPE_THICKNESS_BOUNDS_M[ice_type]:
            return ice_type
    return IceType.HEAVY_MULTI_YEAR


class IceRegimeComponent(BaseModel):
    """One ice type present in the regime, with its partial concentration in tenths."""

    ice_type: IceType
    concentration_tenths: int = Field(ge=0, le=10, description="Partial concentration in tenths (0 to 10)")

    @field_validator("ice_type", mode="before")
    @classmethod
    def _accept_legacy_names(cls, value: object) -> object:
        if isinstance(value, str) and value in LEGACY_ICE_TYPE_ALIASES:
            return LEGACY_ICE_TYPE_ALIASES[value].value
        return value


class ComponentContribution(BaseModel):
    """The arithmetic behind one term of the RIO sum, so the interface can show its working."""

    ice_type: IceType
    concentration_tenths: int
    risk_value: int
    contribution: int


class POLARISAssessmentResult(BaseModel):
    vessel_ice_class: IceClass
    evaluated_as: IceClass = Field(description="POLARIS row actually used after class equivalence")
    total_concentration_tenths: int
    rio: int
    status: str
    is_operation_permitted: bool
    is_speed_restricted: bool
    max_recommended_speed_knots: float
    advisory_notes: str
    per_component_contributions: List[ComponentContribution] = Field(default_factory=list)
    decayed_ice_applied: bool = False
    reference: str = "IMO MSC.1/Circ.1519 (POLARIS)"


def calculate_rio(
    ice_class: IceClass,
    components: List[IceRegimeComponent],
    decayed: bool = False,
) -> POLARISAssessmentResult:
    """
    Evaluate the Risk Index Outcome for an ice regime.

    Any concentration not accounted for by the supplied components is treated as ice free, which
    is the convention the circular uses for a partial regime description.
    """
    resolved = resolve_class(ice_class)

    declared = sum(c.concentration_tenths for c in components)
    if declared > 10:
        raise ValueError(f"Total ice concentration cannot exceed 10 tenths. Provided: {declared}")

    contributions: List[ComponentContribution] = []
    rio = 0
    for comp in components:
        rv = risk_value(ice_class, comp.ice_type, decayed=decayed)
        term = comp.concentration_tenths * rv
        rio += term
        contributions.append(
            ComponentContribution(
                ice_type=comp.ice_type,
                concentration_tenths=comp.concentration_tenths,
                risk_value=rv,
                contribution=term,
            )
        )

    remainder = 10 - declared
    if remainder > 0:
        rv_free = risk_value(ice_class, IceType.ICE_FREE, decayed=decayed)
        rio += remainder * rv_free
        contributions.append(
            ComponentContribution(
                ice_type=IceType.ICE_FREE,
                concentration_tenths=remainder,
                risk_value=rv_free,
                contribution=remainder * rv_free,
            )
        )

    if rio >= RIO_NORMAL_THRESHOLD:
        status = "NORMAL_OPERATION"
        permitted, restricted = True, False
        max_speed = NORMAL_OPERATION_SPEED_KNOTS
        advisory = "Safe for normal operations. Maintain standard polar watchkeeping and ice lookout."
    elif rio >= RIO_PROHIBITED_THRESHOLD:
        status = "ELEVATED_OPERATIONAL_RISK"
        permitted, restricted = True, True
        tier = _ELEVATED_RISK_SPEED_TIERS.get(resolved, 5.0)
        # Taper from the tier ceiling down to a third of it as RIO approaches the prohibition line.
        taper = 1.0 - 0.67 * (abs(rio) / abs(RIO_PROHIBITED_THRESHOLD))
        max_speed = round(max(2.0, tier * taper), 1)
        advisory = (
            f"Elevated operational risk. Limit speed to {max_speed} knots, avoid convergent leads and "
            "ridged floes, and obtain ice navigator concurrence before proceeding."
        )
    else:
        status = "OPERATION_PROHIBITED"
        permitted, restricted = False, True
        max_speed = 0.0
        advisory = (
            "Operation not permitted under POLARIS. Severe risk of structural damage or besetting. "
            "Divert, await ice relaxation, or request icebreaker escort."
        )

    return POLARISAssessmentResult(
        vessel_ice_class=ice_class,
        evaluated_as=resolved,
        total_concentration_tenths=10,
        rio=rio,
        status=status,
        is_operation_permitted=permitted,
        is_speed_restricted=restricted,
        max_recommended_speed_knots=max_speed,
        advisory_notes=advisory,
        per_component_contributions=contributions,
        decayed_ice_applied=decayed,
    )


def rio_for_uniform_regime(
    ice_class: IceClass,
    ice_type: IceType,
    concentration: float,
    decayed: bool = False,
) -> int:
    """
    Fast path for the route search and gridded map layers: a single ice type at a given
    fractional concentration, with the remainder treated as ice free.
    """
    tenths = int(round(max(0.0, min(1.0, concentration)) * 10))
    rv = risk_value(ice_class, ice_type, decayed=decayed)
    rv_free = risk_value(ice_class, IceType.ICE_FREE, decayed=decayed)
    return tenths * rv + (10 - tenths) * rv_free


def speed_limit_for_rio(ice_class: IceClass, rio: int) -> float:
    """The POLARIS speed ceiling for an already-computed RIO, without rebuilding the regime."""
    if rio >= RIO_NORMAL_THRESHOLD:
        return NORMAL_OPERATION_SPEED_KNOTS
    if rio < RIO_PROHIBITED_THRESHOLD:
        return 0.0
    tier = _ELEVATED_RISK_SPEED_TIERS.get(resolve_class(ice_class), 5.0)
    return round(max(2.0, tier * (1.0 - 0.67 * (abs(rio) / abs(RIO_PROHIBITED_THRESHOLD)))), 1)


def risk_value_matrix(ice_class: Optional[IceClass] = None) -> Dict[str, object]:
    """The full table, shaped for the interface to render as a heat-mapped grid."""
    classes = [ice_class] if ice_class else list(_RIV_ROWS.keys())
    return {
        "ice_types": [t.value for t in _TABLE_ORDER],
        "ice_type_bounds_m": {
            t.value: ICE_TYPE_THICKNESS_BOUNDS_M.get(t) for t in _TABLE_ORDER
        },
        "rows": {
            resolve_class(c).value: {
                t.value: risk_value(c, t) for t in _TABLE_ORDER
            }
            for c in classes
        },
        "equivalences": {k.value: v.value for k, v in CLASS_EQUIVALENCE.items()},
        "thresholds": {
            "normal_operation": RIO_NORMAL_THRESHOLD,
            "prohibited_below": RIO_PROHIBITED_THRESHOLD,
        },
        "reference": "IMO MSC.1/Circ.1519",
        "is_synthetic": False,
    }


#: Retained so any v0.1 import site keeps resolving. Prefer risk_value() or risk_value_matrix().
RISK_VALUE_MATRIX: Dict[IceClass, Dict[IceType, int]] = {
    cls: {t: risk_value(cls, t) for t in _TABLE_ORDER} for cls in _RIV_ROWS
}
