import type {
  EnvironmentLayerMetadata,
  EnvironmentLayersRequest,
  EnvironmentLayersResponse,
  OptimizationSummary,
  VoyageState,
  VoyageTick,
} from '../api/types';
import { formatUtcIso, resolveActiveVoyageTime, resolvePlanningTime } from './environmentTime.ts';

export interface RegionalSeaIceSelection {
  status: 'ready' | 'stale' | 'unavailable' | 'outside_coverage' | 'unsupported_time' | 'error';
  sourceStatus: EnvironmentLayerMetadata['status'] | null;
  tileTemplate: string | null;
  maxZoom: number | null;
  validTimeUtc: string | null;
  targetTimeUtc: string | null;
  retrievedAtUtc: string | null;
  offsetHours: number | null;
  product: string | null;
  sourceName: string | null;
  attribution: string | null;
  reason: string | null;
}

export function buildRegionalEnvironmentRequest({
  voyage,
  tick,
  plan,
  leadHours,
  planningReferenceIso,
}: {
  voyage: Pick<VoyageState, 'departure_iso' | 'sim_hours' | 'model_departure_time_hours'> | null;
  tick: Pick<VoyageTick, 'sim_hours' | 'timestamp_iso'> | null;
  plan: Pick<OptimizationSummary, 'departure_time_hours'> | null;
  leadHours: number;
  planningReferenceIso: string | null;
}): EnvironmentLayersRequest | null {
  if (voyage) {
    const simHours = tick?.sim_hours ?? voyage.sim_hours;
    const resolution = resolveActiveVoyageTime(
      voyage.departure_iso,
      simHours,
      tick?.timestamp_iso,
      voyage.model_departure_time_hours,
    );
    if (!resolution.target_time_utc) return null;
    return {
      target_time_utc: resolution.target_time_utc,
      mode: 'active_voyage',
      departure_iso: voyage.departure_iso,
      sim_hours: simHours,
      timestamp_iso: tick?.timestamp_iso,
      departure_time_hours: voyage.model_departure_time_hours,
    };
  }

  if (!planningReferenceIso) return null;
  const resolution = resolvePlanningTime(
    planningReferenceIso,
    leadHours,
    plan?.departure_time_hours ?? 0,
  );
  if (!resolution.target_time_utc) return null;
  return {
    target_time_utc: resolution.target_time_utc,
    mode: 'planning_forecast',
    planning_reference_iso: planningReferenceIso,
    lead_hours: leadHours,
    departure_time_hours: plan?.departure_time_hours ?? 0,
  };
}

function sameInstant(first: string | null, second: string | null): boolean {
  if (!first || !second) return false;
  const firstMs = Date.parse(first);
  const secondMs = Date.parse(second);
  return Number.isFinite(firstMs) && Number.isFinite(secondMs) && firstMs === secondMs;
}

function tileTemplateMatchesSourceTime(
  template: string | null | undefined,
  sourceTime: string | null,
): boolean {
  if (!template || !sourceTime) return false;
  try {
    const url = new URL(template, 'http://localhost');
    return sameInstant(sourceTime, url.searchParams.get('source_valid_time_utc'));
  } catch {
    return false;
  }
}

function isUsableObservation(layer: EnvironmentLayerMetadata | undefined): boolean {
  return Boolean(
    layer
      && (layer.status === 'ready' || layer.status === 'stale')
      && layer.classification === 'observation'
      && layer.source_valid_time_utc
      && layer.tile_dimensions.time
      && sameInstant(layer.source_valid_time_utc, layer.tile_dimensions.time)
      && tileTemplateMatchesSourceTime(layer.render_tile_template, layer.source_valid_time_utc)
      && layer.render_tile_template?.includes('{z}')
      && layer.render_tile_template.includes('{x}')
      && layer.render_tile_template.includes('{y}')
      && (layer.render_status === undefined || layer.render_status === 'ready')
      && layer.style
      && layer.tile_matrix_set === 'EPSG:3857'
      && layer.source_crs?.includes('3857')
      && layer.tile_max_zoom !== null
      && layer.tile_max_zoom !== undefined,
  );
}

