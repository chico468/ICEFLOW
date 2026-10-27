/**
 * Plan: choose a passage, compare distinct safety-constrained objective profiles, and select
 * the evaluated route that will be used when the voyage starts.
 *
 * Layout. The chart fills the working area. The planning controls are one command bar across the
 * top, and the compact comparison cards stay in the existing result tray along the bottom.
 *
 * Every candidate is searched and evaluated using the same environment and voyage physics.
 * Balanced remains the fixed delta reference, regardless of which route is selected.
 */
import { useState, type ReactNode } from 'react';
import {
  AlertTriangle,
  ArrowRight,
  ChevronDown,
  ChevronUp,
  Play,
} from 'lucide-react';
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
import { getRouteAlternatives } from '../api/client';
import { useEndpoints, useForecastSkill, useVessels } from '../api/queries';
import { ChartViews } from '../components/ChartViews';
import { MapStage } from '../components/MapStage';
import { Badge, ComputeOverlay, EmptyState, ErrorNote, KeyValue, Panel, Select, Slider, Toggle } from '../components/ui';
import { Explain } from '../components/Explain';
import { useScene } from '../hooks/useScene';
import { hoursToDhm, num, tenths } from '../lib/format';
import { routeDeltas } from '../lib/routeComparison';
import { MAP_COLORS, rioColor } from '../map/palette';
import { useAppStore } from '../store/useAppStore';
import type { IceClassKey, RouteAlternative, RouteEvaluation, RouteProfileId } from '../api/types';
import type { LayerToggles } from '../map/MapEngine';
import { SimulatedNotice } from '../components/SimulatedNotice';
import { useIcePoint } from '../api/queries';
import { modeAvailability } from '../map/iceModes';

const ICE_CLASSES: IceClassKey[] = [
  'PC1', 'PC2', 'PC3', 'PC4', 'PC5', 'PC6', 'PC7',
  'IA_Super', 'IA', 'IB', 'IC', 'Not_Ice_Strengthened',
];

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

