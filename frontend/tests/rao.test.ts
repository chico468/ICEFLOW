import assert from 'node:assert/strict';
import { test } from 'node:test';
import { raoMotion } from '../src/lib/sceneEnv.ts';

test('raoMotion roll/pitch/heave are monotonic in Hs', () => {
  const waveDirDeg = 45;
  const headingDeg = 0;
  const wavePeriodS = 8;
  const prev = { roll: -1, pitch: -1, heave: -1 };
  for (const hs of [0, 1, 2, 3, 4, 5, 6]) {
    const m = raoMotion({ hsM: hs, wavePeriodS, waveDirDeg, headingDeg });
    assert.ok(m.roll >= prev.roll, `roll not monotonic: ${prev.roll} -> ${m.roll} at hs=${hs}`);
    assert.ok(m.pitch >= prev.pitch, `pitch not monotonic: ${prev.pitch} -> ${m.pitch} at hs=${hs}`);
    assert.ok(m.heave >= prev.heave, `heave not monotonic: ${prev.heave} -> ${m.heave} at hs=${hs}`);
    prev.roll = m.roll;
    prev.pitch = m.pitch;
    prev.heave = m.heave;
  }
});

test('raoMotion is zero when Hs is zero', () => {
  const m = raoMotion({ hsM: 0, wavePeriodS: 8, waveDirDeg: 45, headingDeg: 0 });
  assert.strictEqual(m.roll, 0);
  assert.strictEqual(m.pitch, 0);
  assert.strictEqual(m.heave, 0);
});

test('raoMotion roll max at beam seas, pitch max at head seas', () => {
  const beam = raoMotion({ hsM: 2, wavePeriodS: 8, waveDirDeg: 90, headingDeg: 0 }).roll;
  const head = raoMotion({ hsM: 2, wavePeriodS: 8, waveDirDeg: 0, headingDeg: 0 }).roll;
  assert.ok(beam > head, `beam roll ${beam} should exceed head roll ${head}`);

  const headPitch = raoMotion({ hsM: 2, wavePeriodS: 8, waveDirDeg: 0, headingDeg: 0 }).pitch;
  const beamPitch = raoMotion({ hsM: 2, wavePeriodS: 8, waveDirDeg: 90, headingDeg: 0 }).pitch;
  assert.ok(headPitch > beamPitch, `head pitch ${headPitch} should exceed beam pitch ${beamPitch}`);
});
