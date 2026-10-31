/**
 * Layer controls for the chart: what is drawn, how opaque the ice is, and which forecast time.
 *
 * It reads and writes the same store fields the Sea-ice screen already uses, so the two cannot disagree,
 * and every control here changes something on the map. It is a popover so the chart stays the workspace;
 * Escape closes it. The open state is owned by MapCanvas, which renders the toggle button inside its
 * control stack and this panel as a sibling, so the panel is positioned against the chart, not the stack.
 */
import { useEffect } from 'react';
import { Pause, Play } from 'lucide-react';
import type { LayerToggles } from '../map/MapEngine';
import type { ModeAvailability } from '../map/iceModes';
import type { RasterMode } from '../map/layers';
import type { Provenance } from '../api/types';
import { useReducedMotion } from '../hooks/useReducedMotion';
import { useAppStore } from '../store/useAppStore';
import { Slider, Toggle } from './ui';
import { ProvenanceBadge } from './ProvenanceBadge';

const RASTER_MODES: { mode: RasterMode; label: string; hint: string }[] = [
  { mode: 'concentration', label: 'Concentration', hint: 'Continuous ramp, 0 to 100 percent' },
  { mode: 'classes', label: 'Classes', hint: 'Five labelled bands, easiest to read at a glance' },
  { mode: 'change', label: 'Change', hint: 'Concentration at the chosen time minus +0 h' },
  { mode: 'thickness', label: 'Thickness', hint: 'Ice thickness in metres' },
];

type Row = { key: keyof LayerToggles; label: string; hint?: string; proven?: Provenance };

const ICE_FIELD_PROV: Provenance = { status: 'synthetic', source: 'Model ice field', note: 'hindcast grid, not an observation' };
const ICEBERG_CATALOGUE_PROV: Provenance = {
  status: 'real-seed',
  source: 'Model iceberg catalogue',
  note: 'real names and origins, drifted by the model',
};
const OBSERVED_BERGS_PROV: Provenance = { status: 'real-observation', source: 'USNIC-format snapshot', note: 'dated observed positions, not tracked live' };
const FLOW_PROV: Provenance = { status: 'synthetic', source: 'Model flow field', note: 'simulated wind and current vectors' };

const GROUPS: { title: string; rows: Row[] }[] = [
  {
    title: 'Sea ice',
    rows: [
      { key: 'iceRaster', label: 'Ice raster', hint: 'Model grid of sea-ice concentration', proven: ICE_FIELD_PROV },
      { key: 'iceEdge', label: 'Ice edge', proven: ICE_FIELD_PROV },
      { key: 'compression', label: 'Compression shading', proven: ICE_FIELD_PROV },
      { key: 'drift', label: 'Ice drift vectors', proven: ICE_FIELD_PROV },
    ],
  },
  {
    title: 'Wind and current',
    rows: [
      { key: 'windFlow', label: 'Atmospheric wind', hint: '10 m eastward/northward velocity vectors', proven: FLOW_PROV },
      { key: 'currentFlow', label: 'Ocean currents', hint: 'Surface eastward/northward velocity vectors', proven: FLOW_PROV },
    ],
  },
  {
    title: 'Icebergs',
    rows: [
      { key: 'icebergs', label: 'Simulated catalogue', hint: 'Seeded and drifted by the model', proven: ICEBERG_CATALOGUE_PROV },
      { key: 'observedBergs', label: 'Observed snapshot', hint: 'USNIC-format file; shows its own date and age', proven: OBSERVED_BERGS_PROV },
    ],
  },
  {
    title: 'Chart',
    rows: [
      { key: 'land', label: 'Land' },
      { key: 'graticule', label: 'Graticule' },
      { key: 'labels', label: 'Stations and ports' },
      { key: 'optimisedRoute', label: 'Optimised route' },
      { key: 'baselineRoute', label: 'Baseline route' },
      { key: 'track', label: 'Track made good' },
    ],
  },
];

