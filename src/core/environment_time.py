"""Resolve calendar and model-relative environmental time without conflating their clocks."""
from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from pydantic import BaseModel


class EnvironmentTimeError(ValueError):
    """Raised when time inputs cannot describe an unambiguous UTC instant."""


class EnvironmentTimeResolution(BaseModel):
    mode: Literal["active_voyage", "planning_forecast"]
    status: Literal["resolved", "unavailable"]
    target_time_utc: Optional[datetime] = None
    reference_time_utc: Optional[datetime] = None
    elapsed_sim_hours: Optional[float] = None
    lead_hours: Optional[float] = None
    model_departure_time_hours: Optional[float] = None
    tick_time_utc: Optional[datetime] = None
    reason: Optional[str] = None


class IcebergTimeResolution(BaseModel):
    mode: Literal["active_voyage"]
    status: Literal["resolved", "unavailable"]
    target_model_hours: Optional[float] = None
    forecast_lead_hours: Optional[int] = None
    forcing_start_hours: Optional[float] = None
    reason: Optional[str] = None


def parse_utc_datetime(value: str | datetime, field_name: str = "datetime") -> datetime:
    """Parse a timezone-aware timestamp and normalize it to UTC."""
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError as exc:
            raise EnvironmentTimeError(f"{field_name} must be a valid ISO-8601 timestamp.") from exc
    else:
        parsed = value

    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise EnvironmentTimeError(f"{field_name} must include a timezone offset.")

    try:
        return parsed.astimezone(timezone.utc)
    except OverflowError as exc:
        raise EnvironmentTimeError(f"{field_name} is outside the supported datetime range.") from exc


def _finite_hours(value: float, field_name: str, non_negative: bool = False) -> float:
    try:
        hours = float(value)
    except (TypeError, ValueError) as exc:
        raise EnvironmentTimeError(f"{field_name} must be a finite number.") from exc
    if not math.isfinite(hours):
        raise EnvironmentTimeError(f"{field_name} must be a finite number.")
    if non_negative and hours < 0:
        raise EnvironmentTimeError(f"{field_name} cannot be negative.")
    return hours


def _add_hours(reference: datetime, hours: float, field_name: str) -> datetime:
    try:
        return reference + timedelta(hours=hours)
    except OverflowError as exc:
        raise EnvironmentTimeError(f"{field_name} is outside the supported datetime range.") from exc


def resolve_active_voyage_time(
    departure_iso: str | datetime,
    sim_hours: float,
    tick_timestamp_iso: Optional[str | datetime] = None,
    model_departure_time_hours: Optional[float] = None,
) -> EnvironmentTimeResolution:
    elapsed = _finite_hours(sim_hours, "sim_hours", non_negative=True)
    departure = parse_utc_datetime(departure_iso, "departure_iso")
    target = _add_hours(departure, elapsed, "sim_hours")

    tick_time = parse_utc_datetime(tick_timestamp_iso, "timestamp_iso") if tick_timestamp_iso is not None else None
    if tick_time is not None:
        if abs((tick_time - target).total_seconds()) > 1.1:
            raise EnvironmentTimeError("timestamp_iso is inconsistent with departure_iso plus sim_hours.")

    model_hours = (
        _finite_hours(model_departure_time_hours, "departure_time_hours", non_negative=True)
        if model_departure_time_hours is not None
        else None
    )

    return EnvironmentTimeResolution(
        mode="active_voyage",
        status="resolved",
        target_time_utc=target,
        reference_time_utc=departure,
        elapsed_sim_hours=elapsed,
        model_departure_time_hours=model_hours,
        tick_time_utc=tick_time,
    )


def resolve_planning_time(
    planning_reference_iso: Optional[str | datetime] = None,
    lead_hours: float = 0.0,
    departure_time_hours: float = 0.0,
) -> EnvironmentTimeResolution:
    lead = _finite_hours(lead_hours, "lead_hours", non_negative=True)
    model_hours = _finite_hours(departure_time_hours, "departure_time_hours", non_negative=True)

    if planning_reference_iso is None or (isinstance(planning_reference_iso, str) and not planning_reference_iso.strip()):
        return EnvironmentTimeResolution(
            mode="planning_forecast",
            status="unavailable",
            lead_hours=lead,
            model_departure_time_hours=model_hours,
            reason="No timezone-aware planning_reference_iso was supplied.",
        )

    reference = parse_utc_datetime(planning_reference_iso, "planning_reference_iso")
    target = _add_hours(reference, lead, "lead_hours")

    return EnvironmentTimeResolution(
        mode="planning_forecast",
        status="resolved",
        target_time_utc=target,
        reference_time_utc=reference,
        lead_hours=lead,
        model_departure_time_hours=model_hours,
    )


def resolve_iceberg_target_time(sim_hours: float) -> IcebergTimeResolution:
    """Map voyage elapsed model hours to the catalogue-seed drift API contract."""
    try:
        hours = float(sim_hours)
    except (TypeError, ValueError):
        hours = math.nan

    if not math.isfinite(hours) or hours < 0:
        return IcebergTimeResolution(
            mode="active_voyage",
            status="unavailable",
            reason="The active-voyage elapsed time must be finite and non-negative.",
        )
    if hours > 240:
        return IcebergTimeResolution(
            mode="active_voyage",
            status="unavailable",
            reason="The iceberg drift API supports forecast horizons up to 240 hours.",
        )
    if not hours.is_integer():
        return IcebergTimeResolution(
            mode="active_voyage",
            status="unavailable",
            reason="The iceberg drift API only represents whole-hour forecast horizons.",
        )

    return IcebergTimeResolution(
        mode="active_voyage",
        status="resolved",
        target_model_hours=hours,
        forecast_lead_hours=int(hours),
        forcing_start_hours=0.0,
    )
