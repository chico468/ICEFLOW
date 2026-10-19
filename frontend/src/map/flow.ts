/**
 * Flow-field sampling and particle advection, with no DOM and no imports.
 *
 * WHAT IS ANIMATED
 * Only vectors that exist in a field the service returned. A particle moves with the field's own
 * (u, v), sampled bilinearly at its position. Nothing is invented between grid nodes beyond that
 * interpolation, and a particle that leaves the grid is respawned rather than extrapolated.
 *
 * WHAT IS NOT REAL ABOUT THE MOTION
 * Speed on screen is proportional to field speed *within a layer*, but it is scaled so that slow
 * currents are visible at all (see FLOW_KINDS.pxPerSecPerMs). The motion is a depiction of direction
 * and relative strength, not a real-time drift. The legend says so, and the colour ramp, which is on
 * the true m/s scale, carries the actual magnitude.
 *
 * DIRECTION ACCURACY
 * A particle is advanced by stepping along the *geographic* direction of the vector and projecting
 * that step, never by adding (u, v) to screen coordinates. On the polar chart "east" is not "right",
 * and doing it the naive way would draw every vector rotated by the local meridian convergence.
 */

export type RGB = [number, number, number];

export interface FlowGrid {
  /** Ascending latitudes, degrees. */
  lats: number[];
  /** Ascending longitudes, degrees. */
  lons: number[];
  /** [lat][lon], m/s, east component. */
  u: number[][];
  /** [lat][lon], m/s, north component. */
  v: number[][];
  /** [lat][lon]; true where the field is not defined as ocean. Optional. */
  land?: boolean[][];
}

/** Build a grid, or return null when the arrays are not a usable regular grid. */
export function makeFlowGrid(
  lats: number[],
  lons: number[],
  u: number[][],
  v: number[][],
  landFromWaveHeight?: number[][],
): FlowGrid | null {
  if (lats.length < 2 || lons.length < 2) return null;
  if (u.length !== lats.length || v.length !== lats.length) return null;
  for (let i = 1; i < lats.length; i += 1) if (!(lats[i] > lats[i - 1])) return null;
  for (let j = 1; j < lons.length; j += 1) if (!(lons[j] > lons[j - 1])) return null;
  for (let i = 0; i < lats.length; i += 1) {
    if (!u[i] || !v[i] || u[i].length !== lons.length || v[i].length !== lons.length) return null;
  }
  const land = landFromWaveHeight
    ? landFromWaveHeight.map((row) => row.map((hs) => hs === 0))
    : undefined;
  return { lats, lons, u, v, land };
}

function bracket(axis: number[], x: number): number {
  // Index i such that axis[i] <= x <= axis[i+1]; -1 when x is outside the axis.
  if (x < axis[0] || x > axis[axis.length - 1]) return -1;
  let lo = 0;
  let hi = axis.length - 1;
  while (hi - lo > 1) {
    const mid = (lo + hi) >> 1;
    if (axis[mid] <= x) lo = mid;
    else hi = mid;
  }
  return lo;
}

/** Is the point inside the grid's extent? */
export function insideGrid(g: FlowGrid, lat: number, lon: number): boolean {
  return bracket(g.lats, lat) >= 0 && bracket(g.lons, lon) >= 0;
}

/**
 * Bilinear sample of (u, v) in m/s into `out`. Returns false, leaving `out` untouched, when the point
 * is outside the grid or any of the four surrounding nodes is not a finite number.
 */
export function sampleFlow(g: FlowGrid, lat: number, lon: number, out: [number, number]): boolean {
  const i = bracket(g.lats, lat);
  const j = bracket(g.lons, lon);
  if (i < 0 || j < 0) return false;
  const ty = (lat - g.lats[i]) / (g.lats[i + 1] - g.lats[i]);
  const tx = (lon - g.lons[j]) / (g.lons[j + 1] - g.lons[j]);
  const u00 = g.u[i][j];
  const u01 = g.u[i][j + 1];
  const u10 = g.u[i + 1][j];
  const u11 = g.u[i + 1][j + 1];
  const v00 = g.v[i][j];
  const v01 = g.v[i][j + 1];
  const v10 = g.v[i + 1][j];
  const v11 = g.v[i + 1][j + 1];
  if (
    !Number.isFinite(u00 + u01 + u10 + u11 + v00 + v01 + v10 + v11)
  ) {
    return false;
  }
  out[0] = (u00 * (1 - tx) + u01 * tx) * (1 - ty) + (u10 * (1 - tx) + u11 * tx) * ty;
  out[1] = (v00 * (1 - tx) + v01 * tx) * (1 - ty) + (v10 * (1 - tx) + v11 * tx) * ty;
  return true;
}

