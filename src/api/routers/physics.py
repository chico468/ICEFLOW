"""POLARIS risk, Lindqvist resistance, vessel presets and the radar sweep.

The two POST endpoints here keep their v0.1 request bodies exactly, so anything written against
the first prototype still works. The responses gained fields; none were removed.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from src.core.constants import DATA_PROVENANCE
from src.core.growler_radar import RadarSweep, simulate_sweep
from src.core.lindqvist_model import (
    VESSEL_PRESETS,
    ResistanceResult,
    VesselParameters,
    attainable_speed,
    calculate_ice_resistance,
    get_vessel_preset,
    speed_power_curve,
)
from src.core.polaris_risk import (
    IceClass,
    IceRegimeComponent,
    POLARISAssessmentResult,
    calculate_rio,
    classify_ice_type,
    risk_value_matrix,
)

router = APIRouter(prefix="/api/v1", tags=["physics"])


# --------------------------------------------------------------------------- POLARIS
class POLARISRequest(BaseModel):
    ice_class: IceClass = IceClass.PC5
    components: List[IceRegimeComponent]
    decayed: bool = Field(default=False, description="Apply the melt-season decayed-ice allowance")


@router.post("/risk/polaris", response_model=POLARISAssessmentResult)
def assess_polaris_risk(req: POLARISRequest) -> POLARISAssessmentResult:
    """Risk Index Outcome for an ice regime, per IMO MSC.1/Circ.1519."""
    try:
        return calculate_rio(req.ice_class, req.components, decayed=req.decayed)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc


@router.get("/risk/matrix")
def polaris_matrix(ice_class: Optional[IceClass] = Query(default=None)) -> Dict[str, Any]:
    """The full Risk Value table, shaped for the interface to render as a heat map."""
    return risk_value_matrix(ice_class) | {"provenance": DATA_PROVENANCE["polaris_matrix"]}


@router.get("/risk/classify")
def classify(
    thickness_m: float = Query(..., ge=0.0),
    concentration: float = Query(default=1.0, ge=0.0, le=1.0),
) -> Dict[str, Any]:
    """Map an ice thickness to its WMO stage of development, the POLARIS table input."""
    ice_type = classify_ice_type(thickness_m, concentration)
    return {"thickness_m": thickness_m, "concentration": concentration, "ice_type": ice_type.value}


# ------------------------------------------------------------------------- resistance
class ResistanceRequest(BaseModel):
    vessel: Optional[VesselParameters] = None
    vessel_key: Optional[str] = Field(default=None, description="Preset key, e.g. vasiliy_golovnin")
    velocity_knots: float = 10.0
    ice_thickness_m: float = 0.8
    ice_concentration: float = 0.7


@router.post("/resistance/calculate", response_model=ResistanceResult)
def resistance(req: ResistanceRequest) -> ResistanceResult:
    """Lindqvist ice resistance, required power, fuel burn and CO2 for one operating point."""
    vessel = req.vessel or (get_vessel_preset(req.vessel_key) if req.vessel_key else VesselParameters())
    return calculate_ice_resistance(
        vessel=vessel,
        velocity_knots=req.velocity_knots,
        ice_thickness_m=req.ice_thickness_m,
        ice_concentration=req.ice_concentration,
    )


@router.get("/resistance/speed-power-curve")
def speed_power(
    vessel_key: str = Query(default="vasiliy_golovnin"),
    thicknesses: str = Query(default="0.0,0.3,0.6,1.0,1.5"),
    concentration: float = Query(default=0.8, ge=0.0, le=1.0),
) -> Dict[str, Any]:
    """Power and fuel against speed, one series per ice thickness."""
    try:
        vessel = get_vessel_preset(vessel_key)
        thickness_list = [float(x) for x in thicknesses.split(",") if x.strip()]
    except (KeyError, ValueError) as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    if not thickness_list or len(thickness_list) > 8:
        raise HTTPException(status_code=400, detail="Provide between 1 and 8 ice thicknesses.")

    speeds = [round(0.5 + 0.5 * i, 2) for i in range(36)]
    return speed_power_curve(vessel, thickness_list, speeds) | {"ice_concentration": concentration}


@router.get("/resistance/attainable-speed")
def attainable(
    vessel_key: str = Query(default="vasiliy_golovnin"),
    ice_thickness_m: float = Query(default=1.0, ge=0.0),
    ice_concentration: float = Query(default=0.8, ge=0.0, le=1.0),
) -> Dict[str, Any]:
    """
    The speed the ship can actually make in these conditions.

    This is the function the route optimiser calls on every edge, which is what turns a fuel
    saving into a measurement rather than a claim.
    """
    vessel = get_vessel_preset(vessel_key)
    speed = attainable_speed(vessel, vessel.installed_power_kw, ice_thickness_m, ice_concentration)
    return {
        "vessel": vessel.display_name,
        "installed_power_kw": vessel.installed_power_kw,
        "ice_thickness_m": ice_thickness_m,
        "ice_concentration": ice_concentration,
        "attainable_speed_knots": round(speed, 3),
        "is_beset": speed <= 0.0,
    }


@router.get("/vessels")
def vessels() -> Dict[str, Any]:
    """Vessel presets available to the planner."""
    return {
        "vessels": [
            {"key": key, **params.model_dump()} for key, params in VESSEL_PRESETS.items()
        ],
        "note": (
            "Principal dimensions and installed power are published figures where available. "
            "Hull angles, block coefficient, propeller diameter and specific fuel consumption "
            "are engineering estimates and are marked as such in the source."
        ),
    }


# ------------------------------------------------------------------------------ radar
@router.get("/radar/sweep", response_model=RadarSweep)
def radar_sweep(
    lat: float = Query(...), lon: float = Query(...),
    heading_deg: float = Query(default=180.0),
    speed_knots: float = Query(default=8.0, ge=0.0),
    t_hours: float = Query(default=0.0),
) -> RadarSweep:
    """
    One simulated X-band PPI sweep, with the misses and false alarms a real radar produces.

    The missed-target count is the honest part: growlers with little freeboard disappear into
    sea clutter, which is exactly why they are the hazard they are.
    """
    return simulate_sweep(lat, lon, heading_deg, speed_knots, t_hours)
