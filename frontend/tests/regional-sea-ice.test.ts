import assert from 'node:assert/strict';
import { test } from 'node:test';
import type {
  EnvironmentLayerMetadata,
  EnvironmentLayersResponse,
} from '../src/api/types';
import {
  buildRegionalEnvironmentRequest,
  formatSeaIceValidTime,
  resolveRegionalSeaIceEdgeSelection,
} from '../src/lib/regionalSeaIce.ts';

const validTime = '2026-10-19T00:00:00Z';

function layer(
  key: string,
  overrides: Partial<EnvironmentLayerMetadata> = {},
): EnvironmentLayerMetadata {
  const mode = 'edge';
  const style = 'cmap:viridis';
  return {
    key,
    status: 'ready',
    target_time_utc: '2026-10-24T00:00:00Z',
    source_valid_time_utc: validTime,
    source_valid_interval_start_utc: null,
    source_valid_interval_end_utc: null,
    observation_time_utc: validTime,
    retrieved_at_utc: '2026-10-24T03:00:00Z',
    classification: 'observation',
    forecast_lead_hours: null,
    age_hours: 120,
    offset_hours: -120,
    product: 'SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001',
    dataset: 'osisaf-example-dataset',
    layer: `osisaf-example-dataset/${key}`,
    variable: 'ice_edge',
    units: null,
    standard_name: null,
    data_updated_at_utc: null,
    metadata_updated_at_utc: null,
    product_released_at_utc: null,
    source_crs: 'urn:ogc:def:crs:EPSG::3857',
    tile_matrix_set: 'EPSG:3857',
    style,
    tile_max_zoom: 10,
    tile_template: `https://wmts.example/tiles?style=${encodeURIComponent(style)}&tilematrix={z}&tilecol={x}&tilerow={y}&time=${validTime}`,
    render_tile_template: `http://127.0.0.1:8000/api/v1/environment/layers/tiles/${mode}/{z}/{x}/{y}.png?target_time_utc=2026-10-24T00%3A00%3A00Z&source_valid_time_utc=${validTime}`,
    render_quality_layer: 'osisaf-example-dataset/status_flag',
    render_quality_style: 'cmap:rainbow',
    render_quality_valid_time_utc: validTime,
    render_quality_tile_matrix_set: 'EPSG:3857',
    render_quality_tile_max_zoom: 10,
    render_quality_tile_template: `https://wmts.example/tiles?layer=osisaf-example-dataset/status_flag&style=cmap%3Arainbow&time=${validTime}&tilematrix={z}&tilecol={x}&tilerow={y}`,
    render_quality_tile_dimensions: { time: validTime },
    render_quality_reason: null,
    render_status: 'ready',
    render_reason: null,
    tile_dimensions: { time: validTime },
    attribution: 'Copernicus Marine Service (CMEMS)',
    provenance: 'Copernicus Marine WMTS',
    reason: null,
    ...overrides,
  };
}

function response(
  edge: EnvironmentLayerMetadata = layer('sea_ice_edge'),
): EnvironmentLayersResponse {
  return {
    target_time_utc: '2026-10-24T00:00:00Z',
    mode: 'planning_forecast',
    time_resolution: {
      mode: 'planning_forecast',
      status: 'resolved',
      target_time_utc: '2026-10-24T00:00:00Z',
      reference_time_utc: '2026-10-24T00:00:00Z',
      elapsed_sim_hours: null,
      lead_hours: 0,
      model_departure_time_hours: 0,
      tick_time_utc: null,
      reason: null,
    },
    layers: {
      sea_ice_edge: edge,
    },
  };
}

test('planning request resolves forecast lead from a UTC reference without treating model hours as UTC', () => {
  const request = buildRegionalEnvironmentRequest({
    voyage: null,
    tick: null,
    plan: { departure_time_hours: 42 },
    leadHours: 12,
    planningReferenceIso: '2026-10-24T00:00:00Z',
  });
  assert.deepEqual(request, {
    target_time_utc: '2026-10-24T12:00:00.000Z',
    mode: 'planning_forecast',
    planning_reference_iso: '2026-10-24T00:00:00Z',
    lead_hours: 12,
    departure_time_hours: 42,
  });
});

