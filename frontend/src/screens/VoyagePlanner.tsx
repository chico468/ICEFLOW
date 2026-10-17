/**
 * Plan: choose a passage, plan it, and see the recommended route measured against the route a
 * ship would sail with no ice information.
 *
 * Layout. The chart fills the working area. The planning controls are one command bar across the
 * top, and the result is a single tray along the bottom, so the map is never shared with a column
 * of forms. Everything shown is exactly what the original screen showed: same fields, same
 * wording, same numbers.
 *
 * The comparison is deliberately unflattering. The saving is the difference between two model
 * runs, so it is allowed to come out negative, and on some legs it does, because going around
 * the ice costs more fuel than it saves. Showing that honestly is worth more than a number that
 * always looks good.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { AlertTriangle, ArrowRight, ChevronDown, ChevronUp, Play, Route } from 'lucide-react';
import { optimizeRoute } from '../api/client';
import { useEndpoints, useVessels } from '../api/queries';
import { MapCanvas } from '../map/MapCanvas';
import { MapStage } from '../components/MapStage';
import { Badge, ComputeOverlay, ErrorNote, KeyValue, Select, Slider, Stat, Toggle } from '../components/ui';
import { Explain } from '../components/Explain';
import { useScene } from '../hooks/useScene';
import { hoursToDhm, num, signed } from '../lib/format';
import { rioColor } from '../map/palette';
import { useAppStore } from '../store/useAppStore';
import type { IceClassKey, RouteEvaluation } from '../api/types';

const ICE_CLASSES: IceClassKey[] = [
  'PC1', 'PC2', 'PC3', 'PC4', 'PC5', 'PC6', 'PC7',
  'IA_Super', 'IA', 'IB', 'IC', 'Not_Ice_Strengthened',
];

export function VoyagePlanner(): JSX.Element {
  const { scene, fitTargets } = useScene();
  const { endpoints, loading: endpointsLoading } = useEndpoints();
  const vessels = useVessels();

  const planner = useAppStore((s) => s.planner);
  const setPlanner = useAppStore((s) => s.setPlanner);
  const plan = useAppStore((s) => s.plan);
  const setPlan = useAppStore((s) => s.setPlan);
  const phase = useAppStore((s) => s.planPhase);
  const planError = useAppStore((s) => s.planError);
  const setPhase = useAppStore((s) => s.setPlanPhase);
  const setInspect = useAppStore((s) => s.setInspect);
  const simpleMode = useAppStore((s) => s.simpleMode);

  const [elapsed, setElapsed] = useState(0);
  const [trayOpen, setTrayOpen] = useState(true);
  // Once a route is planned the command bar shrinks to a one-line summary, giving the chart
  // back its height. "Edit" reopens it.
  const [barOpen, setBarOpen] = useState(true);
  useEffect(() => {
    if (phase === 'ready') setBarOpen(false);
  }, [phase]);

  const options = endpoints.map((e) => ({
    value: e.id,
    label: `${e.name}${e.inland ? ' (inland — routes to anchorage)' : ''}`,
  }));
  const vesselOptions = (vessels.data?.vessels ?? []).map((v) => ({
    value: v.key,
    label: `${v.display_name} — ${v.ice_class}, ${num(v.installed_power_kw / 1000, 1)} MW`,
  }));

  async function runPlan(): Promise<void> {
    setPhase('planning');
    setElapsed(0);
    const started = performance.now();
    const timer = window.setInterval(() => setElapsed(performance.now() - started), 100);
    try {
      const result = await optimizeRoute({
        origin_id: planner.originId,
        destination_id: planner.destinationId,
        vessel_key: planner.vesselKey,
        ice_class: planner.iceClass,
        weights: planner.weights,
        grid_resolution_deg: planner.gridResolutionDeg,
        avoid_icebergs: planner.avoidIcebergs,
        departure_time_hours: planner.departureTimeHours,
      });
      setPlan(result);
      setPhase('ready');
    } catch (err) {
      setPhase('error', err instanceof Error ? err.message : String(err));
    } finally {
      window.clearInterval(timer);
    }
  }

  const destination = endpoints.find((e) => e.id === planner.destinationId);
  const originName = endpoints.find((e) => e.id === planner.originId)?.name ?? planner.originId;
  const shipName = vessels.data?.vessels.find((v) => v.key === planner.vesselKey)?.display_name ?? planner.vesselKey;

  // ------------------------------------------------------------------ the command bar
  const bar = (
    <div className="float px-5 py-3.5">
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
            {plan && (
              <button
                type="button"
                className="btn-icon !h-10 !w-10"
                aria-label="Collapse the passage controls"
                onClick={() => setBarOpen(false)}
              >
                <ChevronUp size={16} />
              </button>
            )}
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
        {simpleMode
          ? 'This works out two routes — one that ignores the ice, and one that avoids it — then sails both through the same physics so the difference is real. Takes about 15 seconds.'
          : 'Two independent searches, then both tracks sailed through identical physics. Takes 15 to 30 seconds.'}
      </p>
      {planError && (
        <div className="mt-2">
          <ErrorNote message={planError} onRetry={() => void runPlan()} />
        </div>
      )}
    </div>
  );

  const summary = (
    <div className="float flex items-center gap-4 px-5 py-2.5">
      <div className="flex min-w-0 flex-1 items-center gap-2 text-sm text-ink">
        <span className="truncate font-semibold">{originName}</span>
        <ArrowRight size={14} className="shrink-0 text-ink-3" aria-hidden />
        <span className="truncate font-semibold">{destination?.name ?? planner.destinationId}</span>
        <span className="hidden truncate text-xs text-ink-3 md:inline">
          {shipName} · {planner.iceClass.replace(/_/g, ' ')}
        </span>
      </div>
      <button type="button" className="btn" onClick={() => setBarOpen(true)}>
        Edit
      </button>
      <button
        type="button"
        className="btn btn-accent whitespace-nowrap"
        disabled={phase === 'planning'}
        onClick={() => void runPlan()}
      >
        <Play size={13} />
        {phase === 'planning' ? 'Planning…' : 'Plan voyage'}
      </button>
    </div>
  );
  const top = barOpen ? bar : summary;

  // ------------------------------------------------------------------ the result tray
  const tray = !plan ? (
    <div className="flex justify-center">
      <div className="float pointer-events-auto px-6 py-3 text-center">
        <div className="display text-[15px] text-ink-2">No plan yet</div>
        <div className="text-xs text-ink-3">Configure the passage and press Plan voyage.</div>
      </div>
    </div>
  ) : (
    <div className="float pointer-events-auto overflow-hidden">
      <header className="flex items-center justify-between gap-3 px-5 py-3">
        <div className="flex min-w-0 items-baseline gap-3">
          <h2 className="display truncate text-base text-ink">Recommended route vs the route without ice data</h2>
          {plan.savings_method && <span className="hidden truncate text-2xs text-ink-3 xl:inline">{plan.savings_method}</span>}
        </div>
        <div className="flex shrink-0 items-center gap-2">
          <Badge tone="accent">{plan.vessel_name}</Badge>
          <button
            type="button"
            className="btn-icon !h-8 !w-8"
            aria-expanded={trayOpen}
            aria-label={trayOpen ? 'Collapse the result' : 'Expand the result'}
            onClick={() => setTrayOpen((v) => !v)}
          >
            {trayOpen ? <ChevronDown size={16} /> : <ChevronUp size={16} />}
          </button>
        </div>
      </header>

      {trayOpen && (
        <div className="grid max-h-[46vh] gap-x-6 gap-y-4 overflow-y-auto border-t border-hair px-5 py-4 xl:grid-cols-[minmax(0,1.05fr)_minmax(0,0.85fr)_minmax(0,2fr)]">
            <p className="self-start rounded-lg border border-hair bg-panel-2 p-3 text-xs2 leading-relaxed text-ink-2">
              <strong className="text-ink">In plain terms: </strong>
              the recommended route is{' '}
              <strong className="text-ink">
                {Math.abs(plan.distance_delta_nm).toFixed(0)} nm{' '}
                {plan.distance_delta_nm >= 0 ? 'longer' : 'shorter'}
              </strong>{' '}
              but arrives{' '}
              <strong className={plan.time_saved_hours >= 0 ? 'text-ok' : 'text-danger'}>
                {hoursToDhm(Math.abs(plan.time_saved_hours))}{' '}
                {plan.time_saved_hours >= 0 ? 'sooner' : 'later'}
              </strong>{' '}
              and uses{' '}
              <strong className={plan.fuel_saved_percentage >= 0 ? 'text-ok' : 'text-danger'}>
                {Math.abs(plan.fuel_saved_percentage).toFixed(1)}%{' '}
                {plan.fuel_saved_percentage >= 0 ? 'less' : 'more'} fuel
              </strong>
              . Its worst ice-risk score is{' '}
              <strong style={{ color: rioColor(plan.optimized?.minimum_rio ?? 0) }}>
                {plan.optimized?.minimum_rio}
              </strong>{' '}
              against{' '}
              <strong style={{ color: rioColor(plan.baseline?.minimum_rio ?? 0) }}>
                {plan.baseline?.minimum_rio}
              </strong>{' '}
              for the ice-blind route — higher is safer.
            </p>

            <div className="grid grid-cols-2 content-start gap-x-4 gap-y-3">
              <Stat
                label="Fuel saved"
                value={signed(plan.fuel_saved_percentage, 2)}
                unit="%"
                size="lg"
                tone={plan.fuel_saved_percentage >= 0 ? 'ok' : 'danger'}
                hint={plan.fuel_saved_percentage < 0 ? 'The safe route burns more' : undefined}
              />
              <Stat
                label="Time saved"
                value={num(plan.time_saved_hours, 0)}
                unit="h"
                size="lg"
                tone={plan.time_saved_hours >= 0 ? 'ok' : 'danger'}
                hint={hoursToDhm(Math.abs(plan.time_saved_hours))}
              />
              <Stat
                label="CO2 avoided"
                value={signed(plan.co2_saved_tonnes, 1)}
                unit="t"
                tone={plan.co2_saved_tonnes >= 0 ? 'ok' : 'danger'}
              />
              <Stat
                label="Extra distance"
                value={signed(plan.distance_delta_nm, 0)}
                unit="nm"
                tone="muted"
              />
            </div>

          <div className="min-w-0">
            <div className="overflow-x-auto">
              <table className="w-full min-w-[540px] text-xs2">
                <thead>
                  <tr className="text-2xs text-ink-3">
                    <th className="py-1 text-left font-normal">Route</th>
                    <th className="py-1 text-right font-normal">Distance</th>
                    <th className="py-1 text-right font-normal">Time</th>
                    <th className="py-1 text-right font-normal">Fuel</th>
                    <th className="py-1 text-right font-normal">min RIO</th>
                    <th className="py-1 text-right font-normal">Max compr.</th>
                    <th className="py-1 text-right font-normal">Feasible</th>
                  </tr>
                </thead>
                <tbody className="num">
                  {[plan.baseline, plan.optimized].filter(Boolean).map((r) => (
                    <RouteRow key={(r as RouteEvaluation).label} evaluation={r as RouteEvaluation} />
                  ))}
                </tbody>
              </table>
            </div>

            {plan.baseline_would_be_prohibited && (
              <Notice tone="danger">
                The ice-blind baseline enters ice where POLARIS prohibits operation. Its fuel
                figure is what the passage would cost if it were survivable.
              </Notice>
            )}
            {plan.warnings.map((w) => (
              <Notice key={w} tone="caution">
                {w}
              </Notice>
            ))}

            {plan.search && !simpleMode && (
              <div className="mt-3 rounded-lg border border-hair p-3">
                <div className="display mb-1 text-[13px] text-ink">Search diagnostics</div>
                <div className="grid grid-cols-2 gap-x-6 md:grid-cols-4">
                  <KeyValue label="Nodes expanded" value={num(plan.search.nodes_expanded, 0)} />
                  <KeyValue label="Rejected: land" value={num(plan.search.nodes_rejected_land, 0)} />
                  <KeyValue label="Rejected: POLARIS" value={num(plan.search.nodes_rejected_rio, 0)} />
                  <KeyValue label="Rejected: icebergs" value={num(plan.search.nodes_rejected_iceberg, 0)} />
                  <KeyValue label="Rejected: clearance" value={num(plan.search.nodes_rejected_clearance, 0)} />
                  <KeyValue label="Lattice cells" value={num(plan.search.lattice_cells, 0)} />
                  <KeyValue label="A* time" value={num(plan.search.search_ms, 0)} unit="ms" />
                  <KeyValue label="Goal reached" value={plan.search.goal_reached ? 'yes' : 'no'} />
                </div>
              </div>
            )}
          </div>
        </div>
      )}
    </div>
  );

  // ------------------------------------------------------------------------- the map
  const map = (
    <>
      <MapCanvas scene={scene} fitTargets={fitTargets} onClickPoint={(ll) => setInspect(ll)} />
      {phase === 'planning' && (
        <ComputeOverlay
          title="Planning"
          elapsedMs={elapsed}
          expectedMs={30_000}
          steps={[
            'Building the search lattice and ice field cache',
            'Integrating iceberg drift tracks for the corridor',
            'Searching the ice-blind baseline route',
            'Searching the POLARIS-constrained route',
            'Sailing both tracks through the physics',
          ]}
        />
      )}
    </>
  );

  return <MapStage id="plan" map={map} top={top} tray={tray} />;
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

function RouteRow({ evaluation }: { evaluation: RouteEvaluation }): JSX.Element {
  const optimised = evaluation.label.toLowerCase().includes('optimised');
  return (
    <tr className={`border-t border-hair ${optimised ? 'text-ink' : 'text-ink-2'}`}>
      <td className="py-1.5 pr-2 font-sans">
        <span className="flex items-center gap-1.5">
          <Route size={12} className={optimised ? 'text-route' : 'text-ink-3'} />
          {evaluation.label}
        </span>
      </td>
      <td className="py-1.5 text-right">{num(evaluation.total_distance_nm, 0)} nm</td>
      <td className="py-1.5 text-right">{num(evaluation.total_transit_hours, 0)} h</td>
      <td className="py-1.5 text-right">{num(evaluation.total_fuel_burn_tonnes, 0)} t</td>
      <td className="py-1.5 text-right" style={{ color: rioColor(evaluation.minimum_rio) }}>
        {evaluation.minimum_rio}
      </td>
      <td className="py-1.5 text-right">{num(evaluation.max_compression_index, 2)}</td>
      <td className="py-1.5 text-right">
        {evaluation.is_feasible ? (
          <span className="text-ok">yes</span>
        ) : (
          <span className="text-danger" title={evaluation.infeasible_reason}>
            no
          </span>
        )}
      </td>
    </tr>
  );
}
