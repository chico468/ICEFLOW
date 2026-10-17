/**
 * TanStack Query bindings.
 *
 * The static datasets (coastline, stations, vessels, POLARIS matrix) never change while
 * the process runs, so they are cached indefinitely. Modelled fields are keyed by their
 * request so panning or moving the lead-time slider reuses anything already fetched.
 */
import { useQuery, type UseQueryResult } from '@tanstack/react-query';
import * as api from './client';
import type {
  BandwidthReport,
  CoastlineResponse,
  Endpoint,
  ForecastSkillResponse,
  HealthResponse,
  IceField,
  IceState,
  IcebergForecast,
  IcebergsResponse,
  RadarSweep,
  RiskMatrixResponse,
  SpeedPowerResponse,
  StationsResponse,
  VesselsResponse,
} from './types';

const FOREVER = { staleTime: Infinity, gcTime: Infinity } as const;

export function useHealth(): UseQueryResult<HealthResponse> {
  return useQuery({ queryKey: ['health'], queryFn: api.getHealth, staleTime: 60_000 });
}

export function useCoastline(): UseQueryResult<CoastlineResponse> {
  return useQuery({ queryKey: ['coastline'], queryFn: api.getCoastline, ...FOREVER });
}

export function useStations(): UseQueryResult<StationsResponse> {
  return useQuery({ queryKey: ['stations'], queryFn: api.getStations, ...FOREVER });
}

export function useVessels(): UseQueryResult<VesselsResponse> {
  return useQuery({ queryKey: ['vessels'], queryFn: api.getVessels, ...FOREVER });
}

export function useRiskMatrix(): UseQueryResult<RiskMatrixResponse> {
  return useQuery({ queryKey: ['risk-matrix'], queryFn: api.getRiskMatrix, ...FOREVER });
}

export function useForecastSkill(): UseQueryResult<ForecastSkillResponse> {
  return useQuery({
    queryKey: ['forecast-skill'],
    queryFn: () => api.getForecastSkill('6,12,24,48,72,120,168'),
    ...FOREVER,
  });
}

export function useBandwidth(resolutionDeg: number, updatesPerDay: number): UseQueryResult<BandwidthReport> {
  return useQuery({
    queryKey: ['bandwidth', resolutionDeg, updatesPerDay],
    queryFn: () => api.getBandwidth(resolutionDeg, updatesPerDay),
    staleTime: Infinity,
  });
}

export function useSpeedPowerCurve(vesselKey: string, concentration: number): UseQueryResult<SpeedPowerResponse> {
  return useQuery({
    queryKey: ['speed-power', vesselKey, concentration],
    queryFn: () => api.getSpeedPowerCurve(vesselKey, '0.0,0.3,0.6,1.0,1.5,2.0', concentration),
    staleTime: Infinity,
    enabled: Boolean(vesselKey),
  });
}

export function useIcebergs(leadHours: number): UseQueryResult<IcebergsResponse> {
  return useQuery({
    queryKey: ['icebergs', leadHours],
    queryFn: () => api.getIcebergs(leadHours),
    staleTime: 5 * 60_000,
  });
}

export function useIcebergDrift(
  bergId: string | null,
  forecastHours: number,
  ensembleMembers = 16,
): UseQueryResult<IcebergForecast> {
  return useQuery({
    queryKey: ['iceberg-drift', bergId, forecastHours, ensembleMembers],
    queryFn: () => api.getIcebergDrift(bergId as string, forecastHours, ensembleMembers),
    enabled: Boolean(bergId),
    staleTime: Infinity,
  });
}

export interface IceFieldParams {
  latMin: number;
  latMax: number;
  lonMin: number;
  lonMax: number;
  resolutionDeg: number;
  leadHours: number;
}

export function useIceField(p: IceFieldParams | null): UseQueryResult<IceField> {
  return useQuery({
    queryKey: [
      'ice-field',
      p?.latMin,
      p?.latMax,
      p?.lonMin,
      p?.lonMax,
      p?.resolutionDeg,
      p?.leadHours,
    ],
    queryFn: () =>
      api.getIceField({
        latMin: (p as IceFieldParams).latMin,
        latMax: (p as IceFieldParams).latMax,
        lonMin: (p as IceFieldParams).lonMin,
        lonMax: (p as IceFieldParams).lonMax,
        resolutionDeg: (p as IceFieldParams).resolutionDeg,
        leadHours: (p as IceFieldParams).leadHours,
        tHours: (p as IceFieldParams).leadHours,
      }),
    enabled: Boolean(p),
    staleTime: Infinity,
    placeholderData: (prev) => prev,
  });
}

/**
 * Point inspection: everything the ice model knows at one coordinate.
 * Enabled only when the user has actually clicked somewhere.
 */
export function useIcePoint(
  lat: number | null,
  lon: number | null,
  leadHours: number,
): UseQueryResult<IceState> {
  return useQuery({
    queryKey: ['ice-point', lat?.toFixed(3), lon?.toFixed(3), leadHours],
    queryFn: () => api.getIcePoint(lat as number, lon as number, leadHours),
    enabled: lat !== null && lon !== null,
    staleTime: Infinity,
  });
}

export function useRadarSweep(
  lat: number | null,
  lon: number | null,
  headingDeg: number,
  speedKnots: number,
  tHours: number,
): UseQueryResult<RadarSweep> {
  return useQuery({
    queryKey: ['radar', lat?.toFixed(2), lon?.toFixed(2), Math.round(headingDeg), Math.round(tHours)],
    queryFn: () => api.getRadarSweep(lat as number, lon as number, headingDeg, speedKnots, tHours),
    enabled: lat !== null && lon !== null,
    staleTime: 30_000,
    placeholderData: (prev) => prev,
  });
}

/**
 * Ports and stations collapsed into one picker list.
 * The anchorage is carried separately from the station position, because Maitri sits
 * about 80 km inland and a ship can only reach India Bay.
 */
export function useEndpoints(): { endpoints: Endpoint[]; note: string; loading: boolean } {
  const stations = useStations();
  const endpoints: Endpoint[] = [];
  const data = stations.data;
  if (data) {
    for (const p of data.ports) {
      endpoints.push({
        id: p.id,
        name: p.name,
        kind: 'port',
        lat: p.latitude,
        lon: p.longitude,
        anchorageLat: p.anchorage_lat,
        anchorageLon: p.anchorage_lon,
        country: p.country,
        isIndian: p.country === 'India',
        inland: false,
        note: p.notes ?? '',
        portApproach: '',
      });
    }
    for (const s of data.stations) {
      endpoints.push({
        id: s.id,
        name: s.name,
        kind: 'station',
        lat: s.latitude,
        lon: s.longitude,
        anchorageLat: s.anchorage_lat,
        anchorageLon: s.anchorage_lon,
        country: s.country,
        isIndian: Boolean(s.is_indian),
        inland: Boolean(s.station_is_inland),
        note: s.notes ?? '',
        portApproach: s.port_approach ?? '',
      });
    }
  }
  return { endpoints, note: data?.note ?? '', loading: stations.isLoading };
}
