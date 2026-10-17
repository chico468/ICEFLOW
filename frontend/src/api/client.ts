/**
 * Thin fetch client for the ICEFLOW service.
 *
 * Calls are same-origin by default. VITE_API_BASE_URL must be set at build time when the
 * two halves are hosted separately.
 * There are no keys, no CDNs and no tile servers anywhere in this app.
 */
import type {
  BandwidthReport,
  CoastlineResponse,
  CreateVoyageRequest,
  EnvSample,
  ForecastSkillResponse,
  HealthResponse,
  IceEdgeResponse,
  IceField,
  IceState,
  IcebergForecast,
  IcebergRiskResponse,
  IcebergsResponse,
  OptimizationSummary,
  POLARISAssessment,
  RadarSweep,
  ResistanceResult,
  RiskMatrixResponse,
  RouteRequest,
  SpeedPowerResponse,
  StationsResponse,
  VesselsResponse,
  VoyageState,
} from './types';

/** API origin, or '' for same-origin. Baked in at build time by Vite. */
const API_ORIGIN = (import.meta.env.VITE_API_BASE_URL ?? '').replace(/\/+$/, '');

export const API_BASE = `${API_ORIGIN}/api/v1`;

/** True when the bundle is pointed at a different host than the one serving it. */
export const IS_CROSS_ORIGIN = API_ORIGIN !== '';

export class ApiError extends Error {
  constructor(
    message: string,
    readonly status: number,
    readonly path: string,
  ) {
    super(message);
    this.name = 'ApiError';
  }
}

type QueryValue = string | number | boolean | undefined | null;

function qs(params: Record<string, QueryValue>): string {
  const parts: string[] = [];
  for (const [key, value] of Object.entries(params)) {
    if (value === undefined || value === null) continue;
    parts.push(`${encodeURIComponent(key)}=${encodeURIComponent(String(value))}`);
  }
  return parts.length ? `?${parts.join('&')}` : '';
}

async function request<T>(path: string, init?: RequestInit): Promise<T> {
  const res = await fetch(`${API_BASE}${path}`, {
    ...init,
    headers: { 'Content-Type': 'application/json', ...(init?.headers ?? {}) },
  });
  if (!res.ok) {
    let detail = `${res.status} ${res.statusText}`;
    try {
      const body = (await res.json()) as { detail?: string };
      if (body.detail) detail = body.detail;
    } catch {
      /* body was not JSON; the status line is the best message available */
    }
    throw new ApiError(detail, res.status, path);
  }
  return (await res.json()) as T;
}

function get<T>(path: string, params: Record<string, QueryValue> = {}): Promise<T> {
  return request<T>(`${path}${qs(params)}`);
}

function post<T>(path: string, body: unknown): Promise<T> {
  return request<T>(path, { method: 'POST', body: JSON.stringify(body) });
}

// ------------------------------------------------------------------------------- system

export const getHealth = () => get<HealthResponse>('/health');

// ---------------------------------------------------------------------------------- geo

export const getCoastline = () => get<CoastlineResponse>('/geo/coastline');
export const getStations = () => get<StationsResponse>('/geo/stations');

// -------------------------------------------------------------------------- environment

export const getEnvSample = (lat: number, lon: number, tHours = 0) =>
  get<EnvSample>('/env/sample', { lat, lon, t_hours: tHours });

export interface IceFieldQuery {
  latMin: number;
  latMax: number;
  lonMin: number;
  lonMax: number;
  resolutionDeg: number;
  tHours?: number;
  leadHours?: number;
}

/**
 * The service caps a request at 40 000 cells; it counts them as
 * (dlat / res) * (dlon / (2 * res)). We clamp before asking so a wide zoom-out
 * degrades to a coarser grid rather than a 400.
 */
export function clampIceResolution(q: IceFieldQuery): number {
  const MAX_CELLS = 38_000;
  const dLat = Math.max(0.01, q.latMax - q.latMin);
  const dLon = Math.max(0.01, q.lonMax - q.lonMin);
  let res = q.resolutionDeg;
  for (let i = 0; i < 12; i += 1) {
    const cells = (dLat / res) * (dLon / (res * 2));
    if (cells <= MAX_CELLS) break;
    res *= 1.5;
  }
  return Math.min(5, Math.max(0.25, Number(res.toFixed(3))));
}

export const getIceField = (q: IceFieldQuery) =>
  get<IceField>('/ice/field', {
    lat_min: q.latMin,
    lat_max: q.latMax,
    lon_min: q.lonMin,
    lon_max: q.lonMax,
    resolution_deg: clampIceResolution(q),
    t_hours: q.tHours ?? 0,
    lead_hours: q.leadHours ?? 0,
  });