/** Nearest-node land flag. False when the grid carries no land information. */
export function isLandAt(g: FlowGrid, lat: number, lon: number): boolean {
  if (!g.land) return false;
  const i = bracket(g.lats, lat);
  const j = bracket(g.lons, lon);
  if (i < 0 || j < 0) return false;
  const ni = lat - g.lats[i] > g.lats[i + 1] - lat ? i + 1 : i;
  const nj = lon - g.lons[j] > g.lons[j + 1] - lon ? j + 1 : j;
  return g.land[ni][nj];
}

export type Project = (lat: number, lon: number) => { x: number; y: number };

/**
 * Move a point `targetPx` pixels along the screen image of the geographic direction (u, v).
 * Returns null for a calm or degenerate vector.
 */
export function advanceStep(
  project: Project,
  lat: number,
  lon: number,
  u: number,
  v: number,
  targetPx: number,
  probeDeg = 0.05,
  /** The screen position of (lat, lon) when the caller already has it, saving one projection. */
  knownP0?: { x: number; y: number },
): { lat: number; lon: number } | null {
  const speed = Math.hypot(u, v);
  if (!(speed > 1e-6) || !(targetPx > 0)) return null;
  const cosLat = Math.max(0.02, Math.cos((lat * Math.PI) / 180));
  const dLat = (v / speed) * probeDeg;
  const dLon = ((u / speed) * probeDeg) / cosLat;
  const p0 = knownP0 ?? project(lat, lon);
  const p1 = project(lat + dLat, lon + dLon);
  const screenLen = Math.hypot(p1.x - p0.x, p1.y - p0.y);
  if (!(screenLen > 1e-9)) return null;
  const k = targetPx / screenLen;
  const nextLat = lat + dLat * k;
  if (Math.abs(nextLat) > 89.9) return null;
  return { lat: nextLat, lon: lon + dLon * k };
}

// ------------------------------------------------------------------------------------------ kinds

export type FlowKind = 'wind' | 'current';

/** How flow is drawn: moving particles, or static arrows (the dependable fallback, and the reduced-motion default). */
export type FlowStyle = 'animated' | 'arrows';

export interface FlowKindSpec {
  kind: FlowKind;
  label: string;
  /** Upper end of the colour ramp, m/s. Speeds above it use the darkest colour. */
  maxSpeed: number;
  /** Visual scale: screen pixels per second of particle motion, per m/s of field speed. */
  pxPerSecPerMs: number;
  trailLength: number;
  lineWidth: number;
  /** Light to dark. */
  ramp: RGB[];
}

export const FLOW_KINDS: Record<FlowKind, FlowKindSpec> = {
  wind: {
    kind: 'wind',
    label: 'Wind at 10 m',
    maxSpeed: 25,
    // ~50 px/s at the median simulated wind (7 m/s), ~175 px/s at the fastest: clearly moving, never frantic.
    pxPerSecPerMs: 7,
    trailLength: 10,
    lineWidth: 1,
    ramp: [
      [148, 163, 184],
      [100, 116, 139],
      [71, 85, 105],
      [51, 65, 85],
      [30, 41, 59],
      [15, 23, 42],
    ],
  },
  current: {
    kind: 'current',
    label: 'Surface current',
    maxSpeed: 0.8,
    // Currents are ~50x slower than wind, so they need a much larger visual scale to be seen at all:
    // ~50 px/s at the median simulated current (0.15 m/s). The legend says the two scales differ.
    pxPerSecPerMs: 320,
    trailLength: 11,
    lineWidth: 1.3,
    ramp: [
      [103, 232, 249],
      [34, 211, 238],
      [8, 145, 178],
      [14, 116, 144],
      [21, 94, 117],
      [22, 78, 99],
    ],
  },
};

export function speedBucket(speed: number, maxSpeed: number, buckets: number): number {
  if (!(speed > 0)) return 0;
  return Math.min(buckets - 1, Math.floor((speed / maxSpeed) * buckets));
}

// ------------------------------------------------------------------------------------------ rng

/** Small deterministic generator, so a seeded demonstration reproduces the same particle layout. */
export function mulberry32(seed: number): () => number {
  let a = seed >>> 0;
  return () => {
    a = (a + 0x6d2b79f5) >>> 0;
    let t = a;
    t = Math.imul(t ^ (t >>> 15), t | 1);
    t ^= t + Math.imul(t ^ (t >>> 7), t | 61);
    return ((t ^ (t >>> 14)) >>> 0) / 4294967296;
  };
}

/** How many particles to run for a canvas of this size: sparse enough to read, cheap enough to run. */
export function particleCountFor(widthPx: number, heightPx: number): number {
  return Math.max(200, Math.min(700, Math.round((widthPx * heightPx) / 3200)));
}

/**
 * How much of a particle's trail to show: all of it for most of its life, then a shrinking tail as it nears
 * its end, so particles dissolve instead of vanishing. Young particles are already short because their
 * trail has not had time to grow. Returns 0 to 1.
 */
