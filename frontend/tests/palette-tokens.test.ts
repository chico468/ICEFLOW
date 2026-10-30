import assert from 'node:assert/strict';
import { readFileSync } from 'node:fs';
import { test } from 'node:test';
import { BRAND } from '../src/map/palette.ts';

const BRAND_TO_CSS: ReadonlyArray<[keyof typeof BRAND, string]> = [
  ['ground', '--c-ground'],
  ['panel', '--c-panel'],
  ['panel-2', '--c-panel-2'],
  ['panel-3', '--c-panel-3'],
  ['hair', '--c-hair'],
  ['hair-2', '--c-hair-2'],
  ['ink', '--c-ink'],
  ['ink-2', '--c-ink-2'],
  ['ink-3', '--c-ink-3'],
  ['accent', '--c-accent'],
  ['accent-2', '--c-accent-2'],
  ['on-accent', '--c-on-accent'],
];

function rgbToHex(r: number, g: number, b: number): string {
  return (
    '#' +
    [r, g, b]
      .map((n) => n.toString(16).padStart(2, '0').toUpperCase())
      .join('')
  );
}

test('every BRAND token in palette.ts matches its --c-* CSS variable in index.css', () => {
  const css = readFileSync(new URL('../src/index.css', import.meta.url), 'utf-8');

  for (const [brandKey, cssVar] of BRAND_TO_CSS) {
    const escaped = cssVar.replace(/-/g, '\\-');
    const match = new RegExp(`${escaped}\\s*:\\s*(\\d+)\\s+(\\d+)\\s+(\\d+)\\s*;`).exec(css);
    assert.ok(match, `CSS variable ${cssVar} not found in index.css`);
    const cssHex = rgbToHex(Number(match[1]), Number(match[2]), Number(match[3]));
    const brandHex = BRAND[brandKey];
    assert.equal(
      cssHex,
      brandHex,
      `BRAND.${String(brandKey)} (${brandHex}) drifted from ${cssVar} (${cssHex}) in index.css`,
    );
  }
});