test('active voyage request uses departure plus latest simulation tick and checks tick timestamp', () => {
  const request = buildRegionalEnvironmentRequest({
    voyage: {
      departure_iso: '2026-10-23T12:00:00Z',
      sim_hours: 6,
      model_departure_time_hours: 24,
    },
    tick: { sim_hours: 12, timestamp_iso: '2026-10-24T00:00:00Z' },
    plan: null,
    leadHours: 48,
    planningReferenceIso: '2026-10-20T00:00:00Z',
  });
  assert.equal(request?.mode, 'active_voyage');
  assert.equal(request?.target_time_utc, '2026-10-24T00:00:00.000Z');
  assert.equal(request?.sim_hours, 12);
  assert.equal(request?.timestamp_iso, '2026-10-24T00:00:00Z');
  assert.equal(request?.departure_time_hours, 24);
  assert.equal(request?.lead_hours, undefined);
});

test('edge preserves its observed time and source metadata while labeling stale data', () => {
  const selection = resolveRegionalSeaIceEdgeSelection(
    response(layer('sea_ice_edge', {
      status: 'stale',
      units: null,
      reason: 'Observation is old.',
    })),
  );
  assert.equal(selection.status, 'stale');
  assert.equal(selection.validTimeUtc, validTime);
  assert.equal(selection.targetTimeUtc, '2026-10-24T00:00:00Z');
  assert.equal(selection.retrievedAtUtc, '2026-10-24T03:00:00Z');
  assert.equal(selection.product, 'SEAICE_GLO_SEAICE_L4_NRT_OBSERVATIONS_011_001');
  assert.match(selection.tileTemplate ?? '', /tiles\/edge\/\{z\}\/\{x\}\/\{y\}\.png/);
  assert.equal(selection.sourceName, 'osisaf-example-dataset');
  assert.equal(formatSeaIceValidTime(selection.validTimeUtc), '2026-10-19 00:00:00 UTC');
});

test('edge selection surfaces why an older renderable observation was selected', () => {
  const selection = resolveRegionalSeaIceEdgeSelection(
    response(layer('sea_ice_edge', {
      reason: 'The newer advertised edge observation failed its WMTS tile check; showing the newest observation that rendered successfully.',
    })),
  );
  assert.equal(selection.status, 'ready');
  assert.match(selection.reason ?? '', /newer advertised edge observation failed/);
});

test('edge requires a same-time, tile-compatible quality mask', () => {
  const result = resolveRegionalSeaIceEdgeSelection(
    response(
      layer('sea_ice_edge', {
        render_quality_valid_time_utc: '2026-10-18T00:00:00Z',
      }),
    ),
  );
  assert.equal(result.status, 'unavailable');
  assert.equal(result.tileTemplate, null);
});

test('does not advertise an observation when the selected edge tile uses another time', () => {
  const result = resolveRegionalSeaIceEdgeSelection(
    response(
      layer('sea_ice_edge', {
        source_valid_time_utc: '2026-10-18T00:00:00Z',
        tile_dimensions: { time: '2026-10-18T00:00:00Z' },
      }),
    ),
  );
  assert.equal(result.status, 'unavailable');
  assert.equal(result.validTimeUtc, null);
});

test('reports unavailable metadata when edge is missing', () => {
  const data = response();
  delete data.layers.sea_ice_edge;
  const result = resolveRegionalSeaIceEdgeSelection(data);
  assert.equal(result.status, 'unavailable');
  assert.equal(result.validTimeUtc, null);
  assert.equal(result.tileTemplate, null);
});

test('does not render unsupported or unavailable responses', () => {
  for (const status of ['unsupported_time', 'outside_coverage', 'unavailable', 'error'] as const) {
    const result = resolveRegionalSeaIceEdgeSelection(
      response(layer('sea_ice_edge', { status })),
    );
    assert.equal(result.status, status);
    assert.equal(result.tileTemplate, null);
  }
  const missingTile = resolveRegionalSeaIceEdgeSelection(response(layer('sea_ice_edge', {
    status: 'stale',
    render_tile_template: null,
  })));
  assert.equal(missingTile.status, 'unavailable');
  assert.equal(missingTile.tileTemplate, null);
});

test('rejects incompatible tile matrix metadata and unsupported edge units', () => {
  const incompatible = resolveRegionalSeaIceEdgeSelection(
    response(layer('sea_ice_edge', { tile_matrix_set: 'EPSG:4326' })),
  );
  assert.equal(incompatible.status, 'unavailable');

  const notPercent = resolveRegionalSeaIceEdgeSelection(
    response(layer('sea_ice_edge', { units: '1' })),
  );
  assert.equal(notPercent.status, 'unavailable');
  assert.match(notPercent.reason ?? '', /categorical/);
});

test('rejects a source whose selected tile time differs from its reported valid time', () => {
  const result = resolveRegionalSeaIceEdgeSelection(
    response(layer('sea_ice_edge', {
      tile_dimensions: { time: '2026-10-18T00:00:00Z' },
    })),
  );
  assert.equal(result.status, 'unavailable');
});