export function lifeFraction(age: number, maxAge: number, fadeFrames = 14): number {
  const left = maxAge - age;
  if (!(left > 0)) return 0;
  return Math.min(1, left / fadeFrames);
}

// ------------------------------------------------------------------------------------ coverage

/**
 * What fraction of the screen lies inside the grid's extent, sampled on an n x n lattice. 0 means the whole
 * visible chart is outside the field (nothing can be drawn and the user should be told why).
 */
export function viewCoverage(
  g: FlowGrid,
  screenToLatLon: (x: number, y: number) => { lat: number; lon: number },
  widthPx: number,
  heightPx: number,
  n = 7,
): number {
  let inside = 0;
  for (let i = 0; i < n; i += 1) {
    for (let j = 0; j < n; j += 1) {
      const ll = screenToLatLon(((i + 0.5) / n) * widthPx, ((j + 0.5) / n) * heightPx);
      if (Number.isFinite(ll.lat) && Number.isFinite(ll.lon) && insideGrid(g, ll.lat, ll.lon)) inside += 1;
    }
  }
  return inside / (n * n);
}

/** Plain-language extent of a grid, for the "outside the field" notice. */
export function coverageText(g: FlowGrid): string {
  const fmtLat = (v: number): string => `${Math.abs(Math.round(v))}°${v < 0 ? 'S' : 'N'}`;
  const lonSpan = g.lons[g.lons.length - 1] - g.lons[0];
  const lon = lonSpan >= 359 ? 'all longitudes' : `${Math.round(g.lons[0])}° to ${Math.round(g.lons[g.lons.length - 1])}° longitude`;
  return `${fmtLat(g.lats[0])} to ${fmtLat(g.lats[g.lats.length - 1])}, ${lon}`;
}

// ------------------------------------------------------------------------------------ static vectors

/** Arrow length in pixels, proportional to speed between a floor (so calm cells stay visible) and a cap. */
export function arrowLength(speed: number, maxSpeed: number, minPx = 9, maxPx = 28): number {
  const t = Math.min(1, Math.max(0, speed / maxSpeed));
  return minPx + t * (maxPx - minPx);
}

/**
 * A static arrow centred on (lat, lon): its screen endpoints are the images of the GEOGRAPHIC direction of
 * (u, v), so on the polar chart it points the same way an advected particle would. Null for a calm vector.
 */
export function vectorArrow(
  project: Project,
  lat: number,
  lon: number,
  u: number,
  v: number,
  lengthPx: number,
): { x0: number; y0: number; x1: number; y1: number } | null {
  const head = advanceStep(project, lat, lon, u, v, lengthPx / 2);
  const tail = advanceStep(project, lat, lon, -u, -v, lengthPx / 2);
  if (!head || !tail) return null;
  const a = project(tail.lat, tail.lon);
  const b = project(head.lat, head.lon);
  return { x0: a.x, y0: a.y, x1: b.x, y1: b.y };
}

/** Screen positions of a regular lattice (flat x, y pairs), optionally offset so two layers do not collide. */
export function arrowLattice(widthPx: number, heightPx: number, spacingPx: number, offsetPx = 0): number[] {
  const out: number[] = [];
  for (let y = spacingPx / 2 + offsetPx; y < heightPx; y += spacingPx) {
    for (let x = spacingPx / 2 + offsetPx; x < widthPx; x += spacingPx) out.push(x, y);
  }
  return out;
}

// -------------------------------------------------------------------------------------- particles

export interface StepOptions {
  project: Project;
  /** A random on-screen geographic point inside the field, or null when none was found. */
  spawn: () => { lat: number; lon: number } | null;
  widthPx: number;
  heightPx: number;
  /** Respawn a particle that has moved this far outside the canvas. */
  marginPx: number;
  dtSec: number;
  /** True when the viewport changed since the last step: screen-space trails are rebuilt from geography. */
  reproject: boolean;
}

export class ParticleField {
  readonly count: number;
  readonly trailLength: number;
  readonly lat: Float64Array;
  readonly lon: Float64Array;
  readonly speed: Float32Array;
  readonly age: Int32Array;
  readonly maxAge: Int32Array;
  readonly alive: Uint8Array;
  /** Newest first: index 0 is the current position. */
  readonly trailLat: Float32Array;
  readonly trailLon: Float32Array;
  readonly trailCount: Uint8Array;
  /** Screen-space copy of the trails, valid as of the last step. Newest first, like the geographic trail. */
  readonly trailX: Float32Array;
  readonly trailY: Float32Array;

  private grid: FlowGrid | null = null;
  private readonly spec: FlowKindSpec;
  private readonly rng: () => number;
  private readonly scratch: [number, number] = [0, 0];

