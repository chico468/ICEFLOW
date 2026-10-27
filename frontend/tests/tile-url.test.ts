import assert from 'node:assert/strict';
import { test } from 'node:test';
import { resolveTileTemplate } from '../src/api/client.ts';

const RELATIVE_TEMPLATE =
  '/api/v1/environment/layers/tiles/edge/{z}/{x}/{y}.png?target_time_utc=2026-10-24T00%3A00%3A00Z&source_valid_time_utc=2026-10-19T00%3A00%3A00Z';

test('resolveTileTemplate returns the relative path unchanged when no API origin is configured (same-origin)', () => {
  // VITE_API_BASE_URL is unset under `node --test`, so API_ORIGIN defaults to '' (same-origin):
  // the Vite dev proxy and same-origin production hosting apply.
  assert.equal(resolveTileTemplate(RELATIVE_TEMPLATE), RELATIVE_TEMPLATE);
});

test('resolveTileTemplate keeps any relative /api/v1 path same-origin when given an empty origin', () => {
  assert.equal(resolveTileTemplate(RELATIVE_TEMPLATE, ''), RELATIVE_TEMPLATE);
});

test('resolveTileTemplate qualifies the relative path with VITE_API_BASE_URL for a cross-origin deployment', () => {
  const qualified = resolveTileTemplate(RELATIVE_TEMPLATE, 'https://iceflow-api.example.com');
  assert.equal(
    qualified,
    'https://iceflow-api.example.com/api/v1/environment/layers/tiles/edge/{z}/{x}/{y}.png?target_time_utc=2026-10-24T00%3A00%3A00Z&source_valid_time_utc=2026-10-19T00%3A00%3A00Z',
  );
  // The API-origin cross-origin deployment must keep the placeholder contract Mapbox expects.
  assert.match(qualified ?? '', /\/\{z\}\/\{x\}\/\{y\}\.png/);
});

test('resolveTileTemplate strips no path components and preserves the query string verbatim', () => {
  const withOrigin = resolveTileTemplate(RELATIVE_TEMPLATE, 'https://api:8080');
  assert.equal(withOrigin, 'https://api:8080' + RELATIVE_TEMPLATE);
});

test('resolveTileTemplate passes null and undefined templates through as null', () => {
  assert.equal(resolveTileTemplate(null), null);
  assert.equal(resolveTileTemplate(undefined, 'https://iceflow-api.example.com'), null);
  assert.equal(resolveTileTemplate('', 'https://iceflow-api.example.com'), null);
});

test('resolveTileTemplate never produces a host-relative double slash', () => {
  assert.equal(
    resolveTileTemplate('/api/v1/environment/layers/tiles/edge/{z}/{x}/{y}.png', 'https://api.example.com'),
    'https://api.example.com/api/v1/environment/layers/tiles/edge/{z}/{x}/{y}.png',
  );
});
