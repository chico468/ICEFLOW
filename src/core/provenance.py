"""Provenance type and helpers for honest environmental labelling.

Every response that carries modelled or observed environmental data labels its source
through a list of ``Provenance`` entries so the frontend can render evidence badges
and the user can tell real observations from simulated surrogates.
"""
from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Literal, Optional

from pydantic import BaseModel, Field

ProvenanceKind = Literal["observed", "real_forecast", "simulated", "experimental_ml", "real-seed"]


class Provenance(BaseModel):
    """One labelled data source backing a response."""

    layer: str
    kind: ProvenanceKind
    source: str
    product: Optional[str] = None
    valid_time: Optional[str] = None
    age_hours: Optional[float] = None


class WaypointEta(BaseModel):
    """ETA for one waypoint along the optimised route."""

    index: int
    eta_iso: str


def _age_hours(valid_time_iso: Optional[str]) -> Optional[float]:
    if not valid_time_iso:
        return None
    try:
        valid = datetime.fromisoformat(valid_time_iso.replace("Z", "+00:00"))
        now = datetime.now(timezone.utc)
        return round((now - valid).total_seconds() / 3600.0, 1)
    except (ValueError, TypeError):
        return None


def simulated_provenance(valid_time_iso: Optional[str] = None) -> Provenance:
    return Provenance(
        layer="sea_ice_field",
        kind="simulated",
        source="synthetic Antarctic sea-ice analysis + semi-Lagrangian forecast",
        product="ICEFLOW internal (stands in for OSI-SAF OSI-401-b / AMSR2 / Sentinel-1 SAR)",
        valid_time=valid_time_iso,
        age_hours=_age_hours(valid_time_iso),
    )


def observed_provenance(valid_time_iso: str, source: str, product: Optional[str] = None) -> Provenance:
    return Provenance(
        layer="sea_ice_field",
        kind="observed",
        source=source,
        product=product,
        valid_time=valid_time_iso,
        age_hours=_age_hours(valid_time_iso),
    )


def build_provenance(
    environment_mode: str,
    departure_iso: Optional[str],
    valid_time_iso: Optional[str] = None,
    has_observed_ice: bool = True,
) -> List[Provenance]:
    """Build the provenance list for a route based on the environment mode.

    ``has_observed_ice`` makes the distinction between a real observation that
    was actually loaded and a ``real_ice`` request that fell back to the
    synthetic model. A fall-back is labelled ``simulated`` here, so the response
    never silently presents synthetic ice as observed.
    """
    sea_ice_is_observed = (
        environment_mode in ("real_ice", "replay") and has_observed_ice
    )
    valid = valid_time_iso or departure_iso
    if sea_ice_is_observed:
        sea_ice = observed_provenance(
            valid_time_iso=valid or "",
            source="NOAA/NSIDC CDR G02202 Version 6",
            product="G02202 daily Antarctic sea-ice concentration",
        )
    else:
        sea_ice = simulated_provenance(valid_time_iso=valid)
    return [
        sea_ice,
        Provenance(
            layer="atmosphere_ocean",
            kind="simulated",
            source="synthetic Southern Ocean forcing",
            note="Wind and waves remain simulated in real-ice modes.",
            valid_time=valid,
            age_hours=_age_hours(valid),
        ),
        Provenance(
            layer="iceberg_catalogue",
            kind="real-seed",
            source="US National Ice Center Antarctic iceberg tracking database",
            product="real berg names and calving origins; positions are seeded then propagated by the drift model",
        ),
    ]