  constructor(spec: FlowKindSpec, count: number, seed = 1) {
    this.spec = spec;
    this.count = count;
    this.trailLength = spec.trailLength;
    this.rng = mulberry32(seed);
    this.lat = new Float64Array(count);
    this.lon = new Float64Array(count);
    this.speed = new Float32Array(count);
    this.age = new Int32Array(count);
    this.maxAge = new Int32Array(count);
    this.alive = new Uint8Array(count);
    this.trailLat = new Float32Array(count * spec.trailLength);
    this.trailLon = new Float32Array(count * spec.trailLength);
    this.trailCount = new Uint8Array(count);
    this.trailX = new Float32Array(count * spec.trailLength);
    this.trailY = new Float32Array(count * spec.trailLength);
  }

  setGrid(grid: FlowGrid | null): void {
    this.grid = grid;
    this.alive.fill(0);
    this.trailCount.fill(0);
  }

  get hasGrid(): boolean {
    return this.grid !== null;
  }

  random(): number {
    return this.rng();
  }

  private place(i: number, lat: number, lon: number, project: Project): void {
    this.lat[i] = lat;
    this.lon[i] = lon;
    this.alive[i] = 1;
    this.maxAge[i] = 70 + Math.floor(this.rng() * 90);
    // Desynchronise ages so the whole field does not respawn on the same frame.
    this.age[i] = Math.floor(this.rng() * this.maxAge[i] * 0.6);
    this.trailLat[i * this.trailLength] = lat;
    this.trailLon[i * this.trailLength] = lon;
    const sp = project(lat, lon);
    this.trailX[i * this.trailLength] = sp.x;
    this.trailY[i * this.trailLength] = sp.y;
    this.trailCount[i] = 1;
  }

  private kill(i: number): void {
    this.alive[i] = 0;
    this.trailCount[i] = 0;
  }

  /** Advance every particle one frame. */
  step(o: StepOptions): void {
    const g = this.grid;
    if (!g) return;
    const dt = Math.min(0.05, Math.max(0, o.dtSec));
    const sample = this.scratch;
    const K = this.trailLength;

    if (o.reproject) {
      for (let i = 0; i < this.count; i += 1) {
        if (!this.alive[i]) continue;
        const base = i * K;
        for (let k = 0; k < this.trailCount[i]; k += 1) {
          const sp = o.project(this.trailLat[base + k], this.trailLon[base + k]);
          this.trailX[base + k] = sp.x;
          this.trailY[base + k] = sp.y;
        }
      }
    }

    for (let i = 0; i < this.count; i += 1) {
      if (!this.alive[i]) {
        const s = o.spawn();
        if (!s || !sampleFlow(g, s.lat, s.lon, sample)) continue;
        if (this.spec.kind === 'current' && isLandAt(g, s.lat, s.lon)) continue;
        this.place(i, s.lat, s.lon, o.project);
        continue;
      }

      this.age[i] += 1;
      if (this.age[i] > this.maxAge[i]) {
        this.kill(i);
        continue;
      }
      if (!sampleFlow(g, this.lat[i], this.lon[i], sample)) {
        this.kill(i);
        continue;
      }
      if (this.spec.kind === 'current' && isLandAt(g, this.lat[i], this.lon[i])) {
        this.kill(i);
        continue;
      }
      const speed = Math.hypot(sample[0], sample[1]);
      this.speed[i] = speed;
      const headBase = i * K;
      const next = advanceStep(
        o.project,
        this.lat[i],
        this.lon[i],
        sample[0],
        sample[1],
        speed * this.spec.pxPerSecPerMs * dt,
        0.05,
        { x: this.trailX[headBase], y: this.trailY[headBase] },
      );
      if (!next || !insideGrid(g, next.lat, next.lon)) {
        this.kill(i);
        continue;
      }
      const sp = o.project(next.lat, next.lon);
      if (sp.x < -o.marginPx || sp.x > o.widthPx + o.marginPx || sp.y < -o.marginPx || sp.y > o.heightPx + o.marginPx) {
        this.kill(i);
        continue;
      }

      this.lat[i] = next.lat;
      this.lon[i] = next.lon;
      const base = i * K;
      const have = Math.min(this.trailCount[i], K - 1);
      for (let k = have; k >= 1; k -= 1) {
        this.trailLat[base + k] = this.trailLat[base + k - 1];
        this.trailLon[base + k] = this.trailLon[base + k - 1];
        this.trailX[base + k] = this.trailX[base + k - 1];
        this.trailY[base + k] = this.trailY[base + k - 1];
      }
      this.trailLat[base] = next.lat;
      this.trailLon[base] = next.lon;
      this.trailX[base] = sp.x;
      this.trailY[base] = sp.y;
      this.trailCount[i] = have + 1;
    }
  }
}
