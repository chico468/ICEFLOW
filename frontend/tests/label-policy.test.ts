import assert from 'node:assert/strict';
import { test } from 'node:test';
import { LABEL_PRIORITY, MAX_COUNTRY_LABELS, countryRankThreshold, showMarkLabel } from '../src/map/labelPolicy.ts';

const port = { kind: 'port', endpoint: false, indian: false } as const;
const station = { kind: 'station', endpoint: false, indian: false } as const;
const indian = { kind: 'station', endpoint: false, indian: true } as const;

test('endpoints are always named, at any zoom', () => {
  for (const z of [1, 1.5, 4, 20]) {
    assert.equal(showMarkLabel({ ...port, endpoint: true }, z), true);
    assert.equal(showMarkLabel({ ...station, endpoint: true }, z), true);
  }
});

test('ports, Indian stations and other stations earn labels at increasing zoom', () => {
  assert.equal(showMarkLabel(port, 1.9), false);
  assert.equal(showMarkLabel(port, 2), true);
  assert.equal(showMarkLabel(indian, 3.4), false);
  assert.equal(showMarkLabel(indian, 3.5), true);
  assert.equal(showMarkLabel(station, 5.9), false);
  assert.equal(showMarkLabel(station, 6), true);
});

test('at the whole-region view only endpoints are labelled', () => {
  assert.equal(showMarkLabel(port, 1) || showMarkLabel(station, 1) || showMarkLabel(indian, 1), false);
});

test('country threshold falls as you zoom in, and never rises above its zoom-1 value', () => {
  let last = Infinity;
  for (const z of [1, 2, 3, 5, 10]) {
    const t = countryRankThreshold(z);
    assert.ok(t < last || z === 1);
    last = t;
  }
  assert.equal(countryRankThreshold(0.2), countryRankThreshold(1), 'zoom below 1 is treated as 1');
  assert.ok(MAX_COUNTRY_LABELS <= 12, 'a cap keeps the map from becoming a list of names');
});

test('collision priority: the polar-view tag and endpoints survive before ports, stations, countries', () => {
  const p = LABEL_PRIORITY;
  assert.ok(p.view < p.endpoint && p.endpoint < p.port && p.port < p.station && p.station < p.country);
});
