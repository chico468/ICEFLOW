/**
 * EPSG:3031 - Antarctic Polar Stereographic, ported line for line from `src/core/geo.py`.
 *
 * WGS84 ellipsoid, true scale at 71 S, central meridian 0, origin at the South Pole,
 * +x toward 90 E and +y toward 0 E. Forward and inverse are exact inverses of each other,
 * which is what lets a click on the canvas be turned back into a coordinate the backend
 * will agree with.
 *
 * This is deliberately a hand port rather than a library call: proj4 and the tile-map
 * stacks would each add a dependency, and the whole point of the exercise is that the
 * client and the server compute the same projection from the same constants.
 */

// --- constants, mirroring src/core/constants.py ---
export const EARTH_RADIUS_KM = 6371.0088;
export const WGS84_A = 6378137.0;
export const WGS84_E = 0.08181919084262149;
export const EPSG3031_STD_PARALLEL_DEG = -71.0;
export const EPSG3031_CENTRAL_MERIDIAN_DEG = 0.0;
export const KM_PER_NM = 1.852;

const DEG = Math.PI / 180;
const PHI_C = Math.abs(EPSG3031_STD_PARALLEL_DEG) * DEG;
const LAM_0 = EPSG3031_CENTRAL_MERIDIAN_DEG * DEG;
const E = WGS84_E;
const E2 = E * E;

/** Isometric-latitude helper t(phi); phi is a POSITIVE (southern) latitude in radians. */
function tOf(phi: number): number {
  return (
    Math.tan(Math.PI / 4 - phi / 2) /
    Math.pow((1 - E * Math.sin(phi)) / (1 + E * Math.sin(phi)), E / 2)
  );
}

const M_C = Math.cos(PHI_C) / Math.sqrt(1 - E2 * Math.pow(Math.sin(PHI_C), 2));
const T_C = tOf(PHI_C);

export interface XY {
  x: number;
  y: number;
}

export interface LatLon {
  lat: number;
  lon: number;
}

/** WGS84 lat/lon in degrees (southern latitudes negative) to EPSG:3031 metres. */
export function toEpsg3031(lat: number, lon: number): XY {
  const phi = -lat * DEG; // positive southern latitude
  const lam = lon * DEG - LAM_0;
  if (phi >= Math.PI / 2 - 1e-12) return { x: 0, y: 0 };
  const rho = (WGS84_A * M_C * tOf(phi)) / T_C;
  return { x: rho * Math.sin(lam), y: rho * Math.cos(lam) };
}

/** EPSG:3031 metres back to WGS84 degrees. Exact inverse of toEpsg3031. */
export function fromEpsg3031(x: number, y: number): LatLon {
  const rho = Math.hypot(x, y);
  if (rho < 1e-9) return { lat: -90, lon: 0 };
  const t = (rho * T_C) / (WGS84_A * M_C);
  const chi = Math.PI / 2 - 2 * Math.atan(t);
  const e4 = E2 * E2;
  const e6 = e4 * E2;
  const e8 = e6 * E2;
  const phi =
    chi +
    (E2 / 2 + (5 * e4) / 24 + e6 / 12 + (13 * e8) / 360) * Math.sin(2 * chi) +
    ((7 * e4) / 48 + (29 * e6) / 240 + (811 * e8) / 11520) * Math.sin(4 * chi) +
    ((7 * e6) / 120 + (81 * e8) / 1120) * Math.sin(6 * chi) +
    ((4279 * e8) / 161280) * Math.sin(8 * chi);
  const lam = Math.atan2(x, y) + LAM_0;
  return { lat: -(phi / DEG), lon: normalizeLon(lam / DEG) };
}

export function normalizeLon(lon: number): number {
  let l = lon;
  while (l > 180) l -= 360;
  while (l < -180) l += 360;
  return l;
}

// ---------------------------------------------------------------- great-circle geodesy

/** Great-circle distance in nautical miles. Mirrors haversine_nm in geo.py. */
export function haversineNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const phi1 = lat1 * DEG;
  const phi2 = lat2 * DEG;
  const dPhi = (lat2 - lat1) * DEG;
  const dLam = (lon2 - lon1) * DEG;
  let a =
    Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2;
  a = Math.min(1, Math.max(0, a));
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return (EARTH_RADIUS_KM * c) / KM_PER_NM;
}

/** Initial true bearing in degrees from north. */
export function initialBearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const phi1 = lat1 * DEG;
  const phi2 = lat2 * DEG;
  const dLam = (lon2 - lon1) * DEG;
  const y = Math.sin(dLam) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLam);
  return (Math.atan2(y, x) / DEG + 360) % 360;
}

/** Spherical slerp between two coordinates, used to draw the great-circle reference track. */
export function greatCirclePath(
  lat1: number,
  lon1: number,
  lat2: number,
  lon2: number,
  n: number,
): LatLon[] {
  const phi1 = lat1 * DEG;
  const lam1 = lon1 * DEG;
  const phi2 = lat2 * DEG;
  const lam2 = lon2 * DEG;
  const d =
    2 *
    Math.asin(
      Math.min(
        1,
        Math.sqrt(
          Math.sin((phi2 - phi1) / 2) ** 2 +
            Math.cos(phi1) * Math.cos(phi2) * Math.sin((lam2 - lam1) / 2) ** 2,
        ),
      ),
    );
  const out: LatLon[] = [];
  if (d < 1e-12) return [{ lat: lat1, lon: lon1 }];
  for (let i = 0; i <= n; i += 1) {
    const f = i / n;
    const a = Math.sin((1 - f) * d) / Math.sin(d);
    const b = Math.sin(f * d) / Math.sin(d);
    const x = a * Math.cos(phi1) * Math.cos(lam1) + b * Math.cos(phi2) * Math.cos(lam2);
    const y = a * Math.cos(phi1) * Math.sin(lam1) + b * Math.cos(phi2) * Math.sin(lam2);
    const z = a * Math.sin(phi1) + b * Math.sin(phi2);
    out.push({
      lat: Math.atan2(z, Math.hypot(x, y)) / DEG,
      lon: Math.atan2(y, x) / DEG,
    });
  }
  return out;
}

/**
 * Local scale factor of the projection: how many projected metres one true metre becomes
 * at this latitude. Needed so an uncertainty radius quoted in kilometres draws at the
 * right size on a conformal projection whose scale grows away from 71 S.
 */
export function scaleFactorAt(lat: number): number {
  const phi = Math.abs(lat) * DEG;
  if (phi >= Math.PI / 2 - 1e-9) return T_C === 0 ? 1 : (M_C * 2) / T_C;
  const m = Math.cos(phi) / Math.sqrt(1 - E2 * Math.pow(Math.sin(phi), 2));
  const rho = (WGS84_A * M_C * tOf(phi)) / T_C;
  return rho / (WGS84_A * m);
}