function hasUsableQualityMask(layer: EnvironmentLayerMetadata): boolean {
  return Boolean(
    layer.render_quality_layer
      && layer.render_quality_style
      && layer.render_quality_tile_matrix_set === 'EPSG:3857'
      && layer.render_quality_tile_max_zoom !== null
      && layer.render_quality_tile_max_zoom !== undefined
      && layer.render_quality_tile_template?.includes('{z}')
      && layer.render_quality_tile_template.includes('{x}')
      && layer.render_quality_tile_template.includes('{y}')
      && layer.render_quality_valid_time_utc
      && sameInstant(layer.source_valid_time_utc, layer.render_quality_valid_time_utc)
      && layer.render_quality_tile_dimensions?.time
      && sameInstant(layer.source_valid_time_utc, layer.render_quality_tile_dimensions.time),
  );
}

function blockedSelection(
  layer: EnvironmentLayerMetadata | undefined,
  reason: string,
): RegionalSeaIceSelection {
  const status = layer?.status === 'error'
    ? 'error'
    : layer?.status === 'unsupported_time'
      ? 'unsupported_time'
      : layer?.status === 'outside_coverage'
        ? 'outside_coverage'
        : 'unavailable';
  return {
    status,
    sourceStatus: layer?.status ?? null,
    tileTemplate: null,
    maxZoom: null,
    validTimeUtc: layer
      && sameInstant(layer.source_valid_time_utc, layer.tile_dimensions.time ?? null)
      && tileTemplateMatchesSourceTime(layer.render_tile_template, layer.source_valid_time_utc)
      ? layer.source_valid_time_utc
      : null,
    targetTimeUtc: layer?.target_time_utc ?? null,
    retrievedAtUtc: layer?.retrieved_at_utc ?? null,
    offsetHours: layer?.offset_hours ?? null,
    product: layer?.product ?? null,
    sourceName: layer?.dataset ?? null,
    attribution: layer?.attribution ?? null,
    reason: layer?.render_reason ?? layer?.reason ?? reason,
  };
}

export function resolveRegionalSeaIceEdgeSelection(
  response: EnvironmentLayersResponse | undefined,
): RegionalSeaIceSelection {
  const edge = response?.layers.sea_ice_edge;
  if (!edge) {
    return blockedSelection(
      undefined,
      'Copernicus sea-ice edge metadata is unavailable.',
    );
  }

  if (!isUsableObservation(edge)) {
    return blockedSelection(
      edge,
      edge.render_reason
        ?? edge.reason
        ?? 'The selected observation does not include a compatible public sea-ice tile.',
    );
  }
  if (
    edge.render_status === 'unavailable'
    || !hasUsableQualityMask(edge)
  ) {
    return blockedSelection(
      edge,
      edge.render_reason ?? 'No safe sea-ice edge renderer is available for this paired observation.',
    );
  }
  if (edge.units !== null || edge.variable !== 'ice_edge' || edge.style !== 'cmap:viridis') {
    return blockedSelection(
      edge,
      'The selected source is not the supported categorical sea-ice edge product.',
    );
  }

  const stale = edge.status === 'stale';
  return {
    status: stale ? 'stale' : 'ready',
    sourceStatus: edge.status,
    tileTemplate: edge.render_tile_template ?? null,
    maxZoom: edge.tile_max_zoom,
    validTimeUtc: edge.source_valid_time_utc,
    targetTimeUtc: edge.target_time_utc,
    retrievedAtUtc: edge.retrieved_at_utc,
    offsetHours: edge.offset_hours,
    product: edge.product,
    sourceName: edge.dataset,
    attribution: edge.attribution,
    reason: edge.reason ?? (stale ? 'The Copernicus sea-ice edge observation is stale.' : null),
  };
}

export function formatSeaIceValidTime(value: string | null): string {
  if (!value) return 'valid time unavailable';
  const date = new Date(value);
  if (Number.isNaN(date.getTime())) return 'valid time unavailable';
  return `${formatUtcIso(date).replace('T', ' ').replace('Z', ' UTC')}`;
}
