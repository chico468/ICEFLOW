/**
 * TimelineSource: a source of timestamped position / environment samples for the sim clock.
 *
 * Two implementations:
 *   RecordedTimelineSource — the golden fixture, labelled "Recorded replay - real data,
 *     departure 2022-01-15". Never claims to be live.
 *   LiveTimelineSource — GET /api/v1/voyage/{id}/timeline. A live failure shows an error;
 *     it never silently swaps to the recording.
 */
import type { ProvenanceLike } from './provenance.ts';
import { normalizeProvenance } from './provenance.ts';

export interface TimelinePoint {
  index: number;
  t_utc: string;
  sim_hours: number;
  lat: number;
  lon: number;
  sog_kn: number;
  cog: number;
  heading: number;
  ice_conc: number;
  ice_thick_m: number;
  wind_speed_ms: number;
  wind_dir_from_deg: number;
  hs_m: number;
  visibility_km: number;
  nearest_contact_nm: number | null;
  active_alerts: string[];
  /** Provenance for each variable, in the fixture's {kind, source, product, valid_time, age_hours} shape. */
  provenance_by_variable: Record<string, ProvenanceLike>;
}

export interface TimelineSource {
  readonly kind: 'recorded' | 'live';
  readonly label: string;
  readonly error: string | null;
  getTimeline(voyageId?: string): Promise<TimelinePoint[]>;
}

const FIXTURE_PATH = new URL('../../e2e/fixtures/golden-voyage-timeline.json', import.meta.url).href;

async function loadFixture(): Promise<{ steps: Array<Record<string, unknown>> }> {
  const res = await fetch(FIXTURE_PATH);
  if (!res.ok) throw new Error(`Fixture fetch failed: ${res.status}`);
  return res.json();
}

export class RecordedTimelineSource implements TimelineSource {
  readonly kind = 'recorded' as const;
  readonly label = 'Recorded replay — real data, departure 2022-01-15';
  readonly error = null;

  async getTimeline(): Promise<TimelinePoint[]> {
    const data = await loadFixture();
    const steps = data.steps as Array<Record<string, unknown>>;
    return steps.map((s, i) => ({
      index: i,
      t_utc: String(s['t_utc']),
      sim_hours: Number((s['sim_hours'] ?? i * 0.5)),
      lat: Number(s['lat']),
      lon: Number(s['lon']),
      sog_kn: Number(s['sog_kn'] ?? 0),
      cog: Number(s['cog'] ?? 0),
      heading: Number(s['heading'] ?? 0),
      ice_conc: Number(s['ice_conc'] ?? 0),
      ice_thick_m: Number(s['ice_thickness_m'] ?? 0),
      wind_speed_ms: Number(s['wind_speed_ms'] ?? 0),
      wind_dir_from_deg: Number(s['wind_dir_from_deg'] ?? 0),
      hs_m: Number(s['hs'] ?? 0),
      visibility_km: Number(s['visibility_km'] ?? 10),
      nearest_contact_nm:
        s['nearby_bergs'] == null || s['nearby_bergs'] === undefined
          ? null
          : Number((s['nearby_bergs'] as Array<{ dist_nm: number }>)[0]?.dist_nm ?? null),
      active_alerts: Array.isArray(s['alerts']) ? (s['alerts'] as string[]) : [],
      provenance_by_variable: (s['provenance_by_variable'] as Record<string, ProvenanceLike>) ?? {},
    }));
  }
}

export class LiveTimelineSource implements TimelineSource {
  readonly kind = 'live' as const;
  readonly label = 'Live voyage timeline';
  private _error: string | null = null;

  get error(): string | null {
    return this._error;
  }

  async getTimeline(voyageId?: string): Promise<TimelinePoint[]> {
    this._error = null;
    if (!voyageId) {
      this._error = 'No voyage id';
      return [];
    }
    try {
      const res = await fetch(`/api/v1/voyage/${encodeURIComponent(voyageId)}/timeline`);
      if (!res.ok) {
        this._error = `Timeline endpoint unavailable (HTTP ${res.status})`;
        return [];
      }
      const data = await res.json();
      const steps = Array.isArray(data) ? data : data.steps ?? [];
      return steps.map((s: Record<string, unknown>, i: number) => ({
        index: i,
        t_utc: String(s['t_utc'] ?? s['timestamp_iso'] ?? ''),
        sim_hours: Number(s['sim_hours'] ?? i * 0.5),
        lat: Number(s['lat'] ?? s['latitude'] ?? 0),
        lon: Number(s['lon'] ?? s['longitude'] ?? 0),
        sog_kn: Number(s['sog_kn'] ?? s['speed_knots'] ?? 0),
        cog: Number(s['cog'] ?? s['heading_deg'] ?? 0),
        heading: Number(s['heading'] ?? s['heading_deg'] ?? 0),
        ice_conc: Number(s['ice_conc'] ?? 0),
        ice_thick_m: Number(s['ice_thickness_m'] ?? s['ice_thick_m'] ?? 0),
        wind_speed_ms: Number(s['wind_speed_ms'] ?? 0),
        wind_dir_from_deg: Number(s['wind_dir_from_deg'] ?? 0),
        hs_m: Number(s['hs'] ?? s['wave_height_m'] ?? 0),
        visibility_km: Number(s['visibility_km'] ?? 10),
        nearest_contact_nm: s['nearest_contact_nm'] == null ? null : Number(s['nearest_contact_nm']),
        active_alerts: Array.isArray(s['active_alerts']) ? (s['active_alerts'] as string[]) : [],
        provenance_by_variable: {},
      }));
    } catch (err) {
      this._error = err instanceof Error ? err.message : 'Timeline request failed';
      return [];
    }
  }
}

/** Normalize a timeline point's provenance_by_variable into canonical Provenance records. */
export function pointProvenance(
  point: TimelinePoint,
  variable: string,
): { kind: string; source: string; note: string; age_days?: number } | null {
  const rec = point.provenance_by_variable[variable];
  if (!rec) return null;
  const norm = normalizeProvenance(rec);
  if (!norm) return null;
  return {
    kind: norm.status,
    source: norm.source,
    note: norm.note,
    ...(norm.age_days !== undefined ? { age_days: norm.age_days } : {}),
  };
}
