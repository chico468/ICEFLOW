import assert from 'node:assert/strict';
import { test } from 'node:test';
import {
  CHANGE_DEADBAND,
  ICE_BANDS,
  bandCss,
  changeCss,
  classedCss,
  concentrationCss,
  concentrationRgb,
  iceBandOf,
} from '../src/map/palette.ts';

test('ice bands are contiguous, start at 0 and cover 100 percent', () => {
  assert.equal(ICE_BANDS[0].from, 0);
  for (let i = 1; i < ICE_BANDS.length; i += 1) assert.equal(ICE_BANDS[i].from, ICE_BANDS[i - 1].to, `gap before ${ICE_BANDS[i].key}`);
  assert.ok(ICE_BANDS[ICE_BANDS.length - 1].to > 1);
});

test('band boundaries fall where the legend says they do', () => {
  assert.equal(iceBandOf(0).key, 'open');
  assert.equal(iceBandOf(0.1499).key, 'open');
  assert.equal(iceBandOf(0.15).key, 'low', '15 percent is the ice-edge threshold and is already ice');
  assert.equal(iceBandOf(0.4).key, 'moderate');
  assert.equal(iceBandOf(0.7).key, 'dense');
  assert.equal(iceBandOf(0.9).key, 'veryDense');
  assert.equal(iceBandOf(1).key, 'veryDense');
  assert.equal(iceBandOf(1.5).key, 'veryDense', 'out-of-range values clamp rather than throw');
  assert.equal(iceBandOf(-1).key, 'open');
});

test('the classes raster paints exactly the colour the legend swatch shows', () => {
  for (const c of [0.05, 0.2, 0.5, 0.8, 0.95]) assert.equal(classedCss(c), bandCss(iceBandOf(c)));
});

test('concentration colour darkens as ice gets denser', () => {
  const lum = (c: number): number => {
    const [r, g, b] = concentrationRgb(c);
    return 0.2126 * r + 0.7152 * g + 0.0722 * b;
  };
  for (let c = 0.05; c <= 1; c += 0.05) assert.ok(lum(c) <= lum(c - 0.05) + 1e-9, `not monotonic at ${c}`);
  assert.match(concentrationCss(0.5), /^rgba\(\d+,\d+,\d+,1\)$/);
});

test('change colours: a dead band, and distinct hues for advance and retreat', () => {
  assert.equal(changeCss(0), null);
  assert.equal(changeCss(CHANGE_DEADBAND - 0.001), null);
  assert.equal(changeCss(-(CHANGE_DEADBAND - 0.001)), null);
  assert.equal(changeCss(Number.NaN), null, 'a missing value is not painted as no change');
  const gain = changeCss(0.3)!;
  const loss = changeCss(-0.3)!;
  assert.notEqual(gain, loss);
  assert.doesNotMatch(gain + loss, /rgba\((180|19\d|2\d\d),\s*(83|38|6\d)/, 'amber and red stay reserved for hazard');
});
