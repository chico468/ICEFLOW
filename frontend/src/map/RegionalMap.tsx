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
    RasterSourceSpecification,
  } from 'mapbox-gl';
import type { Feature, FeatureCollection, Geometry, Position } from 'geojson';
import { Globe, Maximize2, Minus, Plus, Wind } from 'lucide-react';
import type { RegionalContext, FlatRing } from '../api/types';
import type { RouteProfileId } from '../api/types';
import type { IcebergProfile, ObservedIceberg } from '../api/types';
import { useEnvironmentLayers, useRegionalContext } from '../api/queries';
import { resolveTileTemplate } from '../api/client';
import { MapToolbar, ToolButton } from '../components/MapToolbar';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { useReducedMotion } from '../hooks/useReducedMotion';
import {
  buildRegionalEnvironmentRequest,
  formatSeaIceValidTime,
  resolveRegionalSeaIceEdgeSelection,
  type RegionalSeaIceSelection,
} from '../lib/regionalSeaIce';
import { latestTick, useAppStore, type VoyagePhase } from '../store/useAppStore';
import { MAX_COUNTRY_LABELS, MAX_MARK_LABELS, countryRankThreshold, showMarkLabel } from './labelPolicy';
import { formatLat, formatLon } from './MapCanvas';
import type { MapEngine, MapScene } from './MapEngine';
import { splitAtAntimeridian, viewOutline, type LonLat, type RegionBounds } from './mercator';
import { BRAND, MAP_COLORS, SHIP_ICON, WIND_PARTITION_COLORS, brandRgba } from './palette';
import { interpolateAlongRoute, interpolateVesselPose, type VesselPose } from './regionalVoyageAnimation';
import { resolveWindBand, type WindBandMatch } from './windBandMatch';

const DEFAULT_REGION: RegionBounds = { lon_min: -30, lon_max: 165, lat_min: -75, lat_max: 40 };
const MAX_RELATIVE_ZOOM = 40;
const PAN_STEP = 80;
const PAN_FAR_STEP = 240;
const MAP_STYLE = 'mapbox://styles/mapbox/standard-satellite';
const WIND_SOURCE_ID = 'iceflow-wind-source';
const WIND_SOURCE_URL = 'mapbox://rasterarrayexamples.gfs-winds';
const WIND_LAYER_ID = 'iceflow-wind-particles';
const WIND_SOURCE_LAYER = '10winds';
/** GFS 10 m wind runs are issued every 6 hours; allow a small tolerance around it. */
const WIND_BAND_TOLERANCE_HOURS = 6;
const SEA_ICE_EDGE_LAYER_ID = 'regional-copernicus-sea-ice-edge-layer';
const SEA_ICE_TILE_SIZE = 256;
const SEA_ICETILE_ERROR_THRESHOLD = 5;
const EMPTY: FeatureCollection = { type: 'FeatureCollection', features: [] };
const REGIONAL_SHIP_ICON = 'regional-ship-icon';
const REGIONAL_SIM_ICEBERG_ICON = 'regional-sim-iceberg-icon';
const REGIONAL_OBS_ICEBERG_ICON = 'regional-obs-iceberg-icon';

type SeaIceRenderStatus =
  | 'loading'
  | 'ready'
  | 'stale'
  | 'unavailable'
  | 'outside_coverage'
  | 'unsupported_time'
  | 'error';

interface ActiveSeaIceSource {
  id: string;
  layerId: string;
  key: string;
}