export const getIcePoint = (lat: number, lon: number, leadHours = 0) =>
  get<IceState>('/ice/point', { lat, lon, lead_hours: leadHours });

export const getIceEdge = (tHours = 0, stepDeg = 2) =>
  get<IceEdgeResponse>('/ice/edge', { t_hours: tHours, step_deg: stepDeg });

export const getForecastSkill = (leads = '24,48,72,120,168') =>
  get<ForecastSkillResponse>('/ice/forecast-skill', { leads });

// ------------------------------------------------------------------------------- POLARIS

export const getRiskMatrix = () => get<RiskMatrixResponse>('/risk/matrix');

export const assessPolaris = (body: {
  ice_class: string;
  components: { ice_type: string; concentration_tenths: number }[];
  decayed?: boolean;
}) => post<POLARISAssessment>('/risk/polaris', body);

// ---------------------------------------------------------------------------- resistance

export const getVessels = () => get<VesselsResponse>('/vessels');

export const getSpeedPowerCurve = (vesselKey: string, thicknesses = '0.0,0.3,0.6,1.0,1.5', concentration = 0.8) =>
  get<SpeedPowerResponse>('/resistance/speed-power-curve', {
    vessel_key: vesselKey,
    thicknesses,
    concentration,
  });

export const calculateResistance = (body: {
  vessel_key: string;
  velocity_knots: number;
  ice_thickness_m: number;
  ice_concentration: number;
}) => post<ResistanceResult>('/resistance/calculate', body);

// -------------------------------------------------------------------------------- radar

/**
 * NOTE: the running service names this query parameter `heading_deg`, not `heading`
 * as the build specification's table suggested.
 */
export const getRadarSweep = (lat: number, lon: number, headingDeg: number, speedKnots = 8, tHours = 0) =>
  get<RadarSweep>('/radar/sweep', {
    lat,
    lon,
    heading_deg: headingDeg,
    speed_knots: speedKnots,
    t_hours: tHours,
  });

// ------------------------------------------------------------------------------ icebergs

export const getIcebergs = (leadHours = 0) =>
  get<IcebergsResponse>('/icebergs', { lead_hours: leadHours });

export const getIcebergDrift = (bergId: string, forecastHours = 72, ensembleMembers = 12) =>
  get<IcebergForecast>(`/icebergs/${encodeURIComponent(bergId)}/drift`, {
    forecast_hours: forecastHours,
    ensemble_members: ensembleMembers,
  });

export const getIcebergRisk = (body: RouteRequest) =>
  post<IcebergRiskResponse>('/route/iceberg-risk', body);

// ------------------------------------------------------------------------------- routing

export const optimizeRoute = (body: RouteRequest) =>
  post<OptimizationSummary>('/route/optimize', body);

// -------------------------------------------------------------------------------- voyage

export const createVoyage = (body: CreateVoyageRequest) => post<VoyageState>('/voyage', body);

export const getVoyage = (id: string) => get<VoyageState>(`/voyage/${encodeURIComponent(id)}`);

export const stepVoyage = (id: string, hours: number, tickHours: number) =>
  post<{ voyage_id: string; status: string; ticks_produced: number; sim_hours: number }>(
    `/voyage/${encodeURIComponent(id)}/step`,
    { hours, tick_hours: tickHours },
  );

// ----------------------------------------------------------------------------- telemetry

export const getBandwidth = (resolutionDeg = 0.5, updatesPerDay = 4) =>
  get<BandwidthReport>('/telemetry/bandwidth', {
    resolution_deg: resolutionDeg,
    updates_per_day: updatesPerDay,
  });

// ------------------------------------------------------------------------------ exports

export const exportUrl = (voyageId: string, fmt: 'geojson' | 'gpx' | 'csv' | 's411') =>
  `${API_BASE}/export/${encodeURIComponent(voyageId)}.${fmt}`;

/** The WebSocket lives under the same /api/v1 prefix as the REST routes. */
export function voyageSocketUrl(voyageId: string): string {
  const path = `/api/v1/ws/voyage/${encodeURIComponent(voyageId)}`;
  if (API_ORIGIN) {
    // Deployed split: derive the socket scheme from the API's own scheme, not the page's.
    return `${API_ORIGIN.replace(/^http/, 'ws')}${path}`;
  }
  const scheme = window.location.protocol === 'https:' ? 'wss' : 'ws';
  return `${scheme}://${window.location.host}${path}`;
}