export function VoyagePlanner(): JSX.Element {
  const { scene, fitTargets } = useScene();
  const { endpoints, loading: endpointsLoading } = useEndpoints();
  const vessels = useVessels();
  const leadHours = useAppStore((s) => s.leadHours);
  const modeAvail = modeAvailability(scene.iceField, leadHours, {
    field: scene.iceFieldBase,
    loading: scene.status.baseLoading,
    error: scene.status.baseError,
  });
  const skill = useForecastSkill();
  const inspect = useAppStore((s) => s.inspect);
  const point = useIcePoint(inspect?.lat ?? null, inspect?.lon ?? null, leadHours);

  const planner = useAppStore((s) => s.planner);
  const setPlanner = useAppStore((s) => s.setPlanner);
  const plan = useAppStore((s) => s.plan);
  const setPlan = useAppStore((s) => s.setPlan);
  const routeAlternatives = useAppStore((s) => s.routeAlternatives);
  const selectedCandidateId = useAppStore((s) => s.selectedCandidateId);
  const setRouteAlternatives = useAppStore((s) => s.setRouteAlternatives);
  const setSelectedCandidateId = useAppStore((s) => s.setSelectedCandidateId);
  const alternativesPlanningMs = useAppStore((s) => s.alternativesPlanningMs);
  const omittedProfiles = useAppStore((s) => s.omittedProfiles);
  const phase = useAppStore((s) => s.planPhase);
  const planError = useAppStore((s) => s.planError);
  const setPhase = useAppStore((s) => s.setPlanPhase);
  const setInspect = useAppStore((s) => s.setInspect);
  const simpleMode = useAppStore((s) => s.simpleMode);
  const setScreen = useAppStore((s) => s.setScreen);
  const rasterMode = useAppStore((s) => s.rasterMode);
  const setRasterMode = useAppStore((s) => s.setRasterMode);
  const rasterOpacity = useAppStore((s) => s.rasterOpacity);
  const setRasterOpacity = useAppStore((s) => s.setRasterOpacity);
  const setLeadHours = useAppStore((s) => s.setLeadHours);
  const layers = useAppStore((s) => s.layers);
  const toggleLayer = useAppStore((s) => s.toggleLayer);

  const [elapsed, setElapsed] = useState(0);
  const [trayOpen, setTrayOpen] = useState(true);
  const [expandedCandidateId, setExpandedCandidateId] = useState<RouteProfileId | null>(null);

  const options = endpoints.map((e) => ({
    value: e.id,
    label: `${e.name}${e.inland ? ' (inland — routes to anchorage)' : ''}`,
  }));
  const vesselOptions = (vessels.data?.vessels ?? []).map((v) => ({
    value: v.key,
    label: `${v.display_name} — ${v.ice_class}, ${num(v.installed_power_kw / 1000, 1)} MW`,
  }));

  async function runPlan(): Promise<void> {
    const requestedPlanner = JSON.stringify(planner);
    setPhase('planning');
    setPlan(null);
    setRouteAlternatives(null);
    setElapsed(0);
    const started = performance.now();
    const timer = window.setInterval(() => setElapsed(performance.now() - started), 100);
    try {
      const result = await getRouteAlternatives({
        origin_id: planner.originId,
        destination_id: planner.destinationId,
        vessel_key: planner.vesselKey,
        ice_class: planner.iceClass,
        weights: planner.weights,
        grid_resolution_deg: planner.gridResolutionDeg,
        avoid_icebergs: planner.avoidIcebergs,
        departure_time_hours: planner.departureTimeHours,
      });
      if (JSON.stringify(useAppStore.getState().planner) !== requestedPlanner) return;
      setPlan(result.balanced_summary);
      setRouteAlternatives(result);
      setPhase('ready');
    } catch (err) {
      if (JSON.stringify(useAppStore.getState().planner) !== requestedPlanner) return;
      setPhase('error', err instanceof Error ? err.message : String(err));
    } finally {
      window.clearInterval(timer);
    }
  }

  const destination = endpoints.find((e) => e.id === planner.destinationId);

  // ------------------------------------------------------------------ the command bar (left dock: Plan tab)
  const bar = (
    <div className="px-5 py-3.5">
      <div className="flex flex-wrap items-end gap-x-6 gap-y-3">
        <Group title="Passage" subtitle="Origin and destination">
          {endpointsLoading ? (
            <div className="h-[52px]">
              <div className="text-xs text-ink-2">Loading</div>
              <div className="text-2xs text-ink-3">Fetching stations and ports.</div>
            </div>
          ) : (
            <div className="flex items-end gap-2">
              <div className="w-[215px]">
                <Select
                  label="Origin"
                  value={planner.originId}
                  options={options}
                  onChange={(v) => setPlanner({ originId: v })}
                />
              </div>
              <ArrowRight size={16} className="mb-2.5 shrink-0 text-ink-3" aria-hidden />
              <div className="w-[215px]">
                <Select
                  label="Destination"
                  value={planner.destinationId}
                  options={options}
                  onChange={(v) => setPlanner({ destinationId: v })}
                />
              </div>
            </div>
          )}
        </Group>

        <Group title="Vessel">
          <div className="flex items-end gap-2">
            <div className="w-[300px]">
              <Select
                label="Ship"
                value={planner.vesselKey}
                options={vesselOptions.length ? vesselOptions : [{ value: planner.vesselKey, label: 'Loading…' }]}
                onChange={(v) => setPlanner({ vesselKey: v })}
              />
            </div>
            <div className="w-[120px]">
              <Select
                label="Ice class"
                value={planner.iceClass}
                options={ICE_CLASSES.map((c) => ({ value: c, label: c.replace(/_/g, ' ') }))}
                onChange={(v) => setPlanner({ iceClass: v })}
              />
            </div>
          </div>
        </Group>

        <div className="flex flex-col gap-1 whitespace-nowrap pb-1 text-2xs text-ink-3">
          <Explain term="ice_class">
            <span>What is an ice class?</span>
          </Explain>
          <Explain term="polaris">
            <span>What are the safety rules?</span>
          </Explain>
        </div>

        <div className="ml-auto flex shrink-0 flex-col items-end gap-1">
          {simpleMode && <span className="display text-[13px] text-ink">Plan the passage</span>}
          <div className="flex items-center gap-2">
            <button
              type="button"
              className="btn btn-accent h-10 whitespace-nowrap px-5 text-sm"
              disabled={phase === 'planning'}
              onClick={() => void runPlan()}
            >
              <Play size={14} />
              {phase === 'planning' ? 'Planning…' : 'Plan voyage'}
            </button>
          </div>
        </div>
      </div>

      {destination?.inland && (
        <p className="mt-2.5 text-2xs text-caution">
          {destination.name} is inland. Ships route to its anchorage at{' '}
          {num(destination.anchorageLat, 2)}, {num(destination.anchorageLon, 2)} —{' '}
          {destination.portApproach || 'the shelf-ice edge'} — and cargo moves overland.
        </p>
      )}

      {!simpleMode && (
        <div className="mt-3 border-t border-hair pt-3">
          <div className="mb-2 flex items-baseline gap-2">
            <span className="display text-[13px] text-ink">Objective weights</span>
            <span className="text-2xs text-ink-3">What the optimiser is trading off</span>
          </div>
          <div className="grid grid-cols-2 items-end gap-x-6 gap-y-3 md:grid-cols-5">
            <Slider
              label="Fuel"
              value={planner.weights.fuel}
              min={0}
              max={4}
              step={0.1}
              display={num(planner.weights.fuel, 1)}
              onChange={(v) => setPlanner({ weights: { ...planner.weights, fuel: v } })}
            />
            <Slider
              label="Time"
              value={planner.weights.time}
              min={0}
              max={4}
              step={0.05}
              display={num(planner.weights.time, 2)}
              onChange={(v) => setPlanner({ weights: { ...planner.weights, time: v } })}
            />
            <Slider
              label="Risk"
              value={planner.weights.risk}
              min={0}
              max={8}
              step={0.1}
              display={num(planner.weights.risk, 1)}
              onChange={(v) => setPlanner({ weights: { ...planner.weights, risk: v } })}
            />
            <Slider
              label="Lattice resolution"
              value={planner.gridResolutionDeg}
              min={0.25}
              max={1.5}
              step={0.25}
              display={`${num(planner.gridResolutionDeg, 2)}°`}
              onChange={(v) => setPlanner({ gridResolutionDeg: v })}
            />
            <Toggle
              label="Avoid tracked icebergs"
              checked={planner.avoidIcebergs}
              onChange={(v) => setPlanner({ avoidIcebergs: v })}
              hint="Keep-out zones follow each berg's forecast drift track, not its position today."
            />
          </div>
        </div>
      )}

      <p className="mt-2.5 text-2xs text-ink-3">
        One shared environmental cache supports up to four independently weighted, safety-constrained route searches.
        Every candidate is evaluated with the same voyage physics.
      </p>
      {planError && (
        <div className="mt-2">
          <ErrorNote message={planError} onRetry={() => void runPlan()} />
        </div>
      )}
    </div>
  );

  // ------------------------------------------------------------------ the result tray (right dock: Routes tab)
  const balancedReference = routeAlternatives.find((candidate) => candidate.id === 'balanced')?.evaluation
    ?? plan?.optimized
    ?? null;
  const selectedCandidate = routeAlternatives.find((candidate) => candidate.id === selectedCandidateId) ?? null;
  const tray = !plan ? (
    <div className="flex justify-center">
      <div className="pointer-events-auto px-6 py-3 text-center">
        {phase === 'error' ? (
          <ErrorNote message={planError ?? 'Route comparison could not be completed.'} onRetry={() => void runPlan()} />
        ) : (
          <>
            <div className="display text-[15px] text-ink-2">No route comparison yet</div>
            <div className="text-xs text-ink-3">Configure the passage and press Plan voyage.</div>
          </>
        )}
      </div>
    </div>
  ) : (
    <div className="pointer-events-auto overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="display truncate text-base text-ink">Compare calculated route options</h2>
          <span className="hidden truncate text-2xs text-ink-3 xl:inline">
            Fuel and time deltas use Balanced as a fixed reference, independent of selection.
          </span>
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone="accent">{plan.vessel_name}</Badge>
          {alternativesPlanningMs !== null && (
            <Badge title="Measured server planning duration">{num(alternativesPlanningMs / 1000, 1)} s</Badge>
          )}
          <button
            type="button"
            className="btn-icon !h-8 !w-8"
            aria-expanded={trayOpen}
            aria-label={trayOpen ? 'Collapse route comparison' : 'Expand route comparison'}
            onClick={() => setTrayOpen((v) => !v)}
          >
            {trayOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </div>
      </header>

      {trayOpen && (
        <div className="overflow-y-auto border-t border-hair px-4 py-3">
          <div className="mb-3 flex flex-wrap items-baseline justify-between gap-2 text-2xs text-ink-3">
            <span>
              Reference: <strong className="text-ink">Balanced</strong> · absolute modelled values shown; deltas are against this route.
            </span>
            <span>{routeAlternatives.filter((candidate) => candidate.is_feasible).length} feasible distinct alternative(s)</span>
          </div>
          {routeAlternatives.length === 0 ? (
            <Notice tone="danger">No distinct route candidates were returned. Recheck the voyage conditions and try planning again.</Notice>
          ) : (
            <div data-testid="route-widget-row" className="flex snap-x gap-2.5 overflow-x-auto pb-1">
              {routeAlternatives.map((candidate) => (
                <RouteCandidateCard
                  key={candidate.id}
                  candidate={candidate}
                  reference={balancedReference}
                  selected={candidate.id === selectedCandidateId}
                  onSelect={() => setSelectedCandidateId(candidate.id)}
                  expanded={expandedCandidateId === candidate.id}
                  onToggleExpanded={() => setExpandedCandidateId((current) => (
                    current === candidate.id ? null : candidate.id
                  ))}
                />
              ))}
            </div>
          )}
          {omittedProfiles.map((omitted) => (
            <p key={omitted.profile_id} role="status" className="mt-2 text-2xs text-ink-3">
              {omitted.profile_id.replace(/-/g, ' ')} omitted: {omitted.reason}
            </p>
          ))}
          {routeAlternatives.some((candidate) => !candidate.is_feasible) && (
            <Notice tone="danger">
              Partial or infeasible routes remain visible for context but cannot be selected for sailing.
            </Notice>
          )}
          {routeAlternatives.length > 0 && !selectedCandidate && (
            <Notice tone="danger">No feasible candidate is selected. Do not start a voyage until a feasible route is available.</Notice>
          )}
          {routeAlternatives.some((candidate) => candidate.is_synthetic_environment) && (
            <SimulatedNotice />
          )}
          <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-hair pt-3">
            <p className="text-xs text-ink-2">
              {selectedCandidate
                ? `${selectedCandidate.name} is selected. It will be replanned with these weights when started in Sail.`
                : 'Select a feasible candidate before sailing.'}
            </p>
            <button
              type="button"
              className="btn btn-accent"
              disabled={!selectedCandidate?.is_feasible}
              onClick={() => setScreen('bridge')}
            >
              Continue to Sail
            </button>
          </div>
          {plan.baseline_would_be_prohibited && (
            <p className="mt-2 text-2xs text-ink-3">
              Separate context only: the ice-blind baseline has RIO {plan.baseline?.minimum_rio} and violates POLARIS. It is not selectable.
            </p>
          )}
          {routeAlternatives.flatMap((candidate) => candidate.warnings.map((warning) => (
            <p key={`${candidate.id}-${warning}`} className="mt-1 text-2xs text-danger">
              {candidate.name}: {warning}
            </p>
          )))}
          {!simpleMode && plan.search && (
            <p className="mt-2 text-2xs text-ink-3">
              Balanced search: {num(plan.search.nodes_expanded, 0)} nodes · {num(plan.search.search_ms, 0)} ms · {num(plan.search.lattice_cells, 0)} lattice cells.
            </p>
          )}
        </div>
      )}
    </div>
  );

  // ------------------------------------------------------------------------- the map
  const map = (
    <>
      <ChartViews
        scene={scene}
        fitTargets={fitTargets}
        onClickPoint={(ll) => setInspect(ll)}
        onSelectRouteCandidate={setSelectedCandidateId}
      />
      {phase === 'planning' && (
        <ComputeOverlay
          title="Planning"
          elapsedMs={elapsed}
          expectedMs={60_000}
          steps={[
            'Building one shared environmental field cache',
            'Forecasting iceberg exclusion zones once for all profiles',
            'Searching Balanced and Safety-first objectives',
            'Searching Fuel-efficient and Fastest objectives',
            'Evaluating each distinct route with the same voyage physics',
          ]}
        />
      )}
    </>
  );

  // ------------------------------------------------------------------ left dock: Plan + Layers
  const leftDock = (
    <>
      <Panel
        title="Plan"
        right={phase === 'ready' ? <Badge tone="ok">Ready</Badge> : phase === 'planning' ? <Badge tone="caution">Planning…</Badge> : undefined}
        className="shrink-0"
      >
        {bar}
      </Panel>

      <Panel title="Layers" subtitle="What the chart draws">
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
        <Slider
          label="Forecast time"
          value={leadHours}
          min={0}
          max={168}
          step={6}
          display={`+${num(leadHours, 0)} h`}
          onChange={setLeadHours}
        />
        <div className="mt-2 grid grid-cols-2 gap-1">
          {LAYER_LABELS.map(({ key, label }) => (
            <Toggle key={key} label={label} checked={layers[key]} onChange={() => toggleLayer(key)} />
          ))}
        </div>
      </Panel>
    </>
  );

  // ------------------------------------------------------------------ right dock: Inspect + Routes + Evidence
  const skillRows = (skill.data?.rows ?? []).map((r) => ({
    lead: r.lead_hours,
    forecast: r.rmse,
    persistence: r.persistence_rmse,
    iiee: r.iiee_fraction,
    skillScore: r.skill_score_vs_persistence,
  }));

  const rightDock = (
    <>
      <Panel
        title="Inspect"
        subtitle={inspect ? undefined : 'Click the chart'}
      >
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
          </>
        )}
      </Panel>

      <Panel
        title="Routes"
        right={<Badge tone="accent">{routeAlternatives.length} candidates</Badge>}
      >
        {tray}
      </Panel>

      <Panel
        title="Evidence"
        subtitle="Forecast skill vs persistence"
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
          </>
        )}
      </Panel>
    </>
  );

  return <MapStage id="plan" map={map} leftDock={leftDock} rightDock={rightDock} leftDockLabel="Plan" rightDockLabel="Details" />;
}

