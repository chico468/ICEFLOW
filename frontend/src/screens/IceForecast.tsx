/**
 * Ice Forecast: scrub the forecast forward, toggle chart layers, and inspect forecast skill.
 *
 * The skill panel is the one that matters scientifically. Any forecast must beat persistence —
 * "assume nothing changes" — or it is not adding information. Ours does from 24 hours out, and
 * the persistence baseline is plotted alongside so the claim can be checked rather than taken.
 */
import { useEffect } from 'react';
import { Pause, Play } from 'lucide-react';
import {
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useForecastSkill, useIcePoint, useRiskMatrix } from '../api/queries';
import { MapCanvas } from '../map/MapCanvas';
import { MapStage } from '../components/MapStage';
import { Badge, EmptyState, KeyValue, Panel, Slider, Toggle } from '../components/ui';
import { useScene } from '../hooks/useScene';
import { modeAvailability } from '../map/iceModes';
import { num, tenths } from '../lib/format';
import { rioColor } from '../map/palette';
import type { LayerToggles } from '../map/MapEngine';
import { useAppStore } from '../store/useAppStore';

const LAYER_LABELS: { key: keyof LayerToggles; label: string }[] = [
  { key: 'iceRaster', label: 'Ice raster' },
  { key: 'iceEdge', label: 'Ice edge' },
  { key: 'compression', label: 'Compression' },
  { key: 'drift', label: 'Drift vectors' },
  { key: 'icebergs', label: 'Icebergs' },
  { key: 'windFlow', label: 'Wind (simulated)' },
  { key: 'currentFlow', label: 'Current (simulated)' },
  { key: 'observedBergs', label: 'Observed bergs (stale)' },
  { key: 'land', label: 'Land' },
  { key: 'graticule', label: 'Graticule' },
  { key: 'optimisedRoute', label: 'Optimised route' },
  { key: 'baselineRoute', label: 'Baseline route' },
  { key: 'track', label: 'Track made good' },
  { key: 'labels', label: 'Labels' },
];

