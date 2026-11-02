/**
 * SceneEnvironment: the slice of the voyage environment the 3D scene consumes.
 *
 * Every field is optional. When a field is absent the corresponding effect is
 * OFF and the HUD reports "no data" for it — per the honesty contract, we never
 * fabricate weather, ice or berg data that the payload does not contain.
 *
 * All angles in degrees. Distances in metres unless noted. Times in seconds.
 */
export interface SceneEnvironment {
  /** Significant wave height (m), from sig_wave_height_m. */
  waveHeightM?: number | null;
  /** Wave period (s), from tp. Absent → default 8 s. */
  wavePeriodS?: number | null;
  /** Wave direction the waves come FROM (degrees true), from wave_dir. */
  waveDirDeg?: number | null;
  /** Wind speed (m/s), from wind_speed_ms. */
  windSpeedMs?: number | null;
  /** Wind direction the wind comes FROM (degrees true), from wind_dir_from_deg. */
  windDirDeg?: number | null;
  /** Snowfall rate (mm/hr), from snowfall. Absent → snow off. */
  snowfallMmPerHr?: number | null;
  /** Total cloud cover (0..1), from total_cloud_cover. Absent → cloud off. */
  totalCloudCover?: number | null;
  /** Visibility (km), from visibility_km. Absent → fog off. */
  visibilityKm?: number | null;
  /** Sun azimuth (degrees true), from sun_azimuth_deg. */
  sunAzimuthDeg?: number | null;
  /** Sun elevation (degrees), from sun_elevation_deg. */
  sunElevationDeg?: number | null;
  /** Ice layer product name, from provenance product. */
  iceProduct?: string | null;
  /** Ice layer valid time (ISO), from provenance valid_time. */
  iceValidTime?: string | null;
  /** Named observed bergs, each { id, distanceNm, bearingDeg, lengthM, widthM }. */
  nearbyBergs?: Array<{ id: string; distanceNm: number; bearingDeg: number; lengthM: number; widthM: number }> | null;
  /** True when any environment layer is simulated (drives the SIMULATED banner). */
  simulated?: boolean;
}

/** Metres per nautical mile. */
export const NM_M = 1852;

/**
 * Response-amplitude-operator ship motion.
 *
 * Simple RAO: roll is maximal on beam seas (wave 90° off the heading), pitch is
 * maximal on head/following seas (wave 0°/180°), heave is driven by wave height
 * regardless of direction. Every amplitude is a positive factor times `hsM`, so
 * motion amplitude is monotonic in Hs.
 *
 * Returns { roll deg, pitch deg, heave m }.
 */
export function raoMotion({
  hsM,
  wavePeriodS,
  waveDirDeg,
  headingDeg,
}: {
  hsM: number;
  wavePeriodS: number;
  waveDirDeg: number;
  headingDeg: number;
}): { roll: number; pitch: number; heave: number } {
  const hs = Math.max(0, hsM ?? 0);
  const period = Math.max(1, wavePeriodS ?? 8);
  const rel = ((waveDirDeg ?? 0 - headingDeg ?? 0) + 540) % 360 - 180; // -180..180
  const relRad = (rel * Math.PI) / 180;
  // Roll max at beam (|rel|=90), pitch max at head/following (rel=0/180).
  const rollFactor = Math.abs(Math.sin(relRad));
  const pitchFactor = Math.abs(Math.cos(relRad));
  const periodFactor = Math.min(period / 10, 1.5);
  return {
    roll: hs * rollFactor * 0.6 * periodFactor,
    pitch: hs * pitchFactor * 0.5 * periodFactor,
    heave: hs * 0.4 * periodFactor,
  };
}
