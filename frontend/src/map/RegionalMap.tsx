/**
 * Regional context map, rendered with Mapbox GL JS and independent of the polar navigation chart.
 *
 * The map reuses the voyage scene for routes, ports, stations and vessel position. Natural Earth
 * polygons are display-only context; this map is not used for navigation or land clearance.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type KeyboardEvent, type ReactNode } from 'react';
import type {
  AnyLayer,
  GeoJSONSource,
  Map as MapboxMap,
  RasterArraySourceSpecification,
  RasterParticleLayerSpecification,
} from 'mapbox-gl';
import type { Feature, FeatureCollection, Geometry, Position } from 'geojson';
import { Globe, Maximize2, Minus, Plus, Wind } from 'lucide-react';
import type { RegionalContext, FlatRing } from '../api/types';
import type { RouteProfileId } from '../api/types';
import { useRegionalContext } from '../api/queries';
import { MapToolbar, ToolButton } from '../components/MapToolbar';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { MAX_COUNTRY_LABELS, MAX_MARK_LABELS, countryRankThreshold, showMarkLabel } from './labelPolicy';
import { formatLat, formatLon } from './MapCanvas';
import type { MapEngine, MapScene } from './MapEngine';
import { splitAtAntimeridian, viewOutline, type LonLat, type RegionBounds } from './mercator';
import { MAP_COLORS } from './palette';

const DEFAULT_REGION: RegionBounds = { lon_min: -30, lon_max: 165, lat_min: -75, lat_max: 40 };
const MAX_RELATIVE_ZOOM = 40;
const PAN_STEP = 80;
const PAN_FAR_STEP = 240;
const MAP_STYLE = 'mapbox://styles/mapbox/standard-satellite';
const WIND_SOURCE_ID = 'iceflow-wind-source';
const WIND_SOURCE_URL = 'mapbox://rasterarrayexamples.gfs-winds';
const WIND_LAYER_ID = 'iceflow-wind-particles';
const WIND_SOURCE_LAYER = '10winds';
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };

interface Props {
  scene: MapScene;
  visible: boolean;
  polarEngine: MapEngine | null;
  originId: string;
  destinationId: string;
  toolbarLead?: ReactNode;
  onSelectRouteCandidate: (id: RouteProfileId) => void;
}

interface MarkProperties {
  id: string;
  name: string;
  kind: 'port' | 'station';
  endpoint: boolean;
  indian: boolean;
}

interface Latest {
  scene: MapScene;
  data: RegionalContext | undefined;
  originId: string;
  destinationId: string;
  polarEngine: MapEngine | null;
  visible: boolean;
}

function closedRing(ring: FlatRing): Position[] {
  const points: Position[] = [];
  for (let i = 0; i + 1 < ring.length; i += 2) points.push([ring[i], ring[i + 1]]);
  if (points.length > 0) {
    const first = points[0];
    const last = points[points.length - 1];
    if (first[0] !== last[0] || first[1] !== last[1]) points.push(first);
  }
  return points.length >= 4 ? points : [];
}

function polygonCoordinates(rings: FlatRing[]): Position[][] {
  return rings.map((ring) => closedRing(ring)).filter((ring) => ring.length > 0);
}

function featureCollection<G extends Geometry, P = Record<string, never>>(
  features: Feature<G, P>[],
): FeatureCollection<G, P> {
  return { type: 'FeatureCollection', features };
}

function lineSegments(points: LonLat[]): Position[][] {
  return splitAtAntimeridian(points)
    .filter((run) => run.length > 1)
    .map((run) => run.map((point) => [point.lon, point.lat]));
}

function makeLand(data: RegionalContext | undefined): FeatureCollection<Geometry> {
  const polygons = (data?.available ? data.land : []).map(polygonCoordinates).filter((rings) => rings.length > 0);
  return featureCollection(
    polygons.length > 0
      ? [{ type: 'Feature', properties: {}, geometry: { type: 'MultiPolygon', coordinates: polygons } }]
      : [],
  );
}

function makeCountries(data: RegionalContext | undefined): FeatureCollection<Geometry> {
  const features: Feature<Geometry, { name: string }>[] = [];
  if (data?.available) {
    for (const country of data.countries) {
      const polygons = country.polygons.map(polygonCoordinates).filter((rings) => rings.length > 0);
      if (polygons.length > 0) {
        features.push({
          type: 'Feature',
          properties: { name: country.name },
          geometry: { type: 'MultiPolygon', coordinates: polygons },
        });
      }
    }
  }
  return featureCollection(features);
}

function makeCountryLabels(data: RegionalContext | undefined, relativeZoom: number): FeatureCollection<Geometry> {
  if (!data?.available) return EMPTY;
  const threshold = countryRankThreshold(relativeZoom);
  const features: Feature<Geometry, { name: string; rank: number }>[] = data.countries
    .filter((country) => country.label_rank >= threshold)
    .sort((a, b) => b.label_rank - a.label_rank)
    .slice(0, MAX_COUNTRY_LABELS)
    .map((country) => ({
      type: 'Feature',
      properties: { name: country.name.toUpperCase(), rank: country.label_rank },
      geometry: { type: 'Point', coordinates: country.label },
    }));
  return featureCollection(features);
}

function makeMarks(latest: Latest): FeatureCollection<Geometry, MarkProperties> {
  const { scene, originId, destinationId } = latest;
  const marks: Feature<Geometry, MarkProperties>[] = [
    ...scene.ports.map((port) => ({
      type: 'Feature' as const,
      properties: {
        id: port.id,
        name: port.name,
        kind: 'port' as const,
        endpoint: port.id === originId || port.id === destinationId,
        indian: false,
      },
      geometry: { type: 'Point' as const, coordinates: [port.longitude, port.latitude] },
    })),
    ...scene.stations.map((station) => ({
      type: 'Feature' as const,
      properties: {
        id: station.id,
        name: station.name,
        kind: 'station' as const,
        endpoint: station.id === originId || station.id === destinationId,
        indian: Boolean(station.is_indian),
      },
      geometry: { type: 'Point' as const, coordinates: [station.longitude, station.latitude] },
    })),
  ];
  return featureCollection(marks);
}

function makeMarkLabels(marks: FeatureCollection<Geometry, MarkProperties>, relativeZoom: number): FeatureCollection<Geometry> {
  const features = marks.features
    .filter(({ properties }) => showMarkLabel(properties, relativeZoom))
    .sort((a, b) => Number(b.properties.endpoint) - Number(a.properties.endpoint))
    .slice(0, MAX_MARK_LABELS);
  return featureCollection(features);
}

function makeLines(scene: MapScene): FeatureCollection<Geometry, { kind: string }> {
  const features: Feature<Geometry, { kind: string; profile?: RouteProfileId; selected?: boolean }>[] = [];
  const addLine = (kind: string, points: LonLat[]): void => {
    const coordinates = lineSegments(points);
    if (coordinates.length > 0) {
      features.push({
        type: 'Feature',
        properties: { kind },
        geometry: { type: 'MultiLineString', coordinates },
      });
    }
  };
  addLine('baseline', scene.baselineRoute.map((point) => ({ lat: point.latitude, lon: point.longitude })));
  if (scene.routeAlternatives.length === 0) {
    addLine('optimized', scene.optimisedRoute.map((point) => ({ lat: point.latitude, lon: point.longitude })));
  } else {
    const candidates = [...scene.routeAlternatives].sort((a, b) => (
      Number(a.id === scene.selectedCandidateId) - Number(b.id === scene.selectedCandidateId)
    ));
    for (const candidate of candidates) {
      const coordinates = lineSegments(candidate.evaluation.waypoints.map((point) => ({
        lat: point.latitude,
        lon: point.longitude,
      })));
      if (coordinates.length > 0) {
        features.push({
          type: 'Feature',
          properties: {
            kind: 'candidate',
            profile: candidate.id,
            selected: candidate.id === scene.selectedCandidateId,
          },
          geometry: { type: 'MultiLineString', coordinates },
        });
      }
    }
  }
  addLine('track', scene.track.map(([lat, lon]) => ({ lat, lon })));
  return featureCollection(features);
}

function makePolarOutline(engine: MapEngine | null): FeatureCollection<Geometry> {
  if (!engine) return EMPTY;
  const outline = viewOutline(engine.viewport);
  const features = lineSegments(outline)
    .map((coordinates): Feature<Geometry> => ({
      type: 'Feature',
      properties: {},
      geometry: { type: 'LineString', coordinates },
    }));
  return featureCollection(features);
}

function makePolarLabel(engine: MapEngine | null): FeatureCollection<Geometry, { name: string }> {
  if (!engine) return featureCollection<Geometry, { name: string }>([]);
  const point = viewOutline(engine.viewport)[0];
  if (!point) return featureCollection<Geometry, { name: string }>([]);
  return featureCollection([
    {
      type: 'Feature',
      properties: { name: 'Antarctic chart view' },
      geometry: { type: 'Point', coordinates: [point.lon, point.lat] },
    },
  ]);
}

function updateSource(map: MapboxMap, id: string, data: FeatureCollection): void {
  const source = map.getSource(id);
  if (source?.type === 'geojson') (source as GeoJSONSource).setData(data);
}

function addGeoJSONSourceIfMissing(map: MapboxMap, id: string): void {
  if (!map.getSource(id)) map.addSource(id, { type: 'geojson', data: EMPTY });
}

function addLayerIfMissing(map: MapboxMap, layer: AnyLayer, slot: 'bottom' | 'middle' | 'top' = 'top'): void {
  if (!map.getLayer(layer.id)) map.addLayer({ ...layer, slot });
}

function addWindParticles(map: MapboxMap, enabled: boolean, onError: (reason: string) => void): boolean {
  try {
    if (!map.getSource(WIND_SOURCE_ID)) {
      const source: RasterArraySourceSpecification = {
        type: 'raster-array',
        url: WIND_SOURCE_URL,
        tileSize: 512,
      };
      map.addSource(WIND_SOURCE_ID, source);
    }
    if (!map.getLayer(WIND_LAYER_ID)) {
      const layer: RasterParticleLayerSpecification = {
        id: WIND_LAYER_ID,
        type: 'raster-particle',
        source: WIND_SOURCE_ID,
        'source-layer': WIND_SOURCE_LAYER,
        slot: 'bottom',
        paint: {
          'raster-particle-speed-factor': 0.4,
          'raster-particle-fade-opacity-factor': 0.92,
          'raster-particle-reset-rate-factor': 0.4,
          'raster-particle-count': 1600,
          'raster-particle-max-speed': 40,
          'raster-particle-color': [
            'interpolate',
            ['linear'],
            ['raster-particle-speed'],
            0,
            '#72B7D2',
            3,
            '#45B8C5',
            7,
            '#74C879',
            12,
            '#E7CF55',
            20,
            '#EA9147',
            32,
            '#D95454',
            50,
            '#B14A91',
          ],
        },
      };
      map.addLayer(layer);
    }
    map.setLayoutProperty(WIND_LAYER_ID, 'visibility', enabled ? 'visible' : 'none');
    return true;
  } catch (error) {
    onError(error instanceof Error ? error.message : 'Unknown Mapbox raster-particle error');
    return false;
  }
}

function addLayers(map: MapboxMap, windEnabled: boolean, onWindError: (reason: string) => void): boolean {
  const windLayerAdded = addWindParticles(map, windEnabled, onWindError);
  addGeoJSONSourceIfMissing(map, 'regional-land');
  addGeoJSONSourceIfMissing(map, 'regional-countries');
  addGeoJSONSourceIfMissing(map, 'regional-country-labels');
  addGeoJSONSourceIfMissing(map, 'regional-lines');
  addGeoJSONSourceIfMissing(map, 'regional-marks');
  addGeoJSONSourceIfMissing(map, 'regional-mark-labels');
  addGeoJSONSourceIfMissing(map, 'regional-vessel');
  addGeoJSONSourceIfMissing(map, 'regional-polar-outline');
  addGeoJSONSourceIfMissing(map, 'regional-polar-label');

  addLayerIfMissing(map, {
    id: 'regional-land-fill',
    type: 'fill',
    source: 'regional-land',
    paint: { 'fill-color': MAP_COLORS.land, 'fill-opacity': 0.12 },
  });
  addLayerIfMissing(map, {
    id: 'regional-country-borders',
    type: 'line',
    source: 'regional-countries',
    paint: { 'line-color': 'rgba(143,133,116,0.5)', 'line-width': 0.7 },
  });
  addLayerIfMissing(map, {
    id: 'regional-polar-fill',
    type: 'line',
    source: 'regional-polar-outline',
    paint: { 'line-color': '#0B5C8E', 'line-width': 1.6, 'line-dasharray': [3, 2], 'line-opacity': 0.95 },
  });
  addLayerIfMissing(map, {
    id: 'regional-baseline-route',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'baseline'],
    paint: { 'line-color': MAP_COLORS.routeBaseline, 'line-width': 1.5, 'line-dasharray': [3, 2] },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-optimized-route',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'optimized'],
    paint: { 'line-color': MAP_COLORS.routeOptimised, 'line-width': 2.4 },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-candidate-route-halo',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'candidate'],
    paint: {
      'line-color': MAP_COLORS.routeHalo,
      'line-width': ['case', ['boolean', ['get', 'selected'], false], 10, 7],
      'line-opacity': 0.96,
    },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-candidate-route-casing',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'candidate'],
    paint: {
      'line-color': MAP_COLORS.routeDarkCasing,
      'line-width': ['case', ['boolean', ['get', 'selected'], false], 7.5, 4.8],
      'line-opacity': 0.92,
    },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-candidate-routes',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'candidate'],
    paint: {
      'line-color': [
        'match', ['get', 'profile'],
        'safety-first', MAP_COLORS.routeSafetyFirst,
        'balanced', MAP_COLORS.routeBalanced,
        'fuel-efficient', MAP_COLORS.routeFuelEfficient,
        'fastest', MAP_COLORS.routeFastest,
        '#334155',
      ],
      'line-width': ['case', ['boolean', ['get', 'selected'], false], 5.5, 3.3],
      'line-opacity': ['case', ['boolean', ['get', 'selected'], false], 1, 0.94],
    },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-track',
    type: 'line',
    source: 'regional-lines',
    filter: ['==', ['get', 'kind'], 'track'],
    paint: { 'line-color': MAP_COLORS.track, 'line-width': 2.6 },
    layout: { 'line-cap': 'round', 'line-join': 'round' },
  });
  addLayerIfMissing(map, {
    id: 'regional-ports',
    type: 'circle',
    source: 'regional-marks',
    filter: ['==', ['get', 'kind'], 'port'],
    paint: {
      'circle-radius': 4,
      'circle-color': MAP_COLORS.port,
      'circle-stroke-color': ['case', ['get', 'endpoint'], '#0E2433', 'rgba(255,255,255,0.9)'],
      'circle-stroke-width': ['case', ['get', 'endpoint'], 2.2, 1],
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-stations',
    type: 'circle',
    source: 'regional-marks',
    filter: ['==', ['get', 'kind'], 'station'],
    paint: {
      'circle-radius': 4,
      'circle-color': MAP_COLORS.station,
      'circle-stroke-color': ['case', ['get', 'endpoint'], '#0E2433', 'rgba(255,255,255,0.9)'],
      'circle-stroke-width': ['case', ['get', 'endpoint'], 2.2, 1],
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-mark-labels',
    type: 'symbol',
    source: 'regional-mark-labels',
    layout: {
      'text-field': ['get', 'name'],
      'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'],
      'text-size': 11,
      'text-offset': [0.8, 0],
      'text-anchor': 'left',
      'text-optional': true,
      'symbol-sort-key': ['case', ['get', 'endpoint'], 0, 1],
    },
    paint: {
      'text-color': '#0E2433',
      'text-halo-color': 'rgba(255,255,255,0.9)',
      'text-halo-width': 1.5,
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-country-labels',
    type: 'symbol',
    source: 'regional-country-labels',
    layout: {
      'text-field': ['get', 'name'],
      'text-font': ['Open Sans Regular', 'Arial Unicode MS Regular'],
      'text-size': 10,
      'text-allow-overlap': false,
    },
    paint: { 'text-color': 'rgba(14,36,51,0.58)' },
  });
  addLayerIfMissing(map, {
    id: 'regional-vessel',
    type: 'circle',
    source: 'regional-vessel',
    paint: {
      'circle-radius': 6,
      'circle-color': '#FFFFFF',
      'circle-stroke-color': MAP_COLORS.track,
      'circle-stroke-width': 2.2,
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-polar-label',
    type: 'symbol',
    source: 'regional-polar-label',
    layout: {
      'text-field': ['get', 'name'],
      'text-font': ['Open Sans Semibold', 'Arial Unicode MS Regular'],
      'text-size': 11,
      'text-offset': [0.5, 0.5],
      'text-anchor': 'left',
    },
    paint: {
      'text-color': '#0B5C8E',
      'text-halo-color': 'rgba(255,255,255,0.9)',
      'text-halo-width': 1.5,
    },
  });
  return windLayerAdded;
}

function getRelativeZoom(map: MapboxMap, baseZoom: number): { relativeZoom: number; centre: string } {
  const relativeZoom = Math.pow(2, map.getZoom() - baseZoom);
  const center = map.getCenter();
  return { relativeZoom, centre: `${center.lng.toFixed(3)},${center.lat.toFixed(3)}` };
}

function fitRegion(map: MapboxMap, bounds: RegionBounds): number {
  map.fitBounds(
    [
      [bounds.lon_min, bounds.lat_min],
      [bounds.lon_max, bounds.lat_max],
    ],
    { padding: 24, duration: 0 },
  );
  return map.getZoom();
}

function safeMapDiagnostic(reason: string, token: string): string {
  return reason
    .replaceAll(token, '[redacted]')
    .replace(/([?&]access_token=)[^&\s"'`]+/gi, '$1[redacted]');
}

function isRouteProfileId(value: unknown): value is RouteProfileId {
  return value === 'safety-first' || value === 'balanced' || value === 'fuel-efficient' || value === 'fastest';
}

export function RegionalMap({
  scene,
  visible,
  polarEngine,
  originId,
  destinationId,
  toolbarLead,
  onSelectRouteCandidate,
}: Props): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const pointerPointRef = useRef<[number, number] | null>(null);
  const windEnabledRef = useRef(true);
  const baseZoomRef = useRef(0);
  const fittedKeyRef = useRef('');
  const regionKeyRef = useRef('');
  const reducedMotion = useReducedMotion();
  const context = useRegionalContext();
  const data = context.data;
  const region = data?.region ?? DEFAULT_REGION;
  const regionKey = `${region.lon_min},${region.lon_max},${region.lat_min},${region.lat_max}`;
  const [mapReady, setMapReady] = useState(false);
  const [mapError, setMapError] = useState<string | null>(null);
  const [mapView, setMapView] = useState<{ zoom: number; centre: string } | null>(null);
  const [windParticlesEnabled, setWindParticlesEnabled] = useState(true);
  const [windSourceStatus, setWindSourceStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [windLayerPresent, setWindLayerPresent] = useState(false);
  const [windError, setWindError] = useState<string | null>(null);
  const windErrorRef = useRef<string | null>(null);
  const selectCandidateRef = useRef(onSelectRouteCandidate);
  selectCandidateRef.current = onSelectRouteCandidate;
  windEnabledRef.current = windParticlesEnabled;

  const routePoints = useMemo(
    () => scene.optimisedRoute.map((point) => ({ lat: point.latitude, lon: point.longitude })),
    [scene.optimisedRoute],
  );
  const endpointPoints = useMemo(() => {
    const find = (id: string): LonLat | null => {
      const point = scene.ports.find((port) => port.id === id) ?? scene.stations.find((station) => station.id === id);
      return point ? { lat: point.latitude, lon: point.longitude } : null;
    };
    return [find(originId), find(destinationId)].filter((point): point is LonLat => point !== null);
  }, [scene.ports, scene.stations, originId, destinationId]);
  const initialPoints = routePoints.length >= 2 ? routePoints : endpointPoints;
  const initialKey = `${originId}>${destinationId}|${routePoints.length}|${initialPoints.length}`;

  const latestRef = useRef<Latest>({ scene, data, originId, destinationId, polarEngine, visible });
  latestRef.current = { scene, data, originId, destinationId, polarEngine, visible };

  const reportWindFailure = useCallback((reason: string): void => {
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim() ?? '';
    const safeReason = safeMapDiagnostic(reason, token);
    if (windErrorRef.current === safeReason) return;
    windErrorRef.current = safeReason;
    setWindSourceStatus('error');
    setWindError(safeReason);
    if (import.meta.env.DEV) console.error(`[RegionalMap] GFS atmospheric wind particles failed: ${safeReason}`);
  }, []);

  const updateMapData = useCallback(
    (map: MapboxMap): void => {
      const latest = latestRef.current;
      const { relativeZoom, centre } = getRelativeZoom(map, baseZoomRef.current);
      setMapView({ zoom: relativeZoom, centre });
      const marks = makeMarks(latest);
      updateSource(map, 'regional-land', makeLand(latest.data));
      updateSource(map, 'regional-countries', makeCountries(latest.data));
      updateSource(map, 'regional-country-labels', makeCountryLabels(latest.data, relativeZoom));
      updateSource(map, 'regional-lines', makeLines(latest.scene));
      updateSource(map, 'regional-marks', marks);
      updateSource(map, 'regional-mark-labels', makeMarkLabels(marks, relativeZoom));
      updateSource(
        map,
        'regional-vessel',
        latest.scene.layers.vessel && latest.scene.vessel
          ? featureCollection([
              {
                type: 'Feature',
                properties: {},
                geometry: {
                  type: 'Point',
                  coordinates: [latest.scene.vessel.lon, latest.scene.vessel.lat],
                },
              },
            ])
          : EMPTY,
      );
      updateSource(map, 'regional-polar-outline', makePolarOutline(latest.polarEngine));
      updateSource(map, 'regional-polar-label', makePolarLabel(latest.polarEngine));
      map.setLayoutProperty('regional-baseline-route', 'visibility', latest.scene.layers.baselineRoute ? 'visible' : 'none');
      map.setLayoutProperty('regional-optimized-route', 'visibility', latest.scene.layers.optimisedRoute ? 'visible' : 'none');
      map.setLayoutProperty('regional-track', 'visibility', latest.scene.layers.track ? 'visible' : 'none');
      map.setLayoutProperty('regional-vessel', 'visibility', latest.scene.layers.vessel ? 'visible' : 'none');
    },
    [],
  );

  useEffect(() => {
    const container = mapContainerRef.current;
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
    if (!visible || mapRef.current || !container) return undefined;
    if (!token) {
      setMapError('Mapbox is not configured. Set VITE_MAPBOX_ACCESS_TOKEN to enable the regional map.');
      return undefined;
    }

    let cancelled = false;
    const initialize = async (): Promise<void> => {
      const [mapbox, _style] = await Promise.all([import('mapbox-gl'), import('mapbox-gl/dist/mapbox-gl.css')]);
      if (cancelled || !mapContainerRef.current) return;
      const mapboxgl = mapbox.default;
      setMapError(null);
      setMapReady(false);
      setWindSourceStatus('loading');
      setWindError(null);
      windErrorRef.current = null;
      mapboxgl.accessToken = token;
      const map = new mapboxgl.Map({
        container: mapContainerRef.current,
        style: MAP_STYLE,
        center: [(region.lon_min + region.lon_max) / 2, (region.lat_min + region.lat_max) / 2],
        zoom: 1,
        attributionControl: false,
        cooperativeGestures: false,
        doubleClickZoom: true,
        dragPan: true,
        dragRotate: false,
        keyboard: false,
        maxPitch: 0,
        pitchWithRotate: false,
        renderWorldCopies: false,
        scrollZoom: false,
        touchZoomRotate: true,
      });
      mapRef.current = map;

      const addRegionalLayers = (): void => {
        if (!map.getSource(WIND_SOURCE_ID)) {
          setWindSourceStatus('loading');
          setWindError(null);
          windErrorRef.current = null;
        }
        const added = addLayers(map, windEnabledRef.current, reportWindFailure);
        setWindLayerPresent(added || Boolean(map.getLayer(WIND_LAYER_ID)));
      };
      map.on('style.load', () => {
        if (!map.isStyleLoaded()) return;
        addRegionalLayers();
        updateMapData(map);
      });
      map.on('sourcedata', (event) => {
        if (event.sourceId !== WIND_SOURCE_ID) return;
        if (event.sourceDataType === 'error') {
          reportWindFailure(`Mapbox reported an error loading raster-array source ${WIND_SOURCE_ID}.`);
        } else if (event.sourceDataType === 'content' && event.isSourceLoaded) {
          windErrorRef.current = null;
          setWindSourceStatus((status) => status === 'error' ? status : 'ready');
          setWindError(null);
        }
      });
      map.on('error', (event) => {
        const message = event.error.message;
        if ([WIND_SOURCE_ID, WIND_LAYER_ID, WIND_SOURCE_URL, 'raster-array', 'raster-particle'].some((key) => message.includes(key))) {
          reportWindFailure(message);
        }
      });

      const onLoad = (): void => {
        addRegionalLayers();
        baseZoomRef.current = fitRegion(map, region);
        map.setMinZoom(baseZoomRef.current);
        map.setMaxZoom(baseZoomRef.current + Math.log2(MAX_RELATIVE_ZOOM));
        map.addControl(new mapboxgl.ScaleControl({ maxWidth: 120, unit: 'metric' }), 'top-left');
        map.getCanvas().tabIndex = -1;
        regionKeyRef.current = regionKey;
        map.getCanvas().setAttribute('aria-label', 'Regional map with routes, ports, stations, vessel and polar chart extent');
        map.getCanvas().setAttribute('role', 'img');
        const updateAfterCameraChange = (): void => {
          if (map.isStyleLoaded()) updateMapData(map);
        };
        map.on('zoomend', updateAfterCameraChange);
        map.on('moveend', updateAfterCameraChange);
        map.on('mousemove', (event) => {
          pointerPointRef.current = [event.point.x, event.point.y];
          const readout = readoutRef.current;
          if (readout) {
            readout.textContent = `${formatLat(event.lngLat.lat)}   ${formatLon(event.lngLat.lng)}`;
          }
        });
        map.on('click', 'regional-candidate-routes', (event) => {
          const profile = event.features?.[0]?.properties?.profile;
          if (isRouteProfileId(profile)) selectCandidateRef.current(profile);
        });
        map.on('mouseenter', 'regional-candidate-routes', () => {
          map.getCanvasContainer().style.cursor = 'pointer';
        });
        map.on('mouseleave', 'regional-candidate-routes', () => {
          map.getCanvasContainer().style.cursor = '';
        });
        const canvas = map.getCanvas();
        const onWheel = (event: WheelEvent): void => {
          event.preventDefault();
          const unit = event.deltaMode === 1 ? 16 : event.deltaMode === 2 ? 400 : 1;
          const rate = event.ctrlKey ? 0.01 : 0.0018;
          const rect = map.getContainer().getBoundingClientRect();
          const point = pointerPointRef.current ?? [event.clientX - rect.left, event.clientY - rect.top];
          const anchor = map.unproject(point);
          map.easeTo({
            zoom: map.getZoom() - (event.deltaY * unit * rate) / Math.LN2,
            around: anchor,
            duration: 0,
          });
        };
        canvas.addEventListener('wheel', onWheel, { passive: false });
        map.on('remove', () => canvas.removeEventListener('wheel', onWheel));
        map.on('mouseleave', () => {
          if (readoutRef.current) readoutRef.current.textContent = '—';
        });
        map.on('idle', () => {
          setMapReady(true);
          if (map.getSource(WIND_SOURCE_ID) && map.isSourceLoaded(WIND_SOURCE_ID)) {
            setWindSourceStatus((status) => status === 'error' ? status : 'ready');
          }
        });
        updateMapData(map);
        setMapReady(true);
      };

      const onError = (): void => {
        setMapError('Mapbox could not load the map. Check the public token, network connection and Mapbox style access.');
      };
      map.on('load', onLoad);
      map.on('error', onError);
    };
    void initialize().catch(() => {
      if (!cancelled) setMapError('Unable to initialize Mapbox. Check the installed map package and public token configuration.');
    });
    return () => {
      cancelled = true;
    };
  }, [visible, updateMapData, reportWindFailure]);

  useEffect(
    () => () => {
      const map = mapRef.current;
      map?.remove();
      mapRef.current = null;
    },
    [],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.isStyleLoaded() || regionKeyRef.current === regionKey) return;
    map.setMinZoom(0);
    map.setMaxZoom(24);
    baseZoomRef.current = fitRegion(map, region);
    map.setMinZoom(baseZoomRef.current);
    map.setMaxZoom(baseZoomRef.current + Math.log2(MAX_RELATIVE_ZOOM));
    regionKeyRef.current = regionKey;
    fittedKeyRef.current = '';
    updateMapData(map);
  }, [mapReady, regionKey, region, reducedMotion, updateMapData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.isStyleLoaded()) return;
    updateMapData(map);
  }, [mapReady, scene, data, originId, destinationId, polarEngine, updateMapData]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.isStyleLoaded() || !map.getLayer(WIND_LAYER_ID)) return;
    map.setLayoutProperty(WIND_LAYER_ID, 'visibility', windParticlesEnabled ? 'visible' : 'none');
    setWindLayerPresent(true);
  }, [mapReady, windParticlesEnabled]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !visible || !polarEngine) return undefined;
    const updateOutline = (): void => {
      updateSource(map, 'regional-polar-outline', makePolarOutline(polarEngine));
      updateSource(map, 'regional-polar-label', makePolarLabel(polarEngine));
    };
    updateOutline();
    return polarEngine.subscribe(updateOutline);
  }, [mapReady, visible, polarEngine]);

  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || fittedKeyRef.current === initialKey) return;
    fittedKeyRef.current = initialKey;
    if (initialPoints.length >= 2) {
      const longitudes = initialPoints.map((point) => point.lon);
      const latitudes = initialPoints.map((point) => point.lat);
      map.fitBounds(
        [
          [Math.min(...longitudes), Math.min(...latitudes)],
          [Math.max(...longitudes), Math.max(...latitudes)],
        ],
        { padding: 90, duration: reducedMotion ? 0 : 260, maxZoom: baseZoomRef.current + Math.log2(16) },
      );
    } else if (initialPoints.length === 1) {
      map.flyTo({
        center: [initialPoints[0].lon, initialPoints[0].lat],
        zoom: baseZoomRef.current + 2,
        duration: reducedMotion ? 0 : 260,
      });
    }
  }, [mapReady, initialKey, initialPoints, reducedMotion]);

  const fitInitial = useCallback((): void => {
    const map = mapRef.current;
    if (!map || initialPoints.length === 0) return;
    if (initialPoints.length === 1) {
      map.flyTo({
        center: [initialPoints[0].lon, initialPoints[0].lat],
        zoom: baseZoomRef.current + 2,
        duration: reducedMotion ? 0 : 260,
      });
      return;
    }
    const longitudes = initialPoints.map((point) => point.lon);
    const latitudes = initialPoints.map((point) => point.lat);
    map.fitBounds(
      [
        [Math.min(...longitudes), Math.min(...latitudes)],
        [Math.max(...longitudes), Math.max(...latitudes)],
      ],
      { padding: 90, duration: reducedMotion ? 0 : 260, maxZoom: baseZoomRef.current + Math.log2(16) },
    );
  }, [initialPoints, reducedMotion]);

  const showWholeRegion = useCallback((): void => {
    const map = mapRef.current;
    if (map) map.fitBounds(
      [
        [region.lon_min, region.lat_min],
        [region.lon_max, region.lat_max],
      ],
      { padding: 24, duration: reducedMotion ? 0 : 260 },
    );
  }, [region, reducedMotion]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const map = mapRef.current;
    if (!map || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target !== hostRef.current && target !== map.getCanvas()) return;
    const pan = event.shiftKey ? PAN_FAR_STEP : PAN_STEP;
    switch (event.key) {
      case 'ArrowLeft': map.panBy([-pan, 0], { duration: reducedMotion ? 0 : 140 }); break;
      case 'ArrowRight': map.panBy([pan, 0], { duration: reducedMotion ? 0 : 140 }); break;
      case 'ArrowUp': map.panBy([0, -pan], { duration: reducedMotion ? 0 : 140 }); break;
      case 'ArrowDown': map.panBy([0, pan], { duration: reducedMotion ? 0 : 140 }); break;
      case '+':
      case '=': map.zoomTo(map.getZoom() + Math.log2(1.5), { duration: reducedMotion ? 0 : 200 }); break;
      case '-':
      case '_': map.zoomTo(map.getZoom() - Math.log2(1.5), { duration: reducedMotion ? 0 : 200 }); break;
      case '0':
      case 'Home': fitInitial(); break;
      case 'f':
      case 'F': showWholeRegion(); break;
      default: return;
    }
    event.preventDefault();
  };

  const unavailable = context.isError || (data && !data.available);
  const zoomIn = (): void => {
    const map = mapRef.current;
    if (map) map.zoomTo(map.getZoom() + Math.log2(1.5), { duration: reducedMotion ? 0 : 200 });
  };
  const zoomOut = (): void => {
    const map = mapRef.current;
    if (map) map.zoomTo(map.getZoom() - Math.log2(1.5), { duration: reducedMotion ? 0 : 200 });
  };

  return (
    <div
      ref={hostRef}
      data-zoom={mapView?.zoom.toFixed(3)}
      data-centre={mapView?.centre}
      data-map-ready={mapReady ? 'true' : undefined}
      data-wind-source-status={windSourceStatus}
      data-wind-layer-present={windLayerPresent ? 'true' : 'false'}
      data-wind-layer-visibility={windLayerPresent ? (windParticlesEnabled ? 'visible' : 'none') : undefined}
      tabIndex={0}
      role="application"
      aria-label="Regional context map"
      aria-describedby="regional-map-help"
      onPointerDown={(event) => {
        if (event.target instanceof Node && mapContainerRef.current?.contains(event.target)) {
          hostRef.current?.focus({ preventScroll: true });
        }
      }}
      onClick={(event) => {
        if (event.target instanceof Node && mapContainerRef.current?.contains(event.target)) {
          hostRef.current?.focus({ preventScroll: true });
        }
      }}
      onKeyDown={onKeyDown}
      className="relative h-full w-full overflow-hidden outline-none focus-visible:ring-2 focus-visible:ring-inset focus-visible:ring-accent"
    >
      <p id="regional-map-help" className="sr-only">
        Arrow keys pan, plus and minus zoom, zero returns to the route extent, and F shows the whole region.
        Scroll or pinch to zoom, drag to pan, and double-click to zoom in.
      </p>
      <div
        ref={mapContainerRef}
        data-testid="regional-map-renderer"
        className="overflow-hidden"
        style={{ position: 'absolute', top: 0, bottom: 0, left: '4%', right: '4%', width: 'auto', height: 'auto' }}
      />
      <MapToolbar
        lead={toolbarLead}
        groups={[
          <>
            <ToolButton label="Zoom in" onClick={zoomIn}>
              <Plus size={15} />
            </ToolButton>
            <ToolButton label="Zoom out" onClick={zoomOut}>
              <Minus size={15} />
            </ToolButton>
            <ToolButton label="Reset to the route extent" onClick={fitInitial}>
              <Maximize2 size={15} />
            </ToolButton>
            <ToolButton label="Show the whole region" onClick={showWholeRegion}>
              <Globe size={15} />
            </ToolButton>
          </>,
          <>
            <ToolButton
              label="Wind particles"
              hint="GFS atmospheric wind velocity; not sea-ice drift or ocean currents."
              onClick={() => setWindParticlesEnabled((enabled) => !enabled)}
              pressed={windParticlesEnabled}
              disabled={!windLayerPresent}
            >
              <Wind size={15} />
            </ToolButton>
          </>,
        ]}
      />

      <div
        ref={readoutRef}
        data-testid="regional-readout"
        className="pointer-events-none absolute bottom-7 right-[5%] z-10 rounded border border-hair bg-panel px-2 py-0.5 num text-2xs text-ink-2"
        aria-live="off"
      >
        —
      </div>
      <div className="pointer-events-none absolute bottom-2 left-[5%] z-10 rounded bg-panel/90 px-2 py-1 text-[10px] font-semibold tracking-wide text-ink-2">
        REGIONAL CONTEXT · Mercator · NOT FOR NAVIGATION
      </div>
      <div className="pointer-events-none absolute bottom-2 right-[5%] z-10 rounded bg-panel/90 px-2 py-1 text-[10px] text-ink-2">
        © Mapbox · © OpenStreetMap contributors · Natural Earth
      </div>
      {context.isLoading && <MapNote title="Loading regional coastline…" />}
      {unavailable && (
        <MapNote
          title="Regional coastline unavailable"
          detail={context.data?.reason ?? context.error?.message ?? 'The map still shows routes, ports and stations.'}
        />
      )}
      {mapError && <MapNote title="Regional map unavailable" detail={mapError} alert />}
      {windError && <MapNote title="Atmospheric wind particles unavailable" detail={windError} alert />}
    </div>
  );
}

function MapNote({ title, detail, alert = false }: { title: string; detail?: string; alert?: boolean }): JSX.Element {
  return (
    <div
      role={alert ? 'alert' : 'status'}
      className="float pointer-events-none absolute bottom-12 left-1/2 z-20 max-w-[min(560px,80%)] -translate-x-1/2 px-3 py-2 text-center text-2xs text-ink-2"
    >
      <strong className={alert ? 'text-warn' : 'text-ink'}>{title}</strong>
      {detail && <div className="mt-0.5">{detail}</div>}
    </div>
  );
}
