/**
 * Shared UTC environmental time contract for the frontend.
 * Resolves calendar timestamps and simulation offsets without conflating their clocks.
 */
import type { EnvironmentTimeResolution } from '../api/types';

export type { EnvironmentTimeResolution } from '../api/types';

export function parseUtcDatetime(value: string, fieldName = 'datetime'): Date {
  if (typeof value !== 'string' || !value.trim()) {
    throw new Error(`${fieldName} must be a valid ISO-8601 timestamp.`);
  }

  // Must include timezone offset: Z, +HH:MM, -HH:MM, etc.
  if (!/(?:Z|[+-]\d{2}:?\d{2})$/i.test(value.trim())) {
    throw new Error(`${fieldName} must include a timezone offset.`);
  }

  const date = new Date(value);
  if (Number.isNaN(date.getTime())) {
    throw new Error(`${fieldName} must be a valid ISO-8601 timestamp.`);
  }
  return date;
}

export function formatUtcIso(date: Date): string {
  return date.toISOString().replace(/\.\d{3}Z$/, 'Z');
}

export function resolveActiveVoyageTime(
  departureIso: string,
  simHours: number,
  tickTimestampIso?: string | null,
  modelDepartureTimeHours?: number | null,
): EnvironmentTimeResolution {
  if (typeof simHours !== 'number' || !Number.isFinite(simHours)) {
    throw new Error('sim_hours must be a finite number.');
  }
  if (simHours < 0) {
    throw new Error('sim_hours cannot be negative.');
  }
  if (
    modelDepartureTimeHours != null
    && (!Number.isFinite(modelDepartureTimeHours) || modelDepartureTimeHours < 0)
  ) {
    throw new Error('departure_time_hours must be a finite, non-negative number.');
  }

  const departure = parseUtcDatetime(departureIso, 'departure_iso');
  const targetTime = new Date(departure.getTime() + simHours * 3600 * 1000);
  if (!Number.isFinite(targetTime.getTime())) {
    throw new Error('sim_hours is outside the supported datetime range.');
  }

  let tickTimeUtc: string | null = null;
  if (tickTimestampIso) {
    const tickTime = parseUtcDatetime(tickTimestampIso, 'timestamp_iso');
    if (Math.abs(tickTime.getTime() - targetTime.getTime()) > 1100) {
      throw new Error('timestamp_iso is inconsistent with departure_iso plus sim_hours.');
    }
    tickTimeUtc = tickTime.toISOString();
  }

  return {
    mode: 'active_voyage',
    status: 'resolved',
    target_time_utc: targetTime.toISOString(),
    reference_time_utc: departure.toISOString(),
    elapsed_sim_hours: simHours,
    lead_hours: null,
    model_departure_time_hours: modelDepartureTimeHours ?? null,
    tick_time_utc: tickTimeUtc,
    reason: null,
  };
}

export function resolvePlanningTime(
  planningReferenceIso?: string | null,
  leadHours = 0,
  departureTimeHours = 0,
): EnvironmentTimeResolution {
  if (typeof leadHours !== 'number' || !Number.isFinite(leadHours)) {
    throw new Error('lead_hours must be a finite number.');
  }
  if (leadHours < 0) {
    throw new Error('lead_hours cannot be negative.');
  }
  if (typeof departureTimeHours !== 'number' || !Number.isFinite(departureTimeHours)) {
    throw new Error('departure_time_hours must be a finite number.');
  }
  if (departureTimeHours < 0) {
    throw new Error('departure_time_hours cannot be negative.');
  }

  if (!planningReferenceIso || !planningReferenceIso.trim()) {
    return {
      mode: 'planning_forecast',
      status: 'unavailable',
      target_time_utc: null,
      reference_time_utc: null,
      elapsed_sim_hours: null,
      lead_hours: leadHours,
      model_departure_time_hours: departureTimeHours,
      tick_time_utc: null,
      reason: 'No timezone-aware planning_reference_iso was supplied.',
    };
  }

  const reference = parseUtcDatetime(planningReferenceIso, 'planning_reference_iso');
  const target = new Date(reference.getTime() + leadHours * 3600 * 1000);
  if (!Number.isFinite(target.getTime())) {
    throw new Error('lead_hours is outside the supported datetime range.');
  }

  return {
    mode: 'planning_forecast',
    status: 'resolved',
    target_time_utc: target.toISOString(),
    reference_time_utc: reference.toISOString(),
    elapsed_sim_hours: null,
    lead_hours: leadHours,
    model_departure_time_hours: departureTimeHours,
    tick_time_utc: null,
    reason: null,
  };
}