export function MapLayerPanel({
  open,
  onClose,
  availability,
  view = 'polar',
}: {
  open: boolean;
  onClose: () => void;
  /** Which ice modes the loaded data supports, and why not. */
  availability: Record<RasterMode, ModeAvailability>;
  /** 'polar' for the navigation chart (default); 'regional' hides the wind/current block. */
  view?: 'polar' | 'regional';
}): JSX.Element | null {
  const layers = useAppStore((s) => s.layers);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const rasterMode = useAppStore((s) => s.rasterMode);
  const setRasterMode = useAppStore((s) => s.setRasterMode);
  const rasterOpacity = useAppStore((s) => s.rasterOpacity);
  const setRasterOpacity = useAppStore((s) => s.setRasterOpacity);
  const leadHours = useAppStore((s) => s.leadHours);
  const setLeadHours = useAppStore((s) => s.setLeadHours);
  const flowStyle = useAppStore((s) => s.flowStyle);
  const setFlowStyle = useAppStore((s) => s.setFlowStyle);
  const flowPaused = useAppStore((s) => s.flowPaused);
  const setFlowPaused = useAppStore((s) => s.setFlowPaused);
  const windFlowSource = useAppStore((s) => s.windFlowSource);
  const setWindFlowSource = useAppStore((s) => s.setWindFlowSource);
  const currentFlowSource = useAppStore((s) => s.currentFlowSource);
  const setCurrentFlowSource = useAppStore((s) => s.setCurrentFlowSource);
  const flowValidDate = useAppStore((s) => s.flowValidDate);
  const setFlowValidDate = useAppStore((s) => s.setFlowValidDate);
  const reduced = useReducedMotion();

  useEffect(() => {
    if (!open) return undefined;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') onClose();
    };
    window.addEventListener('keydown', onKey);
    return () => window.removeEventListener('keydown', onKey);
  }, [open, onClose]);

  if (!open) return null;

  return (
    <div
      id="map-layer-panel"
      role="dialog"
      aria-label="Chart layers"
      className="float absolute z-20 max-h-[calc(100%-24px)] w-[280px] overflow-y-auto px-3 py-3"
      style={{ top: 12, right: 56 }}
    >
      <div className="mb-3">
        <div className="mb-1.5 text-2xs font-medium text-ink">Ice display</div>
        <div className="grid grid-cols-2 gap-1" role="group" aria-label="Ice display mode">
          {RASTER_MODES.map(({ mode, label, hint }) => {
            const a = availability[mode];
            return (
              // aria-disabled, not disabled: the mode can still be chosen, and the legend then explains why it
              // draws nothing. A dead button would leave the user guessing.
              <button
                key={mode}
                type="button"
                title={a.available ? hint : (a.reason ?? hint)}
                aria-pressed={rasterMode === mode}
                aria-disabled={!a.available}
                className={`btn ${rasterMode === mode ? 'btn-accent' : ''} ${a.available ? '' : 'opacity-50'}`}
                onClick={() => setRasterMode(mode)}
              >
                {label}
              </button>
            );
          })}
        </div>
        <div className="mt-3 space-y-3">
          <Slider
            label="Ice opacity"
            value={rasterOpacity}
            min={0.1}
            max={1}
            step={0.02}
            display={`${Math.round(rasterOpacity * 100)}%`}
            onChange={setRasterOpacity}
          />
          <Slider
            label="Forecast time"
            value={leadHours}
            min={0}
            max={168}
            step={6}
            display={`+${leadHours} h`}
            onChange={setLeadHours}
          />
        </div>
      </div>

      {GROUPS.filter((g) => !(view === 'regional' && g.title === 'Wind and current')).map((g) => (
        <div key={g.title} className="mb-2">
          <div className="mb-0.5 text-2xs font-medium text-ink">{g.title}</div>
          {g.rows.map((r) => (
            <Toggle key={r.key} label={r.label} hint={r.hint} checked={layers[r.key]} onChange={() => toggleLayer(r.key)}>
              {r.proven && <ProvenanceBadge provenance={r.proven} size="sm" />}
            </Toggle>
          ))}
          {g.title === 'Wind and current' && (
            <div className="mt-1.5">
              <label className="mb-1 block text-2xs text-ink-3" htmlFor="flow-valid-date">Real data valid date (UTC)</label>
              <input
                id="flow-valid-date"
                type="date"
                value={flowValidDate}
                onChange={(event) => setFlowValidDate(event.currentTarget.value)}
                className="field mb-2 w-full"
                aria-describedby="flow-date-hint"
              />
              <p id="flow-date-hint" className="mb-2 text-2xs text-ink-3">Leave blank to use the latest cached date. Real data never falls back to simulated vectors.</p>
              <label className="mb-1 block text-2xs text-ink-3" htmlFor="wind-source">Wind source</label>
              <select id="wind-source" className="field mb-2 w-full" value={windFlowSource} onChange={(e) => setWindFlowSource(e.currentTarget.value as typeof windFlowSource)}>
                <option value="simulated">Simulation (demo)</option>
                <option value="noaa-gfs">NOAA GFS (forecast)</option>
              </select>
              <label className="mb-1 block text-2xs text-ink-3" htmlFor="current-source">Current source</label>
              <select id="current-source" className="field mb-2 w-full" value={currentFlowSource} onChange={(e) => setCurrentFlowSource(e.currentTarget.value as typeof currentFlowSource)}>
                <option value="simulated">Simulation (demo)</option>
                <option value="copernicus">Copernicus Marine (analysis)</option>
              </select>
              <div className="mb-1 text-2xs text-ink-3">Display</div>
              <div className="grid grid-cols-2 gap-1" role="group" aria-label="Wind and current display">
                {(
                  [
                    ['animated', 'Particles', 'Moving particles that follow the field'],
                    ['arrows', 'Arrows', 'Static arrows; length is relative speed'],
                  ] as const
                ).map(([id, label, hint]) => {
                  const pressed = (reduced ? 'arrows' : flowStyle) === id;
                  return (
                    <button
                      key={id}
                      type="button"
                      title={hint}
                      disabled={reduced && id === 'animated'}
                      aria-pressed={pressed}
                      className={`btn ${pressed ? 'btn-accent' : ''}`}
                      onClick={() => setFlowStyle(id)}
                    >
                      {label}
                    </button>
                  );
                })}
              </div>
              <button
                type="button"
                className="btn mt-1.5 flex w-full items-center justify-center gap-1.5"
                aria-label={flowPaused ? 'Resume flow animation' : 'Pause flow animation'}
                title={flowPaused ? 'Resume animated particles' : 'Pause animated particles'}
                disabled={reduced || flowStyle !== 'animated' || !(layers.windFlow || layers.currentFlow)}
                onClick={() => setFlowPaused(!flowPaused)}
              >
                {flowPaused ? <Play size={13} aria-hidden="true" /> : <Pause size={13} aria-hidden="true" />}
                {flowPaused ? 'Resume particles' : 'Pause particles'}
              </button>
              {reduced && <p className="mt-1 text-2xs text-ink-3">Your system asks for reduced motion, so particles are off.</p>}
            </div>
          )}
        </div>
      ))}
      <p className="text-2xs text-ink-3">Press Esc to close.</p>
    </div>
  );
}
