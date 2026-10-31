// Guards the inactive-screen bug: a descendant that sets `visibility: visible` escapes the
// `visibility: hidden` that App puts on an inactive screen, and paints over the active one.
import assert from 'node:assert/strict';
import { readdirSync, readFileSync, statSync } from 'node:fs';
import { join, relative } from 'node:path';
import { test } from 'node:test';
import { fileURLToPath } from 'node:url';

const SRC = fileURLToPath(new URL('../src', import.meta.url));

function walk(dir: string): string[] {
  return readdirSync(dir).flatMap((name) => {
    const full = join(dir, name);
    return statSync(full).isDirectory() ? walk(full) : /\.(tsx?|css)$/.test(name) ? [full] : [];
  });
}

// `visibility: 'visible'`, `visibility: cond ? 'visible' : 'hidden'`, `visibility: visible` (css), `.visible` class is fine.
const OFFENDERS = [/visibility\s*:\s*['"`]visible['"`]/, /visibility\s*:[^;,}]*\?\s*['"`]visible['"`]/, /visibility\s*:\s*visible\b/];

test('no component below the screen wrapper forces visibility: visible', () => {
  const hits: string[] = [];
  for (const file of walk(SRC)) {
    const rel = relative(SRC, file);
    // App.tsx owns the screen wrapper, which is the one place allowed to say it.
    if (rel === 'App.tsx') continue;
    const text = readFileSync(file, 'utf8');
    text.split('\n').forEach((line, i) => {
      const t = line.trim();
      if (t.startsWith('*') || t.startsWith('//') || t.startsWith('/*')) return; // prose about the rule is fine
      if (OFFENDERS.some((re) => re.test(line))) hits.push(`${rel}:${i + 1}: ${t}`);
    });
  }
  assert.deepEqual(hits, [], `forced visibility would paint an inactive screen over the active one:\n${hits.join('\n')}`);
});

test('the screen wrapper in App still hides inactive screens with visibility, and nothing else conflicts', () => {
  const app = readFileSync(join(SRC, 'App.tsx'), 'utf8');
  assert.match(app, /visibility:\s*visible\s*\?\s*'visible'\s*:\s*'hidden'/);
});

test('flow layers never use a field while a request error is showing (stale vectors must not keep moving)', () => {
  const overlay = readFileSync(join(SRC, 'map', 'FlowOverlay.tsx'), 'utf8');
  assert.match(overlay, /const usable = error \? null : field;/);
  assert.doesNotMatch(overlay, /makeFlowGrid\(field\./, 'grids must be built from `usable`, not the raw field');
});

test('the flow legend keeps its honesty caveats (simulated, visual-aid speed, not real-time drift)', () => {
  const legend = readFileSync(join(SRC, 'components', 'MapLegend.tsx'), 'utf8').replace(/\s+/g, ' ');
  assert.match(legend, /not a real-time drift/);
  assert.match(legend, /SIMULATED/);
  assert.match(legend, /not satellite observation/);
  assert.match(legend, /Not zero ice/);
});

test('provenance: seeded (real-seed) data is never listed under "Real"', () => {
  const bar = readFileSync(join(SRC, 'components', 'ProvenanceBar.tsx'), 'utf8').replace(/\s+/g, ' ');
  assert.match(bar, /p\.status !== 'synthetic' && p\.status !== 'real-seed'/);
  assert.match(bar, /Seeded from real names, not observed/);
});

test('route ends are drawn only inside the optimised-route condition, with explicit braces', () => {
  const engine = readFileSync(join(SRC, 'map', 'MapEngine.ts'), 'utf8');
  assert.match(engine, /if \(L\.optimisedRoute && s\.optimisedRoute\.length > 1\) \{[\s\S]*?drawRouteEnds\(ctx, vp, s\.optimisedRoute\);\s*\}/);
});

test('dock tabs never nest a Panel\'s right-hand content inside the tab button (button-in-button is invalid HTML)', () => {
  const stage = readFileSync(join(SRC, 'components', 'MapStage.tsx'), 'utf8');
  const tab = stage.slice(stage.indexOf('role="tab"') - 400, stage.indexOf('role="tab"') + 900);
  const buttonOpen = tab.lastIndexOf('<button', tab.indexOf('role="tab"'));
  const buttonClose = tab.indexOf('</button>', buttonOpen);
  assert.ok(buttonClose > buttonOpen);
  assert.ok(!tab.slice(buttonOpen, buttonClose).includes('props.right'), 'props.right is inside the tab <button>');
});