export function IceForecast(): JSX.Element {
  const { scene, fitTargets, iceLoading } = useScene();
  const leadHours = useAppStore((s) => s.leadHours);
  // The same availability rules the chart's layer panel and legend use, so the three can never disagree.
  const modeAvail = modeAvailability(scene.iceField, leadHours, {
    field: scene.iceFieldBase,
    loading: scene.status.baseLoading,
    error: scene.status.baseError,
  });
  const setLeadHours = useAppStore((s) => s.setLeadHours);
  const playing = useAppStore((s) => s.playingForecast);
  const setPlaying = useAppStore((s) => s.setPlayingForecast);
  const layers = useAppStore((s) => s.layers);
  const toggleLayer = useAppStore((s) => s.toggleLayer);
  const rasterMode = useAppStore((s) => s.rasterMode);
  const setRasterMode = useAppStore((s) => s.setRasterMode);
  const rasterOpacity = useAppStore((s) => s.rasterOpacity);
  const setRasterOpacity = useAppStore((s) => s.setRasterOpacity);
  const inspect = useAppStore((s) => s.inspect);
  const setInspect = useAppStore((s) => s.setInspect);

  const skill = useForecastSkill();
  const matrix = useRiskMatrix();
  const point = useIcePoint(inspect?.lat ?? null, inspect?.lon ?? null, leadHours);

  // Playback steps the lead time in 12-hour increments and wraps at the forecast horizon.
  useEffect(() => {
    if (!playing) return;
    const id = window.setInterval(() => {
      const next = useAppStore.getState().leadHours + 12;
      useAppStore.getState().setLeadHours(next > 168 ? 0 : next);
    }, 1100);
    return () => window.clearInterval(id);
  }, [playing]);

  const skillRows = (skill.data?.rows ?? []).map((r) => ({
    lead: r.lead_hours,
    forecast: r.rmse,
    persistence: r.persistence_rmse,
    iiee: r.iiee_fraction,
    skillScore: r.skill_score_vs_persistence,
  }));

  return (
    <MapStage
      id="ice"
      map={
        <>
          <MapCanvas scene={scene} fitTargets={fitTargets} onClickPoint={(ll) => setInspect(ll)} />
          {iceLoading && (
            <div className="sheet absolute left-1/2 top-3 -translate-x-1/2 px-3 py-1.5 text-2xs text-accent">
              Loading ice field…
            </div>
          )}
          {scene.status.iceError && (
            <div className="sheet absolute left-1/2 top-3 -translate-x-1/2 rounded-md border border-danger/40 bg-danger/10 p-2 text-xs text-danger">
              <div className="font-semibold">No data for this date</div>
              <div className="mt-0.5 leading-relaxed">{scene.status.iceError}</div>
            </div>
          )}
        </>
      }
      shelf={
        <>
        <Panel
          title="Forecast lead time"
          right={<Badge tone="accent">+{num(leadHours, 0)} h</Badge>}
          className="shrink-0"
        >
          <div className="flex items-center gap-2">
            <button type="button" className="btn" onClick={() => setPlaying(!playing)}>
              {playing ? <Pause size={13} /> : <Play size={13} />}
              {playing ? 'Pause' : 'Play'}
            </button>
            <div className="flex-1">
              <Slider
                label=""
                value={leadHours}
                min={0}
                max={168}
                step={6}
                display={`+${num(leadHours, 0)} h`}
                onChange={(v) => setLeadHours(v)}
              />
            </div>
          </div>
          <p className="mt-1 text-2xs text-ink-3">
            The analysis is materially advected: a lead you see now is the same lead a day later,
            tens of kilometres downstream. That is what makes a Lagrangian forecast the right
            method rather than a decorative one.
          </p>
        </Panel>

        <Panel title="Chart layers">
          <div className="mb-2 flex gap-1">
            {(['concentration', 'classes', 'change', 'thickness'] as const).map((mode) => (
              <button
                key={mode}
                type="button"
                title={modeAvail[mode].reason ?? undefined}
                aria-pressed={rasterMode === mode}
                aria-disabled={!modeAvail[mode].available}
                className={`btn flex-1 ${rasterMode === mode ? 'btn-accent' : ''} ${modeAvail[mode].available ? '' : 'opacity-50'}`}
                onClick={() => setRasterMode(mode)}
              >
                {mode}
              </button>
            ))}
          </div>
          {!modeAvail[rasterMode].available && (
            <p role="status" className="text-2xs text-warn">
              {modeAvail[rasterMode].reason} Nothing is drawn for this mode.
            </p>
          )}
          <Slider
            label="Raster opacity"
            value={rasterOpacity}
            min={0.1}
            max={1}
            step={0.02}
            display={num(rasterOpacity * 100, 0) + '%'}
            onChange={setRasterOpacity}
          />
          <div className="mt-2 grid grid-cols-2 gap-1">
            {LAYER_LABELS.map(({ key, label }) => (
              <Toggle key={key} label={label} checked={layers[key]} onChange={() => toggleLayer(key)} />
            ))}
          </div>
        </Panel>

        <Panel title="Point inspection" subtitle={inspect ? undefined : 'Click the chart'}>
          {!inspect || !point.data ? (
            <EmptyState title="Nothing selected" detail="Click anywhere on the chart to read the model there." />
          ) : (
            <>
              <KeyValue label="Position" value={`${num(point.data.lat, 3)}, ${num(point.data.lon, 3)}`} />
              <KeyValue label="Concentration" value={tenths(point.data.concentration)} />
              <KeyValue label="Thickness" value={num(point.data.thickness_m, 2)} unit="m" />
              <KeyValue label="Stage" value={point.data.stage_of_development} />
              <KeyValue label="Drift" value={`${num(point.data.drift_speed_ms, 3)} m/s → ${num(point.data.drift_dir_to_deg, 0)}°`} />
              <KeyValue label="Compression" value={num(point.data.compression_index, 2)} />
              <KeyValue label="Besetting risk" value={point.data.besetting_risk} />
              <KeyValue label="Freezing degree days" value={num(point.data.freezing_degree_days, 0)} />
              <KeyValue label="Polynya" value={point.data.is_polynya ? 'yes' : 'no'} />
              <KeyValue
                label="Concentration ±1σ"
                value={num(point.data.concentration_uncertainty, 3)}
              />
            </>
          )}
        </Panel>

        <Panel
          title="Forecast skill"
          subtitle="Against the analysis valid at the same time"
          right={skill.data ? <Badge tone="accent">simulated</Badge> : undefined}
        >
          {skillRows.length === 0 ? (
            <EmptyState title="No skill data" detail="Backend unreachable." />
          ) : (
            <>
              <div className="h-40">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={skillRows} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
                    <CartesianGrid stroke="rgb(var(--c-hair))" strokeDasharray="2 3" />
                    <XAxis dataKey="lead" stroke="rgb(var(--c-ink-3))" tick={{ fontSize: 10 }} unit="h" />
                    <YAxis stroke="rgb(var(--c-ink-3))" tick={{ fontSize: 10 }} />
                    <Tooltip
                      contentStyle={{ background: 'rgb(var(--c-panel))', border: '1px solid rgb(var(--c-hair-2))', fontSize: 11 }}
                      labelStyle={{ color: 'rgb(var(--c-ink-2))' }}
                    />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Line type="monotone" dataKey="forecast" name="Forecast RMSE" stroke="rgb(var(--c-accent))" dot={false} strokeWidth={2} />
                    <Line type="monotone" dataKey="persistence" name="Persistence RMSE" stroke="rgb(var(--c-warn))" dot={false} strokeDasharray="4 3" />
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <table className="mt-2 w-full text-2xs">
                <thead className="text-ink-3">
                  <tr>
                    <th className="text-left font-normal">Lead</th>
                    <th className="text-right font-normal">RMSE</th>
                    <th className="text-right font-normal">Persist.</th>
                    <th className="text-right font-normal">Skill</th>
                    <th className="text-right font-normal">IIEE</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {skillRows.map((r) => (
                    <tr key={r.lead} className="border-t border-hair/60">
                      <td className="py-0.5 text-left">{num(r.lead, 0)} h</td>
                      <td className="py-0.5 text-right">{num(r.forecast, 4)}</td>
                      <td className="py-0.5 text-right text-ink-3">{num(r.persistence, 4)}</td>
                      <td className={`py-0.5 text-right ${r.skillScore > 0 ? 'text-ok' : 'text-danger'}`}>
                        {r.skillScore > 0 ? '+' : ''}
                        {num(r.skillScore, 3)}
                      </td>
                      <td className="py-0.5 text-right text-ink-3">{num(r.iiee, 3)}</td>
                    </tr>
                  ))}
                </tbody>
              </table>
              <p className="mt-1 text-2xs text-ink-3">
                A positive skill score means the forecast beat persistence. Measured inside the
                synthetic environment, not operational skill.
              </p>
            </>
          )}
        </Panel>

        <Panel title="POLARIS risk values" subtitle={matrix.data?.reference}>
          {!matrix.data ? (
            <EmptyState title="No matrix" detail="Backend unreachable." />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full min-w-[420px] text-2xs">
                <thead>
                  <tr className="text-ink-3">
                    <th className="sticky left-0 bg-panel text-left font-normal">Class</th>
                    {matrix.data.ice_types.map((t) => (
                      <th key={t} className="px-0.5 text-right font-normal" title={t}>
                        {t.split('_')[0].slice(0, 4)}
                      </th>
                    ))}
                  </tr>
                </thead>
                <tbody className="num">
                  {Object.entries(matrix.data.rows).map(([cls, row]) => (
                    <tr key={cls} className="border-t border-hair/60">
                      <td className="sticky left-0 bg-panel py-0.5 pr-1 text-left font-sans text-ink-2">{cls}</td>
                      {matrix.data!.ice_types.map((t) => {
                        const v = row[t];
                        return (
                          <td
                            key={t}
                            className="px-0.5 py-0.5 text-right"
                            style={{ color: rioColor(v * 10) }}
                          >
                            {v}
                          </td>
                        );
                      })}
                    </tr>
                  ))}
                </tbody>
              </table>
            </div>
          )}
        </Panel>
        </>
      }
    />
  );
}
