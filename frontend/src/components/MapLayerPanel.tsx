/**
 * Layer controls for the chart: what is drawn, how opaque the ice is, and which forecast time.
 *
 * It reads and writes the same store fields the Sea-ice screen already uses, so the two cannot disagree,
 * and every control here changes something on the map. It is a popover so the chart stays the workspace;
 * Escape closes it. The open state is owned by MapCanvas, which renders the toggle button inside its
 * control stack and this panel as a sibling, so the panel is positioned against the chart, not the stack.
 */
import { useEffect } from 'react';
import type { LayerToggles } from '../map/MapEngine';
import type { RasterMode } from '../map/layers';
import { useAppStore } from '../store/useAppStore';
import { Slider, Toggle } from './ui';
import { useStageInsets } from './stageInsets';

const RASTER_MODES: { mode: RasterMode; label: string; hint: string }[] = [
  { mode: 'concentration', label: 'Concentration', hint: 'Continuous ramp, 0 to 100 percent' },
  { mode: 'classes', label: 'Classes', hint: 'Five labelled bands, easiest to read at a glance' },
  { mode: 'change', label: 'Change', hint: 'Concentration at the chosen time minus +0 h' },
  { mode: 'thickness', label: 'Thickness', hint: 'Ice thickness in metres' },
];

type Row = { key: keyof LayerToggles; label: string; hint?: string };

const GROUPS: { title: string; rows: Row[] }[] = [
  {
    title: 'Sea ice',
    rows: [
      { key: 'iceRaster', label: 'Ice raster', hint: 'Model grid of sea-ice concentration' },
      { key: 'iceEdge', label: 'Ice edge' },
      { key: 'compression', label: 'Compression shading' },
      { key: 'drift', label: 'Ice drift vectors' },
    ],
  },
  {
    title: 'Wind and current',
    rows: [
      { key: 'windFlow', label: 'Wind (simulated)', hint: 'Animated particles on the 10 m wind field' },
      { key: 'currentFlow', label: 'Ocean current (simulated)', hint: 'Animated particles on the surface-current field' },
    ],
  },
  {
    title: 'Icebergs',
    rows: [
      { key: 'icebergs', label: 'Simulated catalogue', hint: 'Seeded and drifted by the model' },
      { key: 'observedBergs', label: 'Observed snapshot (stale)', hint: 'USNIC-format file; shows its own date and age' },
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

export function MapLayerPanel({ open, onClose }: { open: boolean; onClose: () => void }): JSX.Element | null {
  const insets = useStageInsets();

  const layers = useAppStore((s) => s.layers);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const rasterMode = useAppStore((s) => s.rasterMode);
  const setRasterMode = useAppStore((s) => s.setRasterMode);
  const rasterOpacity = useAppStore((s) => s.rasterOpacity);
  const setRasterOpacity = useAppStore((s) => s.setRasterOpacity);
  const leadHours = useAppStore((s) => s.leadHours);
  const setLeadHours = useAppStore((s) => s.setLeadHours);

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
      style={{ top: Math.max(12, insets.top), right: insets.right + 64 }}
    >
      <div className="mb-3">
        <div className="mb-1.5 text-2xs font-medium text-ink">Ice display</div>
        <div className="grid grid-cols-2 gap-1" role="group" aria-label="Ice display mode">
          {RASTER_MODES.map(({ mode, label, hint }) => (
            <button
              key={mode}
              type="button"
              title={hint}
              aria-pressed={rasterMode === mode}
              className={`btn ${rasterMode === mode ? 'btn-accent' : ''}`}
              onClick={() => setRasterMode(mode)}
            >
              {label}
            </button>
          ))}
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

      {GROUPS.map((g) => (
        <div key={g.title} className="mb-2">
          <div className="mb-0.5 text-2xs font-medium text-ink">{g.title}</div>
          {g.rows.map((r) => (
            <Toggle key={r.key} label={r.label} hint={r.hint} checked={layers[r.key]} onChange={() => toggleLayer(r.key)} />
          ))}
        </div>
      ))}
      <p className="text-2xs text-ink-3">Press Esc to close.</p>
    </div>
  );
}
