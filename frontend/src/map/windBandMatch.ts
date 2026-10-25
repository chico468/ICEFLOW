/** Wind band matching for the Mapbox GFS raster-array particle layer. */

export interface WindBandMatch {
  band: string | null;
  exact: boolean;
  offsetHours: number | null;
  reason: string | null;
}

export function resolveWindBand(
  referenceTimeUtc: string | null,
  bands: string[],
  maxOffsetHours: number = 12,
): WindBandMatch {
  if (!referenceTimeUtc) {
    return { band: null, exact: false, offsetHours: null, reason: 'No reference time supplied.' };
  }
  const refMs = Date.parse(referenceTimeUtc);
  if (!Number.isFinite(refMs)) {
    return { band: null, exact: false, offsetHours: null, reason: 'Reference time is not a valid ISO-8601 timestamp.' };
  }
  if (!Array.isArray(bands) || bands.length === 0) {
    return { band: null, exact: false, offsetHours: null, reason: 'No wind bands advertised by the source.' };
  }

  const parsed: { band: string; ms: number }[] = [];
  for (const band of bands) {
    const ms = Date.parse(band);
    if (Number.isFinite(ms)) parsed.push({ band, ms });
  }
  if (parsed.length === 0) {
    return { band: null, exact: false, offsetHours: null, reason: 'No wind bands carry a parseable timestamp.' };
  }

  const exact = parsed.find((item) => item.ms === refMs);
  if (exact) {
    return { band: exact.band, exact: true, offsetHours: 0, reason: null };
  }

  let best = parsed[0];
  for (const item of parsed) {
    if (Math.abs(item.ms - refMs) < Math.abs(best.ms - refMs)) best = item;
  }
  const offsetHours = (best.ms - refMs) / 3_600_000;
  if (Math.abs(offsetHours) > maxOffsetHours) {
    return {
      band: null,
      exact: false,
      offsetHours: null,
      reason: `Closest available band is ${offsetHours.toFixed(1)}h from the reference time, beyond the ${maxOffsetHours}h tolerance.`,
    };
  }
  return {
    band: best.band,
    exact: false,
    offsetHours: Number(offsetHours.toFixed(3)),
    reason: `No exact band; using the closest available band, ${Math.abs(offsetHours).toFixed(1)}h ${offsetHours < 0 ? 'before' : 'after'} the reference time.`,
  };
}