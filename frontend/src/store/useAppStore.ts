/**
 * Client state: which screen is up, what the planner is configured to ask for, what the
 * chart is showing, and the live voyage. Server data lives in TanStack Query; nothing
 * fetched is duplicated here except the live voyage, which arrives over a socket rather
 * than a request and so has no query to own it.
 */
import { create } from 'zustand';
import type {
  IcebergForecast,
  IceClassKey,
  OptimizationSummary,
  RadarSweep,
  RouteWeights,
  VoyageAlert,
  VoyageState,
  VoyageTick,
} from '../api/types';
import { DEFAULT_LAYERS, type LayerToggles } from '../map/MapEngine';
import type { FlowStyle } from '../map/flow';
import type { RasterMode } from '../map/layers';

export type ScreenId = 'flow' | 'bridge' | 'planner' | 'forecast' | 'icebergs' | 'analytics';

export interface PlannerConfig {
  originId: string;
  destinationId: string;
  vesselKey: string;
  iceClass: IceClassKey;
  weights: RouteWeights;
  gridResolutionDeg: number;
  avoidIcebergs: boolean;
  departureTimeHours: number;
}

export type PlanPhase = 'idle' | 'planning' | 'ready' | 'error';
export type VoyagePhase = 'idle' | 'creating' | 'connecting' | 'ready' | 'running' | 'paused' | 'done' | 'error';

interface AppState {
  screen: ScreenId;
  setScreen: (s: ScreenId) => void;

  // ---- presentation mode ----
  // Simple mode is the default. A first-time user gets the two screens that tell the story and
  // the panels that matter; everything analytical is one toggle away rather than in their face.
  simpleMode: boolean;
  setSimpleMode: (v: boolean) => void;
  guideOpen: boolean;
  setGuideOpen: (v: boolean) => void;

  // ---- planner ----
  planner: PlannerConfig;
  setPlanner: (patch: Partial<PlannerConfig>) => void;
  plan: OptimizationSummary | null;
  planPhase: PlanPhase;
  planError: string | null;
  planElapsedMs: number;
  setPlan: (plan: OptimizationSummary | null) => void;
  setPlanPhase: (phase: PlanPhase, error?: string | null) => void;
  setPlanElapsedMs: (ms: number) => void;

  // ---- chart ----
  layers: LayerToggles;
  toggleLayer: (key: keyof LayerToggles) => void;
  setLayers: (patch: Partial<LayerToggles>) => void;
  rasterMode: RasterMode;
  setRasterMode: (m: RasterMode) => void;
  /** Moving particles or static arrows for the wind and current layers. */
  flowStyle: FlowStyle;
  setFlowStyle: (s: FlowStyle) => void;
  rasterOpacity: number;
  setRasterOpacity: (v: number) => void;
  rioColoredRoute: boolean;
  setRioColoredRoute: (v: boolean) => void;
  leadHours: number;
  setLeadHours: (h: number) => void;
  playingForecast: boolean;
  setPlayingForecast: (v: boolean) => void;
  inspect: { lat: number; lon: number } | null;
  setInspect: (p: { lat: number; lon: number } | null) => void;

  // ---- icebergs ----
  selectedBergId: string | null;
  setSelectedBergId: (id: string | null) => void;
  bergDrift: IcebergForecast | null;
  setBergDrift: (d: IcebergForecast | null) => void;
  bergForecastHours: number;
  setBergForecastHours: (h: number) => void;

  // ---- live voyage ----
  voyage: VoyageState | null;
  voyagePhase: VoyagePhase;
  voyageError: string | null;
  ticks: VoyageTick[];
  alerts: VoyageAlert[];
  radar: RadarSweep | null;
  tickHours: number;
  intervalMs: number;
  setVoyage: (v: VoyageState | null) => void;
  setVoyagePhase: (p: VoyagePhase, error?: string | null) => void;
  pushTick: (t: VoyageTick) => void;
  pushAlert: (a: VoyageAlert) => void;
  setRadar: (r: RadarSweep | null) => void;
  setTickHours: (h: number) => void;
  setIntervalMs: (ms: number) => void;
  resetVoyage: () => void;
}

