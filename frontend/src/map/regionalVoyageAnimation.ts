export interface VesselPose {
  latitude: number;
  longitude: number;
  heading: number;
}

export interface RoutePoint {
  latitude: number;
  longitude: number;
}

/** Compute the initial true bearing in degrees from north between two points. */
export function initialBearingDeg(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRadians = Math.PI / 180;
  const toDegrees = 180 / Math.PI;
  const phi1 = lat1 * toRadians;
  const phi2 = lat2 * toRadians;
  const dLam = (lon2 - lon1) * toRadians;
  const y = Math.sin(dLam) * Math.cos(phi2);
  const x = Math.cos(phi1) * Math.sin(phi2) - Math.sin(phi1) * Math.cos(phi2) * Math.cos(dLam);
  return ((Math.atan2(y, x) * toDegrees) % 360 + 360) % 360;
}

/** Great-circle distance in nautical miles between two points. */
export function haversineNm(lat1: number, lon1: number, lat2: number, lon2: number): number {
  const toRadians = Math.PI / 180;
  const EARTH_RADIUS_KM = 6371.0088;
  const KM_PER_NM = 1.852;
  const phi1 = lat1 * toRadians;
  const phi2 = lat2 * toRadians;
  const dPhi = (lat2 - lat1) * toRadians;
  const dLam = (lon2 - lon1) * toRadians;
  let a = Math.sin(dPhi / 2) ** 2 + Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2;
  a = Math.min(1, Math.max(0, a));
  const c = 2 * Math.atan2(Math.sqrt(a), Math.sqrt(1 - a));
  return (EARTH_RADIUS_KM * c) / KM_PER_NM;
}

/** Normalize longitude to [-180, 180]. */
function normalizeLongitude(lon: number): number {
  let result = ((lon % 360) + 360) % 360;
  if (result > 180) result -= 360;
  return result;
}

/** Spherical linear interpolation between two points along great circle. */
function slerpGreatCircle(lat1: number, lon1: number, lat2: number, lon2: number, t: number): { lat: number; lon: number } {
  const toRadians = Math.PI / 180;
  const toDegrees = 180 / Math.PI;
  const phi1 = lat1 * toRadians;
  const lam1 = lon1 * toRadians;
  const phi2 = lat2 * toRadians;
  let lam2 = lon2 * toRadians;
  
  // Handle longitude wrapping
  let dLam = lam2 - lam1;
  if (dLam > Math.PI) dLam -= 2 * Math.PI;
  if (dLam < -Math.PI) dLam += 2 * Math.PI;
  lam2 = lam1 + dLam;
  
  const d = 2 * Math.asin(
    Math.min(
      1,
      Math.sqrt(
        Math.sin((phi2 - phi1) / 2) ** 2 +
          Math.cos(phi1) * Math.cos(phi2) * Math.sin(dLam / 2) ** 2,
      ),
    ),
  );
  if (d < 1e-12) {
    return { lat: lat1 + (lat2 - lat1) * t, lon: normalizeLongitude(lon1 + ((lon2 - lon1 + 540) % 360) - 180) * t + normalizeLongitude(lon1) };
  }
  const a = Math.sin((1 - t) * d) / Math.sin(d);
  const b = Math.sin(t * d) / Math.sin(d);
  const x = a * Math.cos(phi1) * Math.cos(lam1) + b * Math.cos(phi2) * Math.cos(lam2);
  const y = a * Math.cos(phi1) * Math.sin(lam1) + b * Math.cos(phi2) * Math.sin(lam2);
  const z = a * Math.sin(phi1) + b * Math.sin(phi2);
  return {
    lat: Math.atan2(z, Math.hypot(x, y)) * toDegrees,
    lon: normalizeLongitude(Math.atan2(y, x) * toDegrees),
  };
}

