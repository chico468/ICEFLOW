/**
 * Iceberg forecast time alignment and limitations.
 * Maps simulation hours to the drift model's whole-hour forecast lead contract.
 */
import type { IcebergTimeResolution } from '../api/types';

export type { IcebergTimeResolution } from '../api/types';

export function resolveIcebergTargetTime(simHours: number): IcebergTimeResolution {
  if (typeof simHours !== 'number' || !Number.isFinite(simHours) || simHours < 0) {
    return {
      mode: 'active_voyage',
      status: 'unavailable',
      target_model_hours: null,
      forecast_lead_hours: null,
      forcing_start_hours: null,
      reason: 'The active-voyage elapsed time must be finite and non-negative.',
    };
  }

  if (simHours > 240) {
    return {
      mode: 'active_voyage',
      status: 'unavailable',
      target_model_hours: null,
      forecast_lead_hours: null,
      forcing_start_hours: null,
      reason: 'The iceberg drift API supports forecast horizons up to 240 hours.',
    };
  }

  if (!Number.isInteger(simHours)) {
    return {
      mode: 'active_voyage',
      status: 'unavailable',
      target_model_hours: null,
      forecast_lead_hours: null,
      forcing_start_hours: null,
      reason: 'The iceberg drift API only represents whole-hour forecast horizons.',
    };
  }

  return {
    mode: 'active_voyage',
    status: 'resolved',
    target_model_hours: simHours,
    forecast_lead_hours: simHours,
    forcing_start_hours: 0,
    reason: null,
  };
}
