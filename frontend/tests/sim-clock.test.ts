import assert from 'node:assert/strict';
import { test } from 'node:test';
import { useSimClock } from '../src/store/useSimClock.ts';

const get = () => useSimClock.getState();

test('useSimClock starts paused at speed 1 with simMs 0', () => {
  const s = get();
  assert.equal(s.paused, true);
  assert.equal(s.speed, 1);
  assert.equal(s.simMs, 0);
  assert.deepEqual(s.timeline, []);
});

test('useSimClock setTimeline sets timeline and resets simMs', () => {
  const tl = [{ index: 0, sim_hours: 0 }];
  get().setTimeline(tl as any);
  const s = get();
  assert.equal(s.timeline, tl);
  assert.equal(s.simMs, 0);
  assert.equal(s.paused, true);
});

test('useSimClock setSpeed accepts valid speeds', () => {
  get().setSpeed(600);
  assert.equal(get().speed, 600);
  get().setSpeed(1);
  assert.equal(get().speed, 1);
});

test('useSimClock seekHours converts hours to ms', () => {
  get().seekHours(3);
  assert.equal(get().simMs, 3 * 3600 * 1000);
});

test('useSimClock setSimMs sets raw ms', () => {
  get().setSimMs(5000);
  assert.equal(get().simMs, 5000);
});

test('useSimClock reset clears everything', () => {
  get().setTimeline([{ index: 0, sim_hours: 0 }] as any);
  get().setSpeed(3600);
  get().setPaused(false);
  get().setSimMs(999999);
  get().reset();
  const s = get();
  assert.deepEqual(s.timeline, []);
  assert.equal(s.simMs, 0);
  assert.equal(s.speed, 1);
  assert.equal(s.paused, true);
});