export const MAX_TICK_HISTORY = 800;

export const useAppStore = create<AppState>((set) => ({
  screen: 'planner',
  setScreen: (screen) => set({ screen }),

  simpleMode: true,
  setSimpleMode: (simpleMode) => set({ simpleMode }),
  // The first-run guide was retired with the redesign; the field stays so older screens compile.
  guideOpen: false,
  setGuideOpen: (guideOpen) => set({ guideOpen }),

  planner: {
    originId: 'cape_town',
    destinationId: 'bharati',
    vesselKey: 'vasiliy_golovnin',
    iceClass: 'PC5',
    weights: { fuel: 1.0, time: 0.35, risk: 1.0 },
    gridResolutionDeg: 0.5,
    avoidIcebergs: true,
    departureTimeHours: 0,
  },
  setPlanner: (patch) => set((s) => ({ planner: { ...s.planner, ...patch } })),
  plan: null,
  planPhase: 'idle',
  planError: null,
  planElapsedMs: 0,
  setPlan: (plan) => set({ plan }),
  setPlanPhase: (planPhase, planError = null) => set({ planPhase, planError }),
  setPlanElapsedMs: (planElapsedMs) => set({ planElapsedMs }),

  layers: { ...DEFAULT_LAYERS },
  toggleLayer: (key) => set((s) => ({ layers: { ...s.layers, [key]: !s.layers[key] } })),
  setLayers: (patch) => set((s) => ({ layers: { ...s.layers, ...patch } })),
  rasterMode: 'concentration',
  setRasterMode: (rasterMode) => set({ rasterMode }),
  flowStyle: 'animated',
  setFlowStyle: (flowStyle) => set({ flowStyle }),
  rasterOpacity: 0.92,
  setRasterOpacity: (rasterOpacity) => set({ rasterOpacity }),
  rioColoredRoute: false,
  setRioColoredRoute: (rioColoredRoute) => set({ rioColoredRoute }),
  leadHours: 0,
  setLeadHours: (leadHours) => set({ leadHours }),
  playingForecast: false,
  setPlayingForecast: (playingForecast) => set({ playingForecast }),
  inspect: null,
  setInspect: (inspect) => set({ inspect }),

  selectedBergId: null,
  setSelectedBergId: (selectedBergId) => set({ selectedBergId }),
  bergDrift: null,
  setBergDrift: (bergDrift) => set({ bergDrift }),
  bergForecastHours: 120,
  setBergForecastHours: (bergForecastHours) => set({ bergForecastHours }),

  voyage: null,
  voyagePhase: 'idle',
  voyageError: null,
  ticks: [],
  alerts: [],
  radar: null,
  tickHours: 6,
  intervalMs: 400,
  setVoyage: (voyage) =>
    set({
      voyage,
      ticks: voyage?.ticks ?? [],
      alerts: voyage?.alerts ?? [],
    }),
  setVoyagePhase: (voyagePhase, voyageError = null) => set({ voyagePhase, voyageError }),
  pushTick: (t) =>
    set((s) => {
      const ticks = [...s.ticks, t];
      return { ticks: ticks.length > MAX_TICK_HISTORY ? ticks.slice(-MAX_TICK_HISTORY) : ticks };
    }),
  pushAlert: (a) =>
    set((s) => (s.alerts.some((x) => x.alert_id === a.alert_id) ? s : { alerts: [...s.alerts, a] })),
  setRadar: (radar) => set({ radar }),
  setTickHours: (tickHours) => set({ tickHours }),
  setIntervalMs: (intervalMs) => set({ intervalMs }),
  resetVoyage: () =>
    set({ voyage: null, voyagePhase: 'idle', voyageError: null, ticks: [], alerts: [], radar: null }),
}));

/** The latest tick, or null before the ship gets under way. */
export function latestTick(ticks: VoyageTick[]): VoyageTick | null {
  return ticks.length ? ticks[ticks.length - 1] : null;
}