// ----------------------------------------------------------------------------- pieces

function Group({ title, subtitle, children }: { title: string; subtitle?: string; children: ReactNode }): JSX.Element {
  return (
    <div>
      <div className="mb-1.5 flex items-baseline gap-2">
        <span className="display text-[13px] text-ink">{title}</span>
        {subtitle && <span className="text-2xs text-ink-3">{subtitle}</span>}
      </div>
      {children}
    </div>
  );
}

function Notice({ tone, children }: { tone: 'danger' | 'caution'; children: ReactNode }): JSX.Element {
  const cls =
    tone === 'danger'
      ? 'border-danger/40 bg-danger/10 text-danger'
      : 'border-caution/40 bg-caution/10 text-caution';
  return (
    <div className={`mt-2 flex items-start gap-2 rounded-lg border p-2 text-2xs ${cls}`}>
      <AlertTriangle size={13} className="mt-0.5 shrink-0" />
      <span>{children}</span>
    </div>
  );
}

function routeColor(id: RouteProfileId): string {
  switch (id) {
    case 'safety-first': return MAP_COLORS.routeSafetyFirst;
    case 'balanced': return MAP_COLORS.routeBalanced;
    case 'fuel-efficient': return MAP_COLORS.routeFuelEfficient;
    case 'fastest': return MAP_COLORS.routeFastest;
  }
}

