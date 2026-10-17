/**
 * Assembles the MapScene from server data and client state.
 *
 * Every screen draws the same chart with a different emphasis, so the scene is built once here
 * rather than five times. The ice field is requested for a bounding box derived from whatever is
 * currently on the chart, which keeps the grid small: asking for the whole Southern Ocean at
 * half-degree resolution is tens of thousands of cells the user cannot see.
 */
import { useMemo } from 'react';
import { useCoastline, useIceField, useIcebergs, useStations } from '../api/queries';
import type { IceFieldParams } from '../api/queries';
import { emptyScene, type MapScene } from '../map/MapEngine';
import { latestTick, useAppStore } from '../store/useAppStore';

/** Padding around the planned route, in degrees, so the chart has context around the track. */
const PAD_LAT = 4;
const PAD_LON = 8;

export interface SceneOptions {
  /** Draw the iceberg drift track for the selected berg. */
  showBergDrift?: boolean;
  /** Override the forecast lead time used for the ice field. */
  leadHoursOverride?: number;
}

export function useScene(options: SceneOptions = {}): {
  scene: MapScene;
  fitTargets: { lat: number; lon: number }[];
  iceLoading: boolean;
} {
  const coastline = useCoastline();
  const stations = useStations();

  const plan = useAppStore((s) => s.plan);
  const ticks = useAppStore((s) => s.ticks);
  const radar = useAppStore((s) => s.radar);
  const layers = useAppStore((s) => s.layers);
  const rasterMode = useAppStore((s) => s.rasterMode);
  const rasterOpacity = useAppStore((s) => s.rasterOpacity);
  const rioColoredRoute = useAppStore((s) => s.rioColoredRoute);
  const inspect = useAppStore((s) => s.inspect);
  const storeLead = useAppStore((s) => s.leadHours);
  const selectedBergId = useAppStore((s) => s.selectedBergId);
  const bergDrift = useAppStore((s) => s.bergDrift);

  const leadHours = options.leadHoursOverride ?? storeLead;

  const optimisedRoute = plan?.optimized?.waypoints ?? plan?.waypoints ?? [];
  const baselineRoute = plan?.baseline?.waypoints ?? [];

  // The points the chart should frame: the planned track if there is one, otherwise the
  // Indian sector, which is where every demonstration voyage goes.
  const fitTargets = useMemo(() => {
    if (optimisedRoute.length) {
      return optimisedRoute.map((w) => ({ lat: w.latitude, lon: w.longitude }));
    }
    return [
      { lat: -38, lon: 10 },
      { lat: -38, lon: 90 },
      { lat: -72, lon: 10 },
      { lat: -72, lon: 90 },
    ];
  }, [optimisedRoute]);

  // Ice-field bounding box, clamped to the domain the backend will serve and to a cell budget.
  const iceParams: IceFieldParams | null = useMemo(() => {
    const lats = fitTargets.map((p) => p.lat);
    const lons = fitTargets.map((p) => p.lon);
    const latMin = Math.max(-78, Math.min(...lats) - PAD_LAT);
    const latMax = Math.min(-48, Math.max(...lats) + PAD_LAT);
    const lonMin = Math.max(-180, Math.min(...lons) - PAD_LON);
    const lonMax = Math.min(180, Math.max(...lons) + PAD_LON);
    if (!(latMax > latMin && lonMax > lonMin)) return null;

    // Keep the request inside the server's 40,000-cell ceiling.
    let resolutionDeg = 0.5;
    for (const candidate of [0.5, 0.75, 1.0, 1.5, 2.0]) {
      const cells = ((latMax - latMin) / candidate) * ((lonMax - lonMin) / (candidate * 2));
      resolutionDeg = candidate;
      if (cells <= 18_000) break;
    }
    return { latMin, latMax, lonMin, lonMax, resolutionDeg, leadHours };
  }, [fitTargets, leadHours]);

  const iceField = useIceField(iceParams);
  const icebergs = useIcebergs(leadHours);

  const scene: MapScene = useMemo(() => {
    const base = emptyScene();
    const tick = latestTick(ticks);
    return {
      ...base,
      coastline: coastline.data?.features ?? [],
      stations: stations.data?.stations ?? [],
      ports: stations.data?.ports ?? [],
      iceField: iceField.data ?? null,
      icebergs: icebergs.data?.icebergs ?? [],
      selectedBergId,
      bergDrift: options.showBergDrift ? bergDrift : null,
      optimisedRoute,
      baselineRoute,
      track: ticks.map((t) => [t.latitude, t.longitude] as [number, number]),
      vessel: tick ? { lat: tick.latitude, lon: tick.longitude, heading: tick.heading_deg } : null,
      radar,
      inspect,
      rasterMode,
      rasterOpacity,
      rioColoredRoute,
      layers,
    };
  }, [
    coastline.data,
    stations.data,
    iceField.data,
    icebergs.data,
    selectedBergId,
    bergDrift,
    options.showBergDrift,
    optimisedRoute,
    baselineRoute,
    ticks,
    radar,
    inspect,
    rasterMode,
    rasterOpacity,
    rioColoredRoute,
    layers,
  ]);

  return { scene, fitTargets, iceLoading: iceField.isFetching };
}