/** Interpolate position and heading along a route geometry by distance. */
export function interpolateAlongRoute(
  route: RoutePoint[],
  distanceProgress: number, // 0 to 1
): VesselPose | null {
  if (!route || route.length === 0) return null;
  if (route.length === 1) {
    return { latitude: route[0].latitude, longitude: route[0].longitude, heading: 0 };
  }
  
  const t = Math.max(0, Math.min(1, distanceProgress));
  
  // Calculate cumulative distances along the whole route
  const distances: number[] = [0];
  let totalDistance = 0;
  for (let i = 1; i < route.length; i++) {
    const d = haversineNm(route[i - 1].latitude, route[i - 1].longitude, route[i].latitude, route[i].longitude);
    totalDistance += d;
    distances.push(totalDistance);
  }
  
  if (totalDistance === 0) {
    const heading = initialBearingDeg(route[0].latitude, route[0].longitude, route[1].latitude, route[1].longitude);
    return { latitude: route[0].latitude, longitude: route[0].longitude, heading };
  }
  
  // Try to be compatible with different interpretations
  const targetDistance = t * totalDistance;
  
  // Find segment
  let segmentIndex = 0;
  for (let i = 1; i < distances.length; i++) {
    if (targetDistance <= distances[i] + 1e-9) {
      segmentIndex = i - 1;
      break;
    }
    segmentIndex = i - 1;
  }
  if (segmentIndex >= route.length - 1) {
    segmentIndex = route.length - 2;
  }
  
  const segmentStart = distances[segmentIndex];
  const segmentEnd = distances[segmentIndex + 1];
  const segmentLength = segmentEnd - segmentStart;
  const st = segmentLength === 0 ? 0 : Math.max(0, Math.min(1, (targetDistance - segmentStart) / segmentLength));
  
  const p1 = route[segmentIndex];
  const p2 = route[segmentIndex + 1];
  const pos = slerpGreatCircle(p1.latitude, p1.longitude, p2.latitude, p2.longitude, st);
  const heading = initialBearingDeg(p1.latitude, p1.longitude, p2.latitude, p2.longitude);
  
  return {
    latitude: pos.lat,
    longitude: pos.lon,
    heading,
  };
}

/** Interpolate geographic positions on a great-circle arc, including across ±180°. */
export function interpolateVesselPose(from: VesselPose, to: VesselPose, progress: number): VesselPose {
  const t = Math.max(0, Math.min(1, progress));
  const toRadians = Math.PI / 180;
  const toDegrees = 180 / Math.PI;
  const fromLat = from.latitude * toRadians;
  const fromLon = from.longitude * toRadians;
  const toLat = to.latitude * toRadians;
  const toLon = to.longitude * toRadians;
  const fromVector = [
    Math.cos(fromLat) * Math.cos(fromLon),
    Math.cos(fromLat) * Math.sin(fromLon),
    Math.sin(fromLat),
  ];
  const toVector = [
    Math.cos(toLat) * Math.cos(toLon),
    Math.cos(toLat) * Math.sin(toLon),
    Math.sin(toLat),
  ];
  const dot = Math.min(1, Math.max(-1, fromVector[0] * toVector[0] + fromVector[1] * toVector[1] + fromVector[2] * toVector[2]));
  const arc = Math.acos(dot);
  let latitude: number;
  let longitude: number;
  if (arc < 1e-8) {
    latitude = from.latitude + (to.latitude - from.latitude) * t;
    const longitudeDelta = ((to.longitude - from.longitude + 540) % 360) - 180;
    longitude = ((from.longitude + longitudeDelta * t + 540) % 360) - 180;
  } else if (Math.PI - arc < 1e-6) {
    // Antipodal points have no unique great circle. This fallback chooses a stable short
    // longitude arc while keeping latitude bounded for the rare degenerate segment.
    latitude = from.latitude + (to.latitude - from.latitude) * t;
    const longitudeDelta = ((to.longitude - from.longitude + 540) % 360) - 180;
    longitude = ((from.longitude + longitudeDelta * t + 540) % 360) - 180;
  } else {
    const sinArc = Math.sin(arc);
    const fromWeight = Math.sin((1 - t) * arc) / sinArc;
    const toWeight = Math.sin(t * arc) / sinArc;
    const x = fromWeight * fromVector[0] + toWeight * toVector[0];
    const y = fromWeight * fromVector[1] + toWeight * toVector[1];
    const z = fromWeight * fromVector[2] + toWeight * toVector[2];
    latitude = Math.atan2(z, Math.hypot(x, y)) * toDegrees;
    longitude = Math.atan2(y, x) * toDegrees;
  }
  const headingDelta = ((to.heading - from.heading + 540) % 360) - 180;
  return {
    latitude,
    longitude,
    heading: ((from.heading + headingDelta * t + 360) % 360 + 360) % 360,
  };
}
