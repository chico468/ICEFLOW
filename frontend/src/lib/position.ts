/**
 * PositionSource: the current ship position and environment, sampled from a timeline.
 *
 * PositionSource{ subscribe, now } — a minimal interface so the bridge can render the
 * ship's state without knowing whether it comes from a recording or a live socket.
 *
 * SimulatedPositionSource walks a TimelinePoint[] at the current sim clock time,
 * interpolating between steps. A future GPS/AIS source would implement the same interface;
 * this file makes no claim that any live GPS feed exists.
 */
import type { TimelinePoint } from './timeline';

export interface PositionFix {
  readonly index: number;
  readonly t_utc: string;
  readonly sim_hours: number;
  readonly lat: number;
  readonly lon: number;
  readonly sog_kn: number;
  readonly cog: number;
  readonly heading: number;
  readonly ice_conc: number;
  readonly ice_thick_m: number;
  readonly wind_speed_ms: number;
  readonly wind_dir_from_deg: number;
  readonly hs_m: number;
  readonly visibility_km: number;
  readonly nearest_contact_nm: number | null;
  readonly active_alerts: string[];
}

export interface PositionSource {
  /** Subscribe to position changes. Caller receives the current fix on every clock tick. */
  subscribe(cb: (fix: PositionFix) => void): () => void;
  /** Current fix (null before the clock has started). */
  now(): PositionFix | null;
  /** Whether the source is paused. */
  readonly paused: boolean;
}

export interface SimulatedPositionSourceProps {
  timeline: TimelinePoint[];
  onChange?: (fix: PositionFix | null) => void;
}

export function SimulatedPositionSource({
  timeline,
  onChange,
}: SimulatedPositionSourceProps): PositionSource {
  let listeners = new Set<(fix: PositionFix) => void>();
  let paused = true;
  let simMs = 0; // wall-clock ms elapsed since the sim started (at 1x)
  let speed = 1; // 1, 60, 600, 3600
  let raf: number | null = null;
  let startWall = 0;

  const timelineLength = timeline.length;

  const fixAt = (simMs: number): PositionFix | null => {
    if (timelineLength === 0) return null;
    // Convert sim ms to sim hours at 1x speed
    const simHours = simMs / 1000 / 3600;
    if (simHours <= 0) return toFix(timeline[0]);
    if (simHours >= timeline[timelineLength - 1].sim_hours) return toFix(timeline[timelineLength - 1]);

    // Binary search for the bracketing steps
    let lo = 0;
    let hi = timelineLength - 1;
    while (hi - lo > 1) {
      const mid = (lo + hi) >> 1;
      if (timeline[mid].sim_hours <= simHours) lo = mid;
      else hi = mid;
    }
    const a = timeline[lo];
    const b = timeline[hi];
    const span = b.sim_hours - a.sim_hours;
    const t = span === 0 ? 1 : (simHours - a.sim_hours) / span;
    return lerp(a, b, t);
  };

  const toFix = (p: TimelinePoint): PositionFix => ({
    index: p.index,
    t_utc: p.t_utc,
    sim_hours: p.sim_hours,
    lat: p.lat,
    lon: p.lon,
    sog_kn: p.sog_kn,
    cog: p.cog,
    heading: p.heading,
    ice_conc: p.ice_conc,
    ice_thick_m: p.ice_thick_m,
    wind_speed_ms: p.wind_speed_ms,
    wind_dir_from_deg: p.wind_dir_from_deg,
    hs_m: p.hs_m,
    visibility_km: p.visibility_km,
    nearest_contact_nm: p.nearest_contact_nm,
    active_alerts: p.active_alerts,
  });

  const lerp = (a: TimelinePoint, b: TimelinePoint, t: number): PositionFix => ({
    index: b.index,
    t_utc: b.t_utc,
    sim_hours: a.sim_hours + (b.sim_hours - a.sim_hours) * t,
    lat: a.lat + (b.lat - a.lat) * t,
    lon: a.lon + (b.lon - a.lon) * t,
    sog_kn: a.sog_kn + (b.sog_kn - a.sog_kn) * t,
    cog: a.cog + (b.cog - a.cog) * t,
    heading: a.heading + (b.heading - a.heading) * t,
    ice_conc: a.ice_conc + (b.ice_conc - a.ice_conc) * t,
    ice_thick_m: a.ice_thick_m + (b.ice_thick_m - a.ice_thick_m) * t,
    wind_speed_ms: a.wind_speed_ms + (b.wind_speed_ms - a.wind_speed_ms) * t,
    wind_dir_from_deg: a.wind_dir_from_deg + (b.wind_dir_from_deg - a.wind_dir_from_deg) * t,
    hs_m: a.hs_m + (b.hs_m - a.hs_m) * t,
    visibility_km: a.visibility_km + (b.visibility_km - a.visibility_km) * t,
    nearest_contact_nm:
      a.nearest_contact_nm == null || b.nearest_contact_nm == null
        ? null
        : a.nearest_contact_nm + (b.nearest_contact_nm - a.nearest_contact_nm) * t,
    active_alerts: b.active_alerts,
  });

  const tick = () => {
    if (!paused) {
      const now = performance.now();
      const elapsed = (now - startWall) * speed;
      simMs += elapsed;
      startWall = now;
    }
    const fix = fixAt(simMs);
    if (fix) {
      listeners.forEach((cb) => cb(fix));
      onChange?.(fix);
    }
    if (simMs >= (timeline[timelineLength - 1]?.sim_hours ?? 0) * 3600 * 1000) {
      pause();
    }
    if (!paused) raf = requestAnimationFrame(tick);
  };

  const subscribe = (cb: (fix: PositionFix) => void): (() => void) => {
    listeners.add(cb);
    const fix = fixAt(simMs);
    if (fix) cb(fix);
    return () => listeners.delete(cb);
  };

  const play = (): void => {
    if (paused) {
      paused = false;
      startWall = performance.now();
      raf = requestAnimationFrame(tick);
    }
  };

  const pause = (): void => {
    paused = true;
    if (raf !== null) {
      cancelAnimationFrame(raf);
      raf = null;
    }
  };

  const setSpeed = (s: number): void => {
    speed = s;
    if (!paused) {
      startWall = performance.now();
    }
  };

  const seek = (simHours: number): void => {
    simMs = simHours * 3600 * 1000;
    const fix = fixAt(simMs);
    if (fix) {
      listeners.forEach((cb) => cb(fix));
      onChange?.(fix);
    }
  };

  const now = (): PositionFix | null => fixAt(simMs);

  return {
    subscribe,
    now,
    get paused() {
      return paused;
    },
    play,
    pause,
    setSpeed,
    seek,
  } as unknown as PositionSource;
}
