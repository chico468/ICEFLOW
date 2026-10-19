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