interface Props {
  scene: MapScene;
  visible: boolean;
  polarEngine: MapEngine | null;
  originId: string;
  destinationId: string;
  toolbarLead?: ReactNode;
  onSelectRouteCandidate: (id: RouteProfileId) => void;
  voyagePhase?: VoyagePhase;
  onPlay?: () => void;
  onPause?: () => void;
  onStep?: () => void;
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

function validCoordinates(latitude: number, longitude: number): boolean {
  return Number.isFinite(latitude) && Number.isFinite(longitude)
    && latitude >= -90 && latitude <= 90 && longitude >= -180 && longitude <= 180;
}

function makeRegionalIcebergs(scene: MapScene): {
  simulated: FeatureCollection<Geometry, { id: string; size: string; length: number; width: number }>;
  observed: FeatureCollection<Geometry, { id: string; size: string; date: string; length: number; width: number }>;
} {
  const simulated = scene.icebergs
    .filter((berg: IcebergProfile) => validCoordinates(
      berg.forecast_latitude ?? berg.latitude,
      berg.forecast_longitude ?? berg.longitude,
    ))
    .map((berg: IcebergProfile) => ({
      type: 'Feature' as const,
      properties: { id: berg.berg_id, size: berg.size_class, length: berg.length_m, width: berg.width_m },
      geometry: {
        type: 'Point' as const,
        coordinates: [berg.forecast_longitude ?? berg.longitude, berg.forecast_latitude ?? berg.latitude],
      },
    }));
  const observed = (scene.observed?.available ? scene.observed.icebergs : [])
    .filter((berg: ObservedIceberg) => validCoordinates(berg.latitude, berg.longitude))
    .map((berg: ObservedIceberg) => ({
      type: 'Feature' as const,
      properties: {
        id: berg.id,
        size: `${berg.length_nm.toFixed(1)} × ${berg.width_nm.toFixed(1)} nm`,
        date: berg.observed_date,
        length: berg.length_nm,
        width: berg.width_nm,
      },
      geometry: { type: 'Point' as const, coordinates: [berg.longitude, berg.latitude] },
    }));
  return { simulated: featureCollection(simulated), observed: featureCollection(observed) };
}

function addRegionalIcons(map: MapboxMap): void {
  const draw = (id: string, observed = false): void => {
    if (map.hasImage(id)) return;
    const canvas = document.createElement('canvas');
    canvas.width = 64;
    canvas.height = 64;
    const ctx = canvas.getContext('2d');
    if (!ctx) return;
    ctx.translate(32, 32);
    ctx.lineJoin = 'round';
    ctx.lineCap = 'round';
    if (id === REGIONAL_SHIP_ICON) {
      ctx.beginPath();
      ctx.arc(0, 0, 27, 0, Math.PI * 2);
      ctx.fillStyle = 'rgba(7, 33, 49, 0.28)';
      ctx.fill();
      ctx.beginPath();
      ctx.moveTo(0, -27);
      ctx.lineTo(11, -8);
      ctx.lineTo(10, 17);
      ctx.lineTo(0, 25);
      ctx.lineTo(-10, 17);
      ctx.lineTo(-11, -8);
      ctx.closePath();
      ctx.fillStyle = SHIP_ICON.hullFill;
      ctx.fill();
      ctx.strokeStyle = SHIP_ICON.hullStroke;
      ctx.lineWidth = 3.5;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(0, -20);
      ctx.lineTo(0, 13);
      ctx.strokeStyle = SHIP_ICON.centerline;
      ctx.lineWidth = 3;
      ctx.stroke();
      ctx.beginPath();
      ctx.moveTo(-6, 15);
      ctx.lineTo(6, 15);
      ctx.strokeStyle = SHIP_ICON.hatch;
      ctx.lineWidth = 3;
      ctx.stroke();
    } else {
      // Faceted iceberg silhouette rather than the generic diamond used by the Polar canvas.
      ctx.beginPath();
      ctx.moveTo(0, -24);
      ctx.lineTo(7, -12);
      ctx.lineTo(19, -14);
      ctx.lineTo(13, -2);
      ctx.lineTo(23, 12);
      ctx.lineTo(11, 20);
      ctx.lineTo(-17, 19);
      ctx.lineTo(-24, 10);
      ctx.lineTo(-14, 2);
      ctx.lineTo(-17, -8);
      ctx.lineTo(-5, -5);
      ctx.closePath();
      ctx.fillStyle = observed ? 'rgba(235, 250, 255, 0.96)' : 'rgba(165, 226, 242, 0.96)';
      ctx.fill();
      ctx.strokeStyle = observed ? MAP_COLORS.iceEdge : MAP_COLORS.regionalBergSim;
      ctx.lineWidth = observed ? 3 : 2.5;
      if (observed) ctx.setLineDash([4, 3]);
      ctx.stroke();
      ctx.setLineDash([]);
      ctx.beginPath();
      ctx.moveTo(-6, -4);
      ctx.lineTo(0, -16);
      ctx.lineTo(4, -2);
      ctx.lineTo(13, -8);
      ctx.moveTo(-7, 5);
      ctx.lineTo(2, 13);
      ctx.lineTo(11, 4);
      ctx.strokeStyle = observed ? 'rgba(27, 106, 156, 0.75)' : 'rgba(8, 69, 94, 0.75)';
      ctx.lineWidth = 2;
      ctx.stroke();
    }
    map.addImage(id, ctx.getImageData(0, 0, canvas.width, canvas.height), { pixelRatio: 2 });
  };
  draw(REGIONAL_SHIP_ICON);
  draw(REGIONAL_SIM_ICEBERG_ICON);
  draw(REGIONAL_OBS_ICEBERG_ICON, true);
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

function updateVesselSource(map: MapboxMap, pose: VesselPose | null, enabled: boolean): void {
  updateSource(
    map,
    'regional-vessel',
    enabled && pose
      ? featureCollection([
          {
            type: 'Feature',
            properties: { heading: pose.heading },
            geometry: { type: 'Point', coordinates: [pose.longitude, pose.latitude] },
          },
        ])
      : EMPTY,
  );
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
              WIND_PARTITION_COLORS[0],
              3,
              WIND_PARTITION_COLORS[1],
              7,
              WIND_PARTITION_COLORS[2],
              12,
              WIND_PARTITION_COLORS[3],
              20,
              WIND_PARTITION_COLORS[4],
              32,
              WIND_PARTITION_COLORS[5],
              50,
              WIND_PARTITION_COLORS[6],
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

function syncSeaIceLayers(
  map: MapboxMap,
  selection: RegionalSeaIceSelection,
  activeSources: { current: ActiveSeaIceSource[] },
): SeaIceRenderStatus {
  if (!hasLoadedStyle(map)) return 'loading';

  const desiredLayers = [
    {
      id: 'regional-copernicus-sea-ice-edge-source',
      layerId: SEA_ICE_EDGE_LAYER_ID,
      tileTemplate: selection.tileTemplate,
      maxZoom: selection.maxZoom,
    },
  ];
  if (desiredLayers.some((layer) => !layer.tileTemplate || layer.maxZoom === null)) {
    for (const source of activeSources.current) {
      if (map.getLayer(source.layerId)) map.removeLayer(source.layerId);
      if (map.getSource(source.id)) map.removeSource(source.id);
    }
    activeSources.current = [];
    return 'unavailable';
  }

  const expectedSources = desiredLayers.map((layer) => ({
    id: layer.id,
    layerId: layer.layerId,
    key: `${layer.tileTemplate}|${layer.maxZoom}`,
  }));
  const existingMatches = expectedSources.length === activeSources.current.length
    && expectedSources.every((expected) => {
      const active = activeSources.current.find((source) => source.id === expected.id);
      return active?.key === expected.key
        && map.getSource(expected.id)
        && map.getLayer(expected.layerId);
    });
  if (existingMatches) {
    if (expectedSources.some((source) => !map.isSourceLoaded(source.id))) return 'loading';
    return selection.status === 'stale' ? 'stale' : 'ready';
  }

  for (const source of activeSources.current) {
    if (map.getLayer(source.layerId)) map.removeLayer(source.layerId);
    if (map.getSource(source.id)) map.removeSource(source.id);
  }
  activeSources.current = [];

  for (const item of desiredLayers) {
    const { tileTemplate, maxZoom, id, layerId } = item;
    if (!tileTemplate || maxZoom === null) continue;
    // Resolve the same-origin tile template. When VITE_API_BASE_URL is set the relative path is
    // qualified with that origin; otherwise it routes through the Vite dev proxy / same-origin host.
    const resolvedTileTemplate = resolveTileTemplate(tileTemplate) ?? tileTemplate;
    const source: RasterSourceSpecification = {
      type: 'raster',
      tiles: [resolvedTileTemplate],
      tileSize: SEA_ICE_TILE_SIZE,
      maxzoom: maxZoom,
    };
    map.addSource(id, source);
    map.addLayer(
      {
        id: layerId,
        type: 'raster',
        source: id,
        slot: 'bottom',
        paint: {
          'raster-opacity': 0.82,
          'raster-fade-duration': 0,
          'raster-resampling': 'linear',
        },
      },
      map.getLayer(WIND_LAYER_ID) ? WIND_LAYER_ID : undefined,
    );
    activeSources.current.push({
      id,
      layerId,
      key: `${tileTemplate}|${maxZoom}`,
    });
  }
  return 'loading';
}

function addLayers(map: MapboxMap, windEnabled: boolean, onWindError: (reason: string) => void): boolean {
  const windLayerAdded = addWindParticles(map, windEnabled, onWindError);
  addRegionalIcons(map);
  addGeoJSONSourceIfMissing(map, 'regional-land');
  addGeoJSONSourceIfMissing(map, 'regional-countries');
  addGeoJSONSourceIfMissing(map, 'regional-country-labels');
  addGeoJSONSourceIfMissing(map, 'regional-lines');
  addGeoJSONSourceIfMissing(map, 'regional-marks');
  addGeoJSONSourceIfMissing(map, 'regional-mark-labels');
  addGeoJSONSourceIfMissing(map, 'regional-vessel');
  addGeoJSONSourceIfMissing(map, 'regional-simulated-icebergs');
  addGeoJSONSourceIfMissing(map, 'regional-observed-icebergs');
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
    paint: { 'line-color': BRAND.accent, 'line-width': 1.6, 'line-dasharray': [3, 2], 'line-opacity': 0.95 },
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
         BRAND['ink-2'],
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
      'circle-stroke-color': ['case', ['get', 'endpoint'], BRAND.ink, brandRgba(BRAND['on-accent'], 0.9)],
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
      'circle-stroke-color': ['case', ['get', 'endpoint'], BRAND.ink, brandRgba(BRAND['on-accent'], 0.9)],
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
      'text-color': BRAND.ink,
      'text-halo-color': brandRgba(BRAND['on-accent'], 0.9),
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
    paint: { 'text-color': brandRgba(BRAND.ink, 0.58) },
  });
  addLayerIfMissing(map, {
    id: 'regional-simulated-icebergs',
    type: 'symbol',
    source: 'regional-simulated-icebergs',
    layout: {
      'icon-image': REGIONAL_SIM_ICEBERG_ICON,
      'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.38, 4, 0.62, 9, 0.82, 14, 0.9],
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
      'icon-rotation-alignment': 'viewport',
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-observed-icebergs',
    type: 'symbol',
    source: 'regional-observed-icebergs',
    layout: {
      'icon-image': REGIONAL_OBS_ICEBERG_ICON,
      'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.42, 4, 0.66, 9, 0.86, 14, 0.94],
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
      'icon-rotation-alignment': 'viewport',
    },
  });
  addLayerIfMissing(map, {
    id: 'regional-vessel',
    type: 'symbol',
    source: 'regional-vessel',
    layout: {
      'icon-image': REGIONAL_SHIP_ICON,
      'icon-size': ['interpolate', ['linear'], ['zoom'], 0, 0.48, 4, 0.72, 9, 0.88, 14, 0.94],
      'icon-rotate': ['get', 'heading'],
      'icon-rotation-alignment': 'map',
      'icon-pitch-alignment': 'map',
      'icon-allow-overlap': true,
      'icon-ignore-placement': true,
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
      'text-color': BRAND.accent,
      'text-halo-color': brandRgba(BRAND['on-accent'], 0.9),
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

function hasLoadedStyle(map: MapboxMap): boolean {
  return map.getStyle().version === 8;
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

interface WindSourceMeta {
  name: string | null;
  units: string | null;
  range: [number, number] | null;
  jobid: string | null;
  bands: string[];
}

/**
 * The GFS raster-array tileset advertises its available timestamps as band ids in its
 * TileJSON. The particle layer selects one of those bands with `raster-particle-array-band`,
 * so the band that matches ICEFLOW's environmental target time has to be resolved before the
 * layer is painted. Bands are read from the TileJSON, never assumed.
 */
async function fetchWindSourceMeta(
  map: MapboxMap,
  sourceId: string,
  token: string,
): Promise<WindSourceMeta | null> {
  const source = map.getSource(sourceId) as
    | (RasterArraySourceSpecification & { url?: string; tiles?: string[] })
    | undefined;
  if (!source) return null;
  const tilejsonUrl = typeof source.url === 'string' && source.url.endsWith('.json')
    ? source.url
    : (source.tiles?.[0]?.replace(/{z}\/{x}\/{y}\.mrt$/, 'json') ?? null);
  if (!tilejsonUrl) return null;
  try {
    const response = await fetch(`${tilejsonUrl}${tilejsonUrl.includes('?') ? '&' : '?'}access_token=${encodeURIComponent(token)}`);
    if (!response.ok) return null;
    const tilejson = await response.json() as {
      name?: string;
      raster_layers?: Array<{
        fields?: { bands?: string[]; units?: string; range?: [number, number] };
        id?: string;
      }>;
      rasterarray_job_id?: string;
    };
    const layer = tilejson.raster_layers?.find((entry) => entry.id === WIND_SOURCE_LAYER)
      ?? tilejson.raster_layers?.[0];
    const bands = Array.isArray(layer?.fields?.bands)
      ? layer.fields.bands.filter((value): value is string => typeof value === 'string')
      : [];
    return {
      name: tilejson.name ?? null,
      units: layer?.fields?.units ?? null,
      range: Array.isArray(layer?.fields?.range) && layer.fields.range.length === 2
        ? [layer.fields.range[0], layer.fields.range[1]]
        : null,
      jobid: tilejson.rasterarray_job_id ?? null,
      bands,
    };
  } catch {
    return null;
  }
}

/**
 * Apply a resolved band match to the particle layer. Returns the paint property name used so
 * callers can decide whether a re-paint is needed.
 */
function applyWindBand(map: MapboxMap, layerId: string, match: WindBandMatch | null): boolean {
  if (!map.getLayer(layerId)) return false;
  if (match?.band) {
    map.setPaintProperty(layerId, 'raster-particle-array-band', match.band);
  } else {
    map.setPaintProperty(layerId, 'raster-particle-array-band', '0');
  }
  return true;
}

export function RegionalMap({
  scene,
  visible,
  polarEngine,
  originId,
  destinationId,
  toolbarLead,
  onSelectRouteCandidate,
  voyagePhase,
  onPlay,
  onPause,
  onStep,
}: Props): JSX.Element {
  const hostRef = useRef<HTMLDivElement>(null);
  const mapContainerRef = useRef<HTMLDivElement>(null);
  const readoutRef = useRef<HTMLDivElement>(null);
  const mapRef = useRef<MapboxMap | null>(null);
  const pointerPointRef = useRef<[number, number] | null>(null);
  const windEnabledRef = useRef(false);
  const baseZoomRef = useRef(0);
  const fittedKeyRef = useRef('');
  const regionKeyRef = useRef('');
  const reducedMotion = useReducedMotion();
  const context = useRegionalContext();
  const data = context.data;
  const voyage = useAppStore((state) => state.voyage);
  const storedVoyagePhase = useAppStore((state) => state.voyagePhase);
  const effectiveVoyagePhase = voyagePhase ?? storedVoyagePhase;
  const ticks = useAppStore((state) => state.ticks);
  const intervalMs = useAppStore((state) => state.intervalMs);
  const plan = useAppStore((state) => state.plan);
  const leadHours = useAppStore((state) => state.leadHours);
  const latestVoyageTick = latestTick(ticks);
  const displayedVesselRef = useRef<VesselPose | null>(null);
  const previousVesselTargetRef = useRef<VesselPose | null>(null);
  const vesselAnimationRef = useRef<{
    from: VesselPose; to: VesselPose; startedAt: number; duration: number;
  } | null>(null);
  const vesselFrameRef = useRef<number | null>(null);
  const [selectedIceberg, setSelectedIceberg] = useState<{
    kind: 'observed' | 'simulated'; id: string; size: string; date?: string; x: number; y: number;
  } | null>(null);
  const [planningReferenceIso] = useState(() => new Date().toISOString());
  const [windBandMatch, setWindBandMatch] = useState<WindBandMatch | null>(null);
  const [windSourceMeta, setWindSourceMeta] = useState<WindSourceMeta | null>(null);
  const [windBandError, setWindBandError] = useState<string | null>(null);
  const environmentRequestResult = useMemo(() => {
    try {
      return {
        request: buildRegionalEnvironmentRequest({
          voyage,
          tick: latestVoyageTick,
          plan,
          leadHours,
          planningReferenceIso,
        }),
        error: null,
      };
    } catch (error) {
      return {
        request: null,
        error: error instanceof Error ? error.message : 'Unable to resolve the environmental target time.',
      };
    }
  }, [voyage, latestVoyageTick, plan, leadHours, planningReferenceIso]);
  const environmentLayers = useEnvironmentLayers(
    environmentRequestResult.request,
    visible && environmentRequestResult.error === null,
  );
  const seaIceSelection = useMemo(
    () => resolveRegionalSeaIceEdgeSelection(environmentLayers.data),
    [environmentLayers.data],
  );
  const region = data?.region ?? DEFAULT_REGION;
  const regionKey = `${region.lon_min},${region.lon_max},${region.lat_min},${region.lat_max}`;
  const [mapReady, setMapReady] = useState(false);
  const [mapView, setMapView] = useState<{ zoom: number; centre: string } | null>(null);
  const [windParticlesEnabled, setWindParticlesEnabled] = useState(false);
  const [windSourceStatus, setWindSourceStatus] = useState<'loading' | 'ready' | 'error'>('loading');
  const [windLayerPresent, setWindLayerPresent] = useState(false);
  const [windError, setWindError] = useState<string | null>(null);
  const [seaIceRenderStatus, setSeaIceRenderStatus] = useState<SeaIceRenderStatus>('loading');
  const [seaIceTileError, setSeaIceTileError] = useState<string | null>(null);
  const seaIceErrorCountRef = useRef(0);
  const seaIceDisabledRef = useRef(false);
  const seaIceDisabledTemplateRef = useRef<string | null>(null);
  const windErrorRef = useRef<string | null>(null);
  const seaIceSelectionRef = useRef(seaIceSelection);
  const activeSeaIceSourceRef = useRef<ActiveSeaIceSource[]>([]);
  seaIceSelectionRef.current = seaIceSelection;
  const selectCandidateRef = useRef(onSelectRouteCandidate);
  selectCandidateRef.current = onSelectRouteCandidate;
  windEnabledRef.current = windParticlesEnabled;

  const routePoints = useMemo(
    () => scene.optimisedRoute.map((point) => ({ lat: point.latitude, lon: point.longitude })),
    [scene.optimisedRoute],
  );
  const routeAnimationPoints = useMemo(
    () => scene.optimisedRoute
      .map((point) => ({ latitude: point.latitude, longitude: point.longitude }))
      .filter((point) => validCoordinates(point.latitude, point.longitude)),
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

  const reportMapFailure = useCallback((reason: string): void => {
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim() ?? '';
    const safeReason = safeMapDiagnostic(
      reason.trim() || 'Mapbox reported a resource error without a diagnostic message.',
      token,
    );
    if (import.meta.env.DEV) console.error(`[RegionalMap] Mapbox resource error: ${safeReason}`);
  }, []);

  const handleSeaIceTileError = useCallback((reason: string): void => {
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim() ?? '';
    const safeReason = safeMapDiagnostic(
      reason.trim() || 'The Copernicus WMTS overlay tile failed to load.',
      token,
    );
    seaIceErrorCountRef.current += 1;
    if (seaIceErrorCountRef.current >= SEA_ICETILE_ERROR_THRESHOLD) {
      // Mapbox re-requests a failed raster tile on every rendered frame. The wind particle layer
      // keeps the map rendering continuously, so without a backstop a CORS or 429 failure becomes a
      // per-frame request storm to the tile endpoint. After N consecutive failures, remove the
      // source so it stops being requested; it is only restored when the selected observation
      // changes (which changes its tile template).
      if (!seaIceDisabledRef.current) {
        seaIceDisabledRef.current = true;
        const map = mapRef.current;
        if (map) {
          for (const source of activeSeaIceSourceRef.current) {
            if (map.getLayer(source.layerId)) map.removeLayer(source.layerId);
            if (map.getSource(source.id)) map.removeSource(source.id);
          }
        }
        activeSeaIceSourceRef.current = [];
        setSeaIceTileError(`Sea-ice overlay unavailable (${safeReason}). Tiles are no longer being requested.`);
        setSeaIceRenderStatus('unavailable');
        // Log once per disable event, not once per failed tile.
        if (import.meta.env.DEV) console.error(`[RegionalMap] Sea-ice overlay disabled after ${SEA_ICETILE_ERROR_THRESHOLD} consecutive tile errors: ${safeReason}`);
      }
      return;
    }
    setSeaIceTileError(safeReason);
    setSeaIceRenderStatus('error');
  }, []);

  const syncSeaIce = useCallback((map: MapboxMap): void => {
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim() ?? '';
    const selection = seaIceSelectionRef.current;
    // While a source is disabled by repeated failures, keep it suppressed for the same selection
    // and re-attempt only when the selected observation (and therefore its tile template) changes.
    if (seaIceDisabledRef.current && seaIceDisabledTemplateRef.current === selection.tileTemplate) {
      return;
    }
    try {
      setSeaIceTileError(null);
      seaIceErrorCountRef.current = 0;
      if (seaIceDisabledRef.current) {
        seaIceDisabledRef.current = false;
      }
      const status = syncSeaIceLayers(map, selection, activeSeaIceSourceRef);
      setSeaIceRenderStatus(status);
      seaIceDisabledTemplateRef.current = selection.tileTemplate ?? null;
    } catch (error) {
      const reason = error instanceof Error ? error.message : 'Unknown Copernicus tile error.';
      setSeaIceTileError(safeMapDiagnostic(reason, token));
      setSeaIceRenderStatus('error');
      for (const source of activeSeaIceSourceRef.current) {
        if (map.getLayer(source.layerId)) map.removeLayer(source.layerId);
        if (map.getSource(source.id)) map.removeSource(source.id);
      }
      activeSeaIceSourceRef.current = [];
    }
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
      const icebergs = makeRegionalIcebergs(latest.scene);
      updateSource(map, 'regional-simulated-icebergs', latest.scene.layers.icebergs ? icebergs.simulated : EMPTY);
      updateSource(map, 'regional-observed-icebergs', latest.scene.layers.observedBergs ? icebergs.observed : EMPTY);
      const tickVessel = latest.scene.vessel
        ? { latitude: latest.scene.vessel.lat, longitude: latest.scene.vessel.lon, heading: latest.scene.vessel.heading }
        : null;
      updateVesselSource(map, displayedVesselRef.current ?? tickVessel, latest.scene.layers.vessel);
      updateSource(map, 'regional-polar-outline', makePolarOutline(latest.polarEngine));
      updateSource(map, 'regional-polar-label', makePolarLabel(latest.polarEngine));
      map.setLayoutProperty('regional-baseline-route', 'visibility', latest.scene.layers.baselineRoute ? 'visible' : 'none');
      map.setLayoutProperty('regional-optimized-route', 'visibility', latest.scene.layers.optimisedRoute ? 'visible' : 'none');
      map.setLayoutProperty('regional-track', 'visibility', latest.scene.layers.track ? 'visible' : 'none');
      map.setLayoutProperty('regional-vessel', 'visibility', latest.scene.layers.vessel ? 'visible' : 'none');
      map.setLayoutProperty('regional-simulated-icebergs', 'visibility', latest.scene.layers.icebergs ? 'visible' : 'none');
      map.setLayoutProperty('regional-observed-icebergs', 'visibility', latest.scene.layers.observedBergs ? 'visible' : 'none');
    },
    [],
  );

  useEffect(() => {
    const container = mapContainerRef.current;
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim();
    if (!visible || mapRef.current || !container) return undefined;
    if (!token) {
      reportMapFailure('Mapbox is not configured. Set VITE_MAPBOX_ACCESS_TOKEN to enable the regional map.');
      return undefined;
    }

    let cancelled = false;
    const initialize = async (): Promise<void> => {
      const [mapbox, _style] = await Promise.all([import('mapbox-gl'), import('mapbox-gl/dist/mapbox-gl.css')]);
      if (cancelled || !mapContainerRef.current) return;
      const mapboxgl = mapbox.default;
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
        addRegionalLayers();
        syncSeaIce(map);
        updateMapData(map);
      });
      map.on('sourcedata', (event) => {
        if (event.sourceId === WIND_SOURCE_ID) {
          if (event.sourceDataType === 'error') {
            reportWindFailure(`Mapbox reported an error loading raster-array source ${WIND_SOURCE_ID}.`);
          } else if (event.sourceDataType === 'content' && event.isSourceLoaded) {
            windErrorRef.current = null;
            setWindSourceStatus((status) => status === 'error' ? status : 'ready');
            setWindError(null);
          }
          return;
        }
        if (activeSeaIceSourceRef.current.some((source) => source.id === event.sourceId)) {
          if (event.sourceDataType === 'error') {
            handleSeaIceTileError('The Copernicus WMTS overlay tile failed to load.');
          } else if (
            event.isSourceLoaded
            && event.sourceDataType !== 'metadata'
            && event.sourceDataType !== 'visibility'
          ) {
            // A successfully loaded tile resets the consecutive-error counter so a one-off blip
            // does not trip the disable backstop.
            seaIceErrorCountRef.current = 0;
            setSeaIceRenderStatus(
              seaIceSelectionRef.current.status === 'stale' ? 'stale' : 'ready',
            );
            setSeaIceTileError(null);
          }
        }
      });
      map.on('error', (event) => {
        const message = event.error.message || 'Mapbox reported a resource error without a diagnostic message.';
        const eventSourceId = 'sourceId' in event && typeof event.sourceId === 'string'
          ? event.sourceId
          : null;
        if (
          activeSeaIceSourceRef.current.some(
            (source) => source.id === eventSourceId || message.includes(source.id),
          )
        ) {
          handleSeaIceTileError(message);
          return;
        }
        if ([WIND_SOURCE_ID, WIND_LAYER_ID, WIND_SOURCE_URL, 'raster-array', 'raster-particle'].some((key) => message.includes(key))) {
          reportWindFailure(message);
          return;
        }
        reportMapFailure(message);
      });

      const onLoad = (): void => {
        addRegionalLayers();
        syncSeaIce(map);
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
        const selectIceberg = (kind: 'observed' | 'simulated') => (event: import('mapbox-gl').MapMouseEvent & { features?: import('geojson').Feature[] }): void => {
          const properties = event.features?.[0]?.properties;
          if (!properties) return;
          const mapRect = mapContainerRef.current?.getBoundingClientRect();
          const hostRect = hostRef.current?.getBoundingClientRect();
          setSelectedIceberg({
            kind,
            id: String(properties.id ?? 'Unknown'),
            size: String(properties.size ?? 'Size unavailable'),
            ...(kind === 'observed' ? { date: String(properties.date ?? 'Date unavailable') } : {}),
            x: event.point.x + (mapRect && hostRect ? mapRect.left - hostRect.left : 0),
            y: event.point.y + (mapRect && hostRect ? mapRect.top - hostRect.top : 0),
          });
        };
        map.on('click', 'regional-simulated-icebergs', selectIceberg('simulated'));
        map.on('click', 'regional-observed-icebergs', selectIceberg('observed'));
        for (const layer of ['regional-simulated-icebergs', 'regional-observed-icebergs']) {
          map.on('mouseenter', layer, () => { map.getCanvasContainer().style.cursor = 'pointer'; });
          map.on('mouseleave', layer, () => { map.getCanvasContainer().style.cursor = ''; });
        }
        map.on('movestart', () => setSelectedIceberg(null));
        map.doubleClickZoom.disable();
        map.on('dblclick', (event) => {
          map.easeTo({ zoom: Math.min(map.getMaxZoom(), map.getZoom() + 1),
            around: event.lngLat,
            duration: 0,
          });
          updateMapData(map);
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
          updateMapData(map);
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

      map.on('load', onLoad);
    };
    void initialize().catch((error: unknown) => {
      if (!cancelled) {
        reportMapFailure(
          error instanceof Error
            ? `Unable to initialize Mapbox: ${error.message}`
            : 'Unable to initialize Mapbox due to an unknown error.',
        );
      }
    });
    return () => {
      cancelled = true;
    };
  }, [visible, updateMapData, reportWindFailure, reportMapFailure, syncSeaIce]);

  useEffect(
    () => () => {
      if (vesselFrameRef.current !== null) cancelAnimationFrame(vesselFrameRef.current);
      const map = mapRef.current;
      map?.remove();
      mapRef.current = null;
    },
    [],
  );

  useEffect(() => {
    const map = mapRef.current;
    if (!visible || !map || !mapReady || !hasLoadedStyle(map)) return;
    syncSeaIce(map);
  }, [visible, mapReady, seaIceSelection, syncSeaIce]);

  useEffect(() => {
    let target: VesselPose | null = latestVoyageTick
      ? {
        latitude: latestVoyageTick.latitude,
        longitude: latestVoyageTick.longitude,
        heading: latestVoyageTick.heading_deg,
      }
      : scene.vessel
        ? { latitude: scene.vessel.lat, longitude: scene.vessel.lon, heading: scene.vessel.heading }
        : null;

    // Prefer route-following animation along the selected/optimised route when available
    if (target && routeAnimationPoints.length >= 2 && typeof latestVoyageTick?.progress_percent === 'number') {
      const progress = Math.max(0, Math.min(1, latestVoyageTick.progress_percent / 100));
      const along = interpolateAlongRoute(routeAnimationPoints, progress);
      if (along) {
        target = along;
      }
    }

    const previous = previousVesselTargetRef.current;
    if (!target) {
      previousVesselTargetRef.current = null;
      displayedVesselRef.current = null;
      vesselAnimationRef.current = null;
      const map = mapRef.current;
      if (map) updateVesselSource(map, null, scene.layers.vessel);
      if (hostRef.current) {
        delete hostRef.current.dataset.vesselLatitude;
        delete hostRef.current.dataset.vesselLongitude;
      }
      return;
    }

    const moved = previous && (
      previous.latitude !== target.latitude
      || previous.longitude !== target.longitude
      || previous.heading !== target.heading
    );
    if (!previous || !moved || !latestRef.current.visible || reducedMotion || effectiveVoyagePhase === 'paused') {
      if (!previous || moved || !displayedVesselRef.current) displayedVesselRef.current = target;
      vesselAnimationRef.current = null;
      const map = mapRef.current;
      if (map) updateVesselSource(map, displayedVesselRef.current, scene.layers.vessel);
      if (hostRef.current && displayedVesselRef.current) {
        hostRef.current.dataset.vesselLatitude = displayedVesselRef.current.latitude.toFixed(5);
        hostRef.current.dataset.vesselLongitude = displayedVesselRef.current.longitude.toFixed(5);
      }
    } else {
      const from = displayedVesselRef.current ?? previous;
      vesselAnimationRef.current = {
        from,
        to: target,
        startedAt: performance.now(),
        duration: Math.max(160, Math.min(intervalMs, 1200)),
      };
    }
    previousVesselTargetRef.current = target;

    if (vesselFrameRef.current !== null) cancelAnimationFrame(vesselFrameRef.current);
    const animate = (now: number): void => {
      const animation = vesselAnimationRef.current;
      if (!animation || effectiveVoyagePhase === 'paused') {
        vesselFrameRef.current = null;
        return;
      }
      const progress = Math.min(1, (now - animation.startedAt) / animation.duration);
      const eased = progress * progress * (3 - 2 * progress);
      const pose = interpolateVesselPose(animation.from, animation.to, eased);
      displayedVesselRef.current = pose;
      const map = mapRef.current;
      if (map) updateVesselSource(map, pose, latestRef.current.scene.layers.vessel);
      if (hostRef.current) {
        hostRef.current.dataset.vesselLatitude = pose.latitude.toFixed(5);
        hostRef.current.dataset.vesselLongitude = pose.longitude.toFixed(5);
      }
      if (progress >= 1) {
        vesselAnimationRef.current = null;
        vesselFrameRef.current = null;
      } else {
        vesselFrameRef.current = requestAnimationFrame(animate);
      }
    };
    if (vesselAnimationRef.current && effectiveVoyagePhase !== 'paused') vesselFrameRef.current = requestAnimationFrame(animate);
  }, [latestVoyageTick, scene.vessel, scene.layers.vessel, intervalMs, reducedMotion, routeAnimationPoints, effectiveVoyagePhase]);

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

  /**
   * The particle layer must show the wind field that is valid at ICEFLOW's environmental
   * target time, not the current wall-clock moment. The GFS tileset advertises its available
   * timestamps as band ids in its TileJSON, so we resolve the matching band whenever the
   * reference time or the advertised bands change. When no suitable band exists we surface an
   * explicit stale/unavailable state instead of silently falling back to an unrelated band.
   */
  useEffect(() => {
    const map = mapRef.current;
    if (!map || !mapReady || !map.isStyleLoaded() || !map.getLayer(WIND_LAYER_ID)) return;
    if (!windParticlesEnabled) return;
    const token = import.meta.env.VITE_MAPBOX_ACCESS_TOKEN?.trim() ?? '';
    if (!token) return;

    let cancelled = false;
    const run = async (): Promise<void> => {
      const meta = await fetchWindSourceMeta(map, WIND_SOURCE_ID, token);
      if (cancelled) return;
      if (!meta) {
        setWindBandError('The GFS wind tileset did not advertise its available timestamps.');
        setWindBandMatch(null);
        setWindSourceMeta(null);
        applyWindBand(map, WIND_LAYER_ID, null);
        return;
      }
      setWindSourceMeta(meta);
      const referenceTime = environmentLayers.data?.target_time_utc ?? null;
      const match = resolveWindBand(referenceTime, meta.bands, WIND_BAND_TOLERANCE_HOURS);
      if (cancelled) return;
      setWindBandMatch(match);
      setWindBandError(match.reason);
      applyWindBand(map, WIND_LAYER_ID, match);
    };
    void run().catch(() => {
      if (!cancelled) {
        setWindBandError('Could not resolve the GFS wind timestamp bands.');
        setWindBandMatch(null);
      }
    });
    return () => { cancelled = true; };
  }, [mapReady, windParticlesEnabled, environmentLayers.data?.target_time_utc]);

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
        { padding: 90, duration: 0, maxZoom: baseZoomRef.current + Math.log2(16) },
      );
    } else if (initialPoints.length === 1) {
      map.flyTo({
        center: [initialPoints[0].lon, initialPoints[0].lat],
        zoom: baseZoomRef.current + 2,
        duration: 0,
      });
    }
    updateMapData(map);
  }, [mapReady, initialKey, initialPoints, reducedMotion]);

  const fitInitial = useCallback((): void => {
    const map = mapRef.current;
    if (!map || initialPoints.length === 0) return;
    if (initialPoints.length === 1) {
      map.flyTo({
        center: [initialPoints[0].lon, initialPoints[0].lat],
        zoom: baseZoomRef.current + 2,
        duration: 0,
      });
      updateMapData(map);
      return;
    }
    const longitudes = initialPoints.map((point) => point.lon);
    const latitudes = initialPoints.map((point) => point.lat);
    map.fitBounds(
      [
        [Math.min(...longitudes), Math.min(...latitudes)],
        [Math.max(...longitudes), Math.max(...latitudes)],
      ],
      { padding: 90, duration: 0, maxZoom: baseZoomRef.current + Math.log2(16) },
    );
    updateMapData(map);
  }, [initialPoints, reducedMotion]);

  const showWholeRegion = useCallback((): void => {
    const map = mapRef.current;
    if (map) map.fitBounds(
      [
        [region.lon_min, region.lat_min],
        [region.lon_max, region.lat_max],
      ],
      { padding: 24, duration: 0 },
    );
    if (map) updateMapData(map);
  }, [region, reducedMotion]);

  const onKeyDown = (event: KeyboardEvent<HTMLDivElement>): void => {
    const map = mapRef.current;
    if (!map || event.altKey || event.ctrlKey || event.metaKey) return;
    const target = event.target;
    if (target !== hostRef.current && target !== map.getCanvas()) return;
    const pan = event.shiftKey ? PAN_FAR_STEP : PAN_STEP;
    switch (event.key) {
      case 'ArrowLeft': map.panBy([-pan, 0], { duration: 0 }); break;
      case 'ArrowRight': map.panBy([pan, 0], { duration: 0 }); break;
      case 'ArrowUp': map.panBy([0, -pan], { duration: 0 }); break;
      case 'ArrowDown': map.panBy([0, pan], { duration: 0 }); break;
      case '+':
      case '=': map.zoomTo(map.getZoom() + Math.log2(1.5), { duration: 0 }); break;
      case '-':
      case '_': map.zoomTo(map.getZoom() - Math.log2(1.5), { duration: 0 }); break;
      case '0':
      case 'Home': fitInitial(); break;
      case 'f':
      case 'F': showWholeRegion(); break;
      default: return;
    }
    updateMapData(map);
    event.preventDefault();
  };

  const unavailable = context.isError || (data && !data.available);
  const seaIceStatus: SeaIceRenderStatus =
    environmentRequestResult.error || environmentLayers.isError || seaIceTileError
      ? 'error'
      : !environmentRequestResult.request || environmentLayers.isLoading
        ? 'loading'
        : !environmentLayers.data
          ? 'unavailable'
          : seaIceSelection.tileTemplate
            ? seaIceRenderStatus
            : seaIceSelection.status;
  const seaIceStatusText = seaIceStatus === 'loading'
    ? 'Loading paired Copernicus observations…'
    : seaIceStatus === 'stale'
      ? `STALE OBSERVATION · ${formatSeaIceValidTime(seaIceSelection.validTimeUtc)}`
      : seaIceStatus === 'ready'
        ? `Observation · ${formatSeaIceValidTime(seaIceSelection.validTimeUtc)}`
        : seaIceStatus === 'error'
          ? environmentRequestResult.error
            ?? environmentLayers.error?.message
            ?? seaIceTileError
            ?? 'Copernicus sea-ice tiles could not be loaded.'
          : seaIceStatus === 'outside_coverage'
          ? 'Outside source coverage'
            : seaIceStatus === 'unsupported_time'
            ? 'Unsupported time'
            : `${seaIceSelection.sourceStatus === 'stale' ? 'STALE SOURCE OBSERVATION · ' : ''}Unavailable`;
  const zoomIn = (): void => {
    const map = mapRef.current;
    if (map) {
      const targetZoom = map.getZoom() + Math.log2(1.5);
      map.zoomTo(targetZoom, { duration: 0 });
      updateMapData(map);
    }
  };
  const zoomOut = (): void => {
    const map = mapRef.current;
    if (map) {
      map.zoomTo(map.getZoom() - Math.log2(1.5), { duration: 0 });
      updateMapData(map);
    }
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
        data-wind-band={windBandMatch?.band ?? undefined}
        data-wind-band-exact={windBandMatch ? String(windBandMatch.exact) : undefined}
        data-wind-band-offset-hours={windBandMatch?.offsetHours ?? undefined}
        data-wind-band-source={windSourceMeta?.name ?? undefined}
        data-wind-band-units={windSourceMeta?.units ?? undefined}
        data-wind-band-count={windSourceMeta?.bands.length ?? undefined}
      data-regional-sea-ice-status={seaIceStatus}
      data-regional-sea-ice-valid-time={seaIceSelection.validTimeUtc ?? undefined}
      data-regional-sea-ice-target-time={seaIceSelection.targetTimeUtc ?? undefined}
      data-regional-voyage-phase={effectiveVoyagePhase}
      data-regional-vessel-present={scene.vessel ? 'true' : 'false'}
      data-regional-route-endpoints-ready={scene.ports.length > 0 && scene.stations.length > 0 ? 'true' : 'false'}
      data-regional-simulated-iceberg-count={scene.layers.icebergs ? scene.icebergs.length : 0}
      data-regional-observed-iceberg-count={scene.layers.observedBergs && scene.observed?.available ? scene.observed.icebergs.length : 0}
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
              hint="GFS atmospheric wind velocity; not sea-ice drift or ocean currents. Off by default."
              onClick={() => setWindParticlesEnabled((enabled) => !enabled)}
              pressed={windParticlesEnabled}
              disabled={!windLayerPresent}
            >
              <Wind size={15} />
            </ToolButton>
            <ProvenanceBadge status="forecast" size="sm" showIcon={false} title="Wind particles come from the GFS model, not observation" />
          </>,
        ]}
      />

      {voyage && onPlay && onPause && onStep && (
        <section
          aria-label="Regional voyage controls"
          data-testid="regional-voyage-controls"
          className="absolute right-[5%] top-12 z-20 w-[min(250px,calc(100%-3.5rem))] rounded-lg border border-hair bg-panel/95 p-2.5 shadow-lg backdrop-blur"
        >
          <div className="flex items-center justify-between gap-2">
            <strong className="truncate text-xs text-ink">{voyage.vessel_name}</strong>
            <span className={`shrink-0 text-[9px] font-bold uppercase tracking-wide ${effectiveVoyagePhase === 'running' ? 'text-accent' : 'text-ink-3'}`}>
              {effectiveVoyagePhase === 'running' ? 'Under way' : effectiveVoyagePhase === 'paused' ? 'Paused' : effectiveVoyagePhase === 'done' ? 'Arrived' : effectiveVoyagePhase}
            </span>
          </div>
          {latestVoyageTick && (
            <div className="mt-1 flex justify-between text-[10px] text-ink-2">
              <span>{latestVoyageTick.progress_percent.toFixed(1)}% complete</span>
              <span>{latestVoyageTick.heading_deg.toFixed(0)}° heading</span>
            </div>
          )}
          <div className="mt-2 flex gap-1.5">
            <button
              type="button"
              className="btn min-h-7 flex-1 px-2 py-1 text-[10px]"
              onClick={effectiveVoyagePhase === 'running' ? onPause : onPlay}
              aria-label={effectiveVoyagePhase === 'running' ? 'Pause regional voyage' : 'Play regional voyage'}
            >
              {effectiveVoyagePhase === 'running' ? 'Pause' : 'Play'}
            </button>
            <button
              type="button"
              className="btn min-h-7 px-2 py-1 text-[10px]"
              onClick={onStep}
              disabled={effectiveVoyagePhase === 'running' || effectiveVoyagePhase === 'done'}
              aria-label="Advance regional voyage one step"
            >
              Step
            </button>
          </div>
          <div className="mt-1 text-[9px] text-ink-3">Shared voyage clock · selected route</div>
        </section>
      )}

      {selectedIceberg && (
        <section
          aria-label={`${selectedIceberg.kind === 'observed' ? 'Observed' : 'Simulated'} iceberg details`}
          className="absolute z-30 w-52 rounded-md border border-hair bg-panel p-2.5 shadow-xl"
          style={{
            left: Math.min(selectedIceberg.x + 14, Math.max(8, (hostRef.current?.clientWidth ?? 700) - 224)),
            top: Math.max(44, selectedIceberg.y - 14),
          }}
        >
          <button
            type="button"
            className="absolute right-1 top-0.5 px-1 text-ink-3"
            aria-label="Close iceberg details"
            onClick={() => setSelectedIceberg(null)}
          >×</button>
          <strong className="block pr-4 text-xs text-ink">{selectedIceberg.kind === 'observed' ? 'Observed iceberg' : 'Model catalogue iceberg'}</strong>
          <div className="mt-1 text-2xs text-ink-2">{selectedIceberg.id} · {selectedIceberg.size}</div>
          {selectedIceberg.date && <div className="mt-1 text-2xs text-ink-3">Position date {selectedIceberg.date}</div>}
          <div className="mt-1 text-[9px] text-ink-3">{selectedIceberg.kind === 'observed' ? 'Observed record; not used for routing.' : 'Simulated catalogue record.'}</div>
        </section>
      )}

      <section
        aria-label="Observed sea-ice edge"
        className="pointer-events-none absolute left-[5%] top-12 z-20 w-[min(300px,calc(100%-3.5rem))] rounded-lg border border-hair bg-panel/95 p-2.5 shadow-lg backdrop-blur"
      >
        <strong className="text-xs text-ink">Observed sea-ice edge</strong>
        <ProvenanceBadge status="observation" size="sm" showIcon={false} className="ml-1" />
        <div
          role={seaIceStatus === 'error' ? 'alert' : 'status'}
          aria-live="polite"
          data-testid="regional-sea-ice-status"
          data-status={seaIceStatus}
          className={`mt-2 text-2xs ${seaIceStatus === 'stale' || seaIceStatus === 'error' ? 'text-warn' : 'text-ink-2'}`}
        >
          <strong>{seaIceStatusText}</strong>
          {seaIceSelection.sourceName && seaIceSelection.validTimeUtc && (
            <span className="mt-0.5 block break-words">
              {seaIceSelection.sourceName} · observed {formatSeaIceValidTime(seaIceSelection.validTimeUtc)}
              {seaIceSelection.sourceStatus === 'stale' && ' · STALE SOURCE OBSERVATION'}
              {seaIceSelection.attribution && ` · ${seaIceSelection.attribution}`}
            </span>
          )}
          {seaIceSelection.product && (
            <span className="mt-0.5 block break-all">Product {seaIceSelection.product}</span>
          )}
          {seaIceSelection.targetTimeUtc && (
            <span className="mt-0.5 block">
              Workspace target {formatSeaIceValidTime(seaIceSelection.targetTimeUtc)}
              {seaIceSelection.offsetHours !== null && ` · observation ${Math.abs(seaIceSelection.offsetHours)}h ${seaIceSelection.offsetHours < 0 ? 'before' : 'after'}`}
            </span>
          )}
          {seaIceSelection.retrievedAtUtc && (
            <span className="mt-0.5 block">Catalogue checked {formatSeaIceValidTime(seaIceSelection.retrievedAtUtc)}</span>
          )}
          {seaIceSelection.reason && seaIceStatus !== 'loading' && (
            <span className="mt-0.5 block">{seaIceSelection.reason}</span>
          )}
          {seaIceSelection.tileTemplate && (
            <div
              role="group"
              aria-label="Observed sea-ice class legend"
              data-testid="regional-sea-ice-edge-legend"
              className="mt-2"
            >
              <div className="flex flex-wrap gap-x-3 gap-y-1 text-[9px] text-ink-2">
                <span className="inline-flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-teal-300" />Open ice</span>
                <span className="inline-flex items-center gap-1"><i className="h-2.5 w-2.5 rounded-sm bg-yellow-300" />Close, very close, or fast ice</span>
              </div>
              <span className="mt-1 block text-[9px] text-ink-2">
                Daily categorical ice edge · valid, unflagged pixels · open water is transparent
              </span>
            </div>
          )}
        </div>
      </section>

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
      {windError && <MapNote title="Atmospheric wind particles unavailable" detail={windError} alert />}
      {windBandError && !windError && windParticlesEnabled && (
        <MapNote
          title={windBandMatch?.band ? 'Wind field offset from workspace time' : 'Wind field time unavailable'}
          detail={windBandError}
          alert={!windBandMatch?.band}
        />
      )}
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