function compareDelta(value: number, unit: string, positiveText: string, negativeText: string): string {
  if (!Number.isFinite(value)) return 'Comparison unavailable';
  if (Math.abs(value) < 0.005) return `Same as Balanced`;
  return `${num(Math.abs(value), 1)} ${unit} ${value > 0 ? positiveText : negativeText} Balanced`;
}

function RouteCandidateCard({
  candidate,
  reference,
  selected,
  onSelect,
  expanded,
  onToggleExpanded,
}: {
  candidate: RouteAlternative;
  reference: RouteEvaluation | null;
  selected: boolean;
  onSelect: () => void;
  expanded: boolean;
  onToggleExpanded: () => void;
}): JSX.Element {
  const result = candidate.evaluation;
  const deltas = reference ? routeDeltas(result, reference) : null;
  const advantages: string[] = [];
  const tradeoffs: string[] = [];
  if (candidate.is_feasible) advantages.push('Reached destination; hard route constraints met.');
  if (reference && deltas && candidate.id !== 'balanced') {
    if (deltas.fuelSavedTonnes > 0.05) advantages.push(`${num(deltas.fuelSavedTonnes, 1)} t less fuel than Balanced.`);
    if (deltas.timeSavedHours > 0.1) advantages.push(`${hoursToDhm(deltas.timeSavedHours)} shorter than Balanced.`);
    if (deltas.distanceSavedNm > 0.5) advantages.push(`${num(deltas.distanceSavedNm, 0)} nm shorter than Balanced.`);
    if (result.minimum_rio > reference.minimum_rio) advantages.push(`Higher minimum RIO (${result.minimum_rio}); higher RIO is safer.`);
    if (deltas.fuelSavedTonnes < -0.05) tradeoffs.push(`${num(-deltas.fuelSavedTonnes, 1)} t more fuel than Balanced.`);
    if (deltas.timeSavedHours < -0.1) tradeoffs.push(`${hoursToDhm(-deltas.timeSavedHours)} longer than Balanced.`);
    if (deltas.distanceSavedNm < -0.5) tradeoffs.push(`${num(-deltas.distanceSavedNm, 0)} nm longer than Balanced.`);
    if (result.minimum_rio < reference.minimum_rio) tradeoffs.push(`Lower minimum RIO (${result.minimum_rio}); higher RIO is safer.`);
    if (result.max_compression_index > reference.max_compression_index + 0.01) {
      tradeoffs.push(`Higher maximum compression (${num(result.max_compression_index, 2)}).`);
    }
  }
  if (!candidate.is_feasible) tradeoffs.unshift(result.infeasible_reason || 'Partial or infeasible route; not selectable.');

  const detailsId = `route-details-${candidate.id}`;
  const minRio = Number.isFinite(result.minimum_rio) ? String(result.minimum_rio) : '--';
  const safetyText = candidate.is_feasible
    ? `Min RIO ${minRio}`
    : candidate.goal_reached ? 'Infeasible' : 'Partial route';

  return (
    <article
      data-testid="route-candidate"
      data-candidate-id={candidate.id}
      className={`w-[250px] min-w-[250px] snap-start self-start rounded-md border transition-colors motion-reduce:transition-none sm:flex-1 sm:basis-0 ${selected ? 'border-accent bg-panel-2 ring-1 ring-accent/40' : 'border-hair bg-panel'}`}
      aria-current={selected ? 'true' : undefined}
    >
      <div className="flex items-start gap-1.5 p-2.5">
        <button
          type="button"
          className="min-w-0 flex-1 rounded-sm text-left focus-visible:outline focus-visible:outline-2 focus-visible:outline-offset-2 focus-visible:outline-accent"
          disabled={!candidate.is_feasible}
          aria-pressed={selected}
          aria-label={`Select ${candidate.name} route`}
          onClick={onSelect}
        >
          <span className="flex min-w-0 items-center gap-2">
            <span className="h-[3px] w-5 shrink-0 rounded-full" style={{ backgroundColor: routeColor(candidate.id) }} aria-hidden />
            <span className="display truncate text-[14px] text-ink">{candidate.name}</span>
            {selected && <span className="shrink-0 rounded bg-accent/10 px-1.5 py-0.5 text-[9px] font-semibold uppercase tracking-wide text-accent">Selected</span>}
          </span>
          <span className="mt-1 flex items-center gap-1.5 text-2xs">
            <span className={candidate.is_feasible ? 'font-medium text-ok' : 'font-medium text-danger'}>
              {candidate.is_feasible ? 'Feasible' : candidate.goal_reached ? 'Infeasible' : 'Partial'}
            </span>
            <span className="text-ink-3" aria-hidden>·</span>
            <span className={Number.isFinite(result.minimum_rio) ? '' : 'text-ink-3'} style={Number.isFinite(result.minimum_rio) ? { color: rioColor(result.minimum_rio) } : undefined}>
              {safetyText}
            </span>
          </span>
        </button>
        <button
          type="button"
          className="btn-icon !h-8 !w-8 shrink-0"
          aria-expanded={expanded}
          aria-controls={detailsId}
          aria-label={`${expanded ? 'Collapse' : 'Expand'} ${candidate.name} route details`}
          onClick={onToggleExpanded}
        >
          <ChevronDown size={15} className={`transition-transform motion-reduce:transition-none ${expanded ? 'rotate-180' : ''}`} />
        </button>
      </div>

      <div className="grid grid-cols-3 gap-1 border-t border-hair px-2.5 py-2 num">
        <CompactMetric label="Duration" value={hoursToDhm(result.total_transit_hours)} />
        <CompactMetric label="Fuel" value={`${num(result.total_fuel_burn_tonnes, 1)} t`} />
        <CompactMetric label="Distance" value={`${num(result.total_distance_nm, 0)} nm`} />
      </div>

      {expanded && (
        <div id={detailsId} className="border-t border-hair px-2.5 py-2.5">
          <p className="mb-2 text-2xs leading-snug text-ink-3">{candidate.description}</p>
          <div className="grid grid-cols-2 gap-x-3 gap-y-2 num">
            <Metric label="Total distance" value={`${num(result.total_distance_nm, 1)} nm`} />
            <Metric label="Modelled duration" value={`${hoursToDhm(result.total_transit_hours)} (${num(result.total_transit_hours, 1)} h)`} />
            <Metric
              label="Fuel burn"
              value={`${num(result.total_fuel_burn_tonnes, 2)} t`}
              detail={deltas ? compareDelta(deltas.fuelSavedTonnes, 't', 'less than', 'more than') : 'Balanced reference unavailable'}
            />
            <Metric
              label="Time vs Balanced"
              value={deltas ? compareDelta(deltas.timeSavedHours, 'h', 'shorter than', 'longer than') : 'Balanced reference unavailable'}
            />
            <Metric
              label="CO₂ emissions"
              value={`${num(result.total_co2_tonnes, 2)} t`}
              detail={deltas ? compareDelta(deltas.co2SavedTonnes, 't', 'less than', 'more than') : 'Balanced reference unavailable'}
            />
            <Metric
              label="Distance vs Balanced"
              value={deltas ? compareDelta(deltas.distanceSavedNm, 'nm', 'shorter than', 'longer than') : 'Balanced reference unavailable'}
            />
          </div>
          <div className="mt-2 border-t border-hair pt-2">
            <div className="text-2xs font-semibold text-ink-2">Evaluated safety</div>
            <div className="mt-1 grid grid-cols-2 gap-x-2 gap-y-1 text-2xs text-ink-2">
              <span style={Number.isFinite(result.minimum_rio) ? { color: rioColor(result.minimum_rio) } : undefined}>
                Minimum RIO {minRio}{Number.isFinite(result.minimum_rio) ? ' · higher is safer' : ''}
              </span>
              <span>Mean RIO {num(result.mean_rio, 1)}</span>
              <span>Max compression {num(result.max_compression_index, 2)}</span>
              <span>Max ice {num(result.max_ice_thickness_m, 2)} m</span>
              <span>{num(result.prohibited_waypoints, 0)} prohibited waypoint(s)</span>
              <span>{candidate.is_feasible ? 'Feasibility: reached and permitted' : candidate.goal_reached ? 'Feasibility: prohibited' : 'Feasibility: destination not reached'}</span>
            </div>
            <p className="mt-1 text-2xs text-ink-3">
              Weights · fuel {num(candidate.weights.fuel, 2)} · time {num(candidate.weights.time, 2)} · risk {num(candidate.weights.risk, 2)}
            </p>
          </div>
          {(advantages.length > 0 || tradeoffs.length > 0) && (
            <div className="mt-2 grid gap-1 border-t border-hair pt-2 text-2xs leading-snug">
              {advantages.slice(0, 2).map((advantage) => <p key={advantage} className="text-ok">+ {advantage}</p>)}
              {tradeoffs.slice(0, 2).map((tradeoff) => <p key={tradeoff} className="text-caution">− {tradeoff}</p>)}
              {candidate.id === 'balanced' && <p className="text-ink-3">Fixed comparison reference: current objective weights.</p>}
            </div>
          )}
          {candidate.warnings.map((warning) => (
            <p key={warning} className="mt-2 text-2xs leading-snug text-danger">{warning}</p>
          ))}
        </div>
      )}
    </article>
  );
}

function CompactMetric({ label, value }: { label: string; value: string }): JSX.Element {
  return (
    <div className="min-w-0">
      <div className="text-[9px] leading-tight text-ink-3">{label}</div>
      <div className="truncate text-[11px] font-semibold text-ink" title={value}>{value}</div>
    </div>
  );
}

function Metric({ label, value, detail }: { label: string; value: string; detail?: string }): JSX.Element {
  return (
    <div className="min-w-0">
      <div className="text-2xs text-ink-3">{label}</div>
      <div className="truncate text-xs text-ink">{value}</div>
      {detail && <div className="mt-0.5 truncate text-2xs text-ink-3">{detail}</div>}
    </div>
  );
}
