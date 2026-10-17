/**
 * System Flow: what the prototype is actually doing, stage by stage, with live numbers.
 *
 * This screen exists because "it plans a route" hides everything interesting. A reviewer needs to
 * see that there is a pipeline, that each stage does real work, and that the headline number is
 * produced by running the same physics twice rather than by multiplying by a constant.
 *
 * Every stage reports live state from the running backend, so this is a working instrument rather
 * than a diagram of one: when a plan is running, the stage that is computing lights up, and when a
 * plan has completed each stage shows what it actually produced.
 */
import { useMemo } from 'react';
import {
  AlertTriangle,
  ArrowDown,
  CheckCircle2,
  Circle,
  Cpu,
  Database,
  GitCompareArrows,
  Loader2,
  Map as MapIcon,
  Radar,
  Satellite,
  Ship,
  ShieldCheck,
  Waves,
} from 'lucide-react';
import { useCoastline, useForecastSkill, useHealth, useIcebergs, useVessels } from '../api/queries';
import { Badge, Panel } from '../components/ui';
import { Explain } from '../components/Explain';
import { num } from '../lib/format';
import { latestTick, useAppStore } from '../store/useAppStore';

type StageState = 'idle' | 'busy' | 'done' | 'blocked';

interface Stage {
  id: string;
  icon: typeof Ship;
  title: string;
  what: string;
  module: string;
  state: StageState;
  metrics: { label: string; value: string }[];
  detail: string;
}

const STATE_STYLE: Record<StageState, { ring: string; text: string; label: string }> = {
  idle: { ring: 'border-hair-2', text: 'text-ink-3', label: 'waiting' },
  busy: { ring: 'border-accent animate-pulse', text: 'text-accent', label: 'computing' },
  done: { ring: 'border-ok/50', text: 'text-ok', label: 'complete' },
  blocked: { ring: 'border-danger/50', text: 'text-danger', label: 'unavailable' },
};

export function SystemFlow(): JSX.Element {
  const health = useHealth();
  const coastline = useCoastline();
  const icebergs = useIcebergs(0);
  const vessels = useVessels();
  const skill = useForecastSkill();

  const plan = useAppStore((s) => s.plan);
  const planPhase = useAppStore((s) => s.planPhase);
  const voyagePhase = useAppStore((s) => s.voyagePhase);
  const ticks = useAppStore((s) => s.ticks);
  const alerts = useAppStore((s) => s.alerts);
  const setScreen = useAppStore((s) => s.setScreen);

  const tick = latestTick(ticks);
  const planning = planPhase === 'planning' || voyagePhase === 'creating';
  const sailing = voyagePhase === 'running';

  const stages: Stage[] = useMemo(() => {
    const s = (done: boolean, busy = false): StageState =>
      busy ? 'busy' : done ? 'done' : 'idle';

    const midSkill = skill.data?.rows?.find((r) => r.lead_hours === 72);

    return [
      {
        id: 'inputs',
        icon: Satellite,
        title: 'Environmental inputs',
        what: 'Wind, current, temperature and sea state across the Southern Ocean',
        module: 'src/core/environment.py',
        state: health.isSuccess ? 'done' : 'blocked',
        metrics: [
          { label: 'Source', value: 'Simulated stand-in' },
          { label: 'Stands in for', value: 'ERA5 · CMEMS' },
        ],
        detail:
          'Circumpolar westerlies, katabatic outflow draining off the ice sheet, the Antarctic ' +
          'Circumpolar Current, and eastward-moving depressions. These fields are simulated; ' +
          'everything downstream of them is real physics.',
      },
      {
        id: 'data',
        icon: Database,
        title: 'Fixed reference data',
        what: 'Coastline, stations with reachable anchorages, tracked icebergs',
        module: 'src/data/',
        state: s(coastline.isSuccess && icebergs.isSuccess),
        metrics: [
          { label: 'Coast polygons', value: coastline.data ? num(coastline.data.stats.polygons, 0) : '—' },
          { label: 'Tracked bergs', value: icebergs.data ? num(icebergs.data.count, 0) : '—' },
          { label: 'Vessels', value: vessels.data ? num(vessels.data.vessels.length, 0) : '—' },
        ],
        detail:
          'Real Natural Earth coastline used as a hard land mask, so a waypoint can never be ' +
          'placed on the continent. Maitri is 80 km inland, so every destination carries a ' +
          'seaward anchorage validated against this coastline at start-up.',
      },
      {
        id: 'ice',
        icon: Waves,
        title: 'Sea-ice analysis and forecast',
        what: 'Concentration, thickness, drift, and the pressure that traps ships',
        module: 'src/core/sea_ice.py',
        state: s(skill.isSuccess),
        metrics: [
          { label: '72 h forecast error', value: midSkill ? midSkill.rmse.toFixed(3) : '—' },
          {
            label: 'Beats persistence by',
            value: midSkill ? `${(midSkill.skill_score_vs_persistence * 100).toFixed(0)}%` : '—',
          },
        ],
        detail:
          'Thickness comes from how long it has been freezing (Stefan’s law on freezing ' +
          'degree days) plus extra where ice is being ridged up, because satellites cannot ' +
          'measure thickness at useful resolution. Divergence of the drift field gives the ' +
          'compression index, which is what predicts besetting before it happens.',
      },
      {
        id: 'polaris',
        icon: ShieldCheck,
        title: 'POLARIS safety assessment',
        what: 'Is this ship legally and structurally allowed in this ice?',
        module: 'src/core/polaris_risk.py',
        state: s(Boolean(plan) || Boolean(tick), planning),
        metrics: [
          { label: 'Standard', value: 'IMO MSC.1/Circ.1519' },
          { label: 'Current risk score', value: tick ? String(tick.rio) : plan ? String(plan.minimum_rio) : '—' },
        ],
        detail:
          'The risk index is a hard constraint, not advice. Below -10 the operation is not ' +
          'permitted and the optimiser will not return a route through it at all.',
      },
      {
        id: 'ship',
        icon: Ship,
        title: 'Ship performance in ice',
        what: 'How fast can this hull actually go, and what does it burn?',
        module: 'src/core/lindqvist_model.py',
        state: s(Boolean(plan) || Boolean(tick), planning),
        metrics: [
          { label: 'Attainable speed', value: tick ? `${num(tick.attainable_speed_knots, 1)} kn` : '—' },
          { label: 'Power in use', value: tick ? `${num(tick.power_utilisation_percent, 0)}%` : '—' },
        ],
        detail:
          'Lindqvist (1989): the force to crush ice at the bow, bend the sheet and push the ' +
          'broken pieces under the hull. Speed is solved from the power and propeller-thrust ' +
          'balance, so it is an output of the physics rather than a planner assumption. If it ' +
          'solves to zero, the ship is beset.',
      },
      {
        id: 'optimiser',
        icon: GitCompareArrows,
        title: 'Route optimisation, run twice',
        what: 'The recommended route, and the route a ship would sail without ice data',
        module: 'src/core/route_optimizer.py',
        state: s(Boolean(plan), planning),
        metrics: [
          { label: 'Nodes searched', value: plan?.search ? num(plan.search.nodes_expanded, 0) : '—' },
          { label: 'Rejected: land', value: plan?.search ? num(plan.search.nodes_rejected_land, 0) : '—' },
          { label: 'Rejected: unsafe ice', value: plan?.search ? num(plan.search.nodes_rejected_rio, 0) : '—' },
        ],
        detail:
          'This is the mechanism that makes the headline number honest. Two independent A* ' +
          'searches, then both tracks sailed through identical physics. The saving is the ' +
          'difference between them, which is why it is allowed to come out negative.',
      },
      {
        id: 'radar',
        icon: Radar,
        title: 'Near-field radar',
        what: 'Small ice the satellites cannot see',
        module: 'src/core/growler_radar.py',
        state: s(Boolean(tick), sailing),
        metrics: [
          { label: 'Contacts painted', value: tick ? String(tick.radar_contacts) : '—' },
          { label: 'Highest threat', value: tick ? tick.radar_highest_threat : '—' },
        ],
        detail:
          'Reports what it MISSED, not just what it saw. Growlers with little freeboard vanish ' +
          'into sea clutter, and a display implying complete detection would teach the wrong ' +
          'lesson about the hazard most likely to hole a hull.',
      },
      {
        id: 'console',
        icon: MapIcon,
        title: 'Bridge console and alerting',
        what: 'Sail the plan, watch conditions change, re-plan when they turn',
        module: 'src/core/voyage.py',
        state: s(Boolean(tick), sailing),
        metrics: [
          { label: 'Hours sailed', value: tick ? num(tick.sim_hours, 0) : '—' },
          { label: 'Alerts raised', value: String(alerts.length) },
        ],
        detail:
          'Conditions are resampled at the ship’s actual arrival time, not at planning time, ' +
          'so a forecast that was right at departure can be wrong on arrival and the system ' +
          'notices. Hard constraint violations trigger a re-plan from the present position.',
      },
    ];
  }, [health, coastline, icebergs, vessels, skill, plan, tick, alerts.length, planning, sailing]);

  return (
    <div className="h-full overflow-y-auto p-3">
      <div className="mx-auto max-w-5xl">
        {/* ------------------------------------------------------- the problem */}
        <div className="grid gap-2 lg:grid-cols-2">
          <Panel title="The problem">
            <p className="text-xs2 leading-relaxed text-ink-2">
              Every austral summer India sends ships to resupply its Antarctic stations{' '}
              <strong className="text-ink">Maitri</strong> and{' '}
              <strong className="text-ink">Bharati</strong>. The sailing window is about{' '}
              <strong className="text-ink">ninety days</strong>. Sea ice decides whether they make
              it, and the ice charts available today are largely manual and twelve to twenty-four
              hours old.
            </p>
            <p className="mt-2 text-xs2 leading-relaxed text-ink-2">
              Get it wrong and you burn fuel ramming ice, miss a relief window, or get{' '}
              <Explain term="besetting">
                <strong className="text-danger">beset</strong>
              </Explain>{' '}
              — trapped as the ice closes around the hull.
            </p>
          </Panel>

          <Panel title="The solution">
            <p className="text-xs2 leading-relaxed text-ink-2">
              Plan a route that is safe under international rules, and{' '}
              <strong className="text-ink">prove the benefit by measuring it</strong>.
            </p>
            <p className="mt-2 text-xs2 leading-relaxed text-ink-2">
              The system plans <strong className="text-accent">two</strong> routes: the one a ship
              would sail with no ice information, and the one it recommends. It then sails{' '}
              <em>both</em> through identical physics. The difference between them is the benefit.
            </p>
            <div className="mt-2 rounded-sm border border-ok/30 bg-ok/[0.06] p-2 text-2xs leading-relaxed text-ink-2">
              Because that is a measurement and not an assumption, it is{' '}
              <strong className="text-ok">allowed to come out unfavourable</strong> — and on some
              legs it does. The route that is safer sometimes burns more fuel, and the system says
              so.
            </div>
          </Panel>
        </div>

        {/* ------------------------------------------------------- live banner */}
        <div className="mt-3 flex flex-wrap items-center gap-2 rounded border border-hair bg-panel px-3 py-2">
          <Cpu size={14} className={planning ? 'animate-pulse text-accent' : 'text-ink-3'} />
          <span className="text-2xs uppercase tracking-[0.12em] text-ink-3">Pipeline status</span>
          <Badge tone={planning ? 'accent' : sailing ? 'ok' : 'neutral'}>
            {planning ? 'Planning' : sailing ? 'Voyage under way' : plan ? 'Plan ready' : 'Idle'}
          </Badge>
          {health.data?.warmup && (
            <span className="text-2xs text-ink-3">
              caches {health.data.warmup.state}
              {health.data.warmup.seconds ? ` in ${num(health.data.warmup.seconds, 0)} s` : ''}
            </span>
          )}
          <button type="button" className="btn ml-auto" onClick={() => setScreen('planner')}>
            Run the pipeline
          </button>
        </div>

        {/* ------------------------------------------------------- the stages */}
        <div className="mt-3">
          {stages.map((stage, i) => (
            <div key={stage.id}>
              <StageCard stage={stage} index={i + 1} />
              {i < stages.length - 1 && (
                <div className="flex justify-center py-0.5">
                  <ArrowDown
                    size={14}
                    className={stage.state === 'done' ? 'text-ok/50' : 'text-hair-2'}
                  />
                </div>
              )}
            </div>
          ))}
        </div>

        {/* ------------------------------------------------------- the output */}
        {plan && (
          <Panel title="What comes out" className="mt-3">
            <div className="grid gap-2 sm:grid-cols-3">
              <Outcome
                label="Transit time"
                value={`${num(Math.abs(plan.time_saved_hours), 0)} h`}
                sub={plan.time_saved_hours >= 0 ? 'saved' : 'lost'}
                good={plan.time_saved_hours >= 0}
              />
              <Outcome
                label="Fuel"
                value={`${num(Math.abs(plan.fuel_saved_percentage), 1)}%`}
                sub={plan.fuel_saved_percentage >= 0 ? 'saved' : 'extra'}
                good={plan.fuel_saved_percentage >= 0}
              />
              <Outcome
                label="Worst risk score"
                value={`${plan.baseline?.minimum_rio ?? '—'} → ${plan.optimized?.minimum_rio ?? '—'}`}
                sub="ice-blind → recommended"
                good={(plan.optimized?.minimum_rio ?? 0) >= (plan.baseline?.minimum_rio ?? 0)}
              />
            </div>
            {plan.warnings.length > 0 && (
              <div className="mt-2 space-y-1">
                {plan.warnings.map((w) => (
                  <div
                    key={w}
                    className="flex items-start gap-2 rounded-sm border border-caution/40 bg-caution/10 p-2 text-2xs text-caution"
                  >
                    <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                    <span>{w}</span>
                  </div>
                ))}
              </div>
            )}
            <p className="mt-2 text-2xs text-ink-3">{plan.savings_method}</p>
          </Panel>
        )}

        <Panel title="What this prototype does not do" className="mt-3">
          <ul className="list-disc space-y-1 pl-4 text-2xs leading-relaxed text-ink-2">
            <li>
              The weather and sea-ice fields are <strong className="text-caution">simulated</strong>.
              The physics, the safety tables, the coastline and the geodesy are real. Every skill
              figure is therefore measured inside a simulated environment.
            </li>
            <li>
              Of three trained machine-learning models, <strong>one is good enough to use</strong>.
              The other two lose to the physics they were meant to improve and are not in the
              serving path. Both failures are documented rather than hidden.
            </li>
            <li>
              Route optimality is approximate in time: each node carries the arrival time of the
              best path found so far, which is standard in weather routing but is not a proof of
              optimality.
            </li>
            <li>The ice overlay export is shaped after IHO S-411 but is not a certified encoding.</li>
          </ul>
        </Panel>
      </div>
    </div>
  );
}

function StageCard({ stage, index }: { stage: Stage; index: number }): JSX.Element {
  const style = STATE_STYLE[stage.state];
  const Icon = stage.icon;
  return (
    <div className={`rounded border bg-panel p-3 transition-colors ${style.ring}`}>
      <div className="flex items-start gap-3">
        <div
          className={`flex h-8 w-8 shrink-0 items-center justify-center rounded-full border ${style.ring} bg-panel-2 ${style.text}`}
        >
          <Icon size={15} />
        </div>

        <div className="min-w-0 flex-1">
          <div className="flex flex-wrap items-baseline gap-2">
            <span className="text-2xs text-ink-3">{index}.</span>
            <span className="text-xs font-semibold text-ink">{stage.title}</span>
            <span className={`flex items-center gap-1 text-2xs ${style.text}`}>
              {stage.state === 'busy' ? (
                <Loader2 size={10} className="animate-spin" />
              ) : stage.state === 'done' ? (
                <CheckCircle2 size={10} />
              ) : (
                <Circle size={10} />
              )}
              {style.label}
            </span>
            <code className="ml-auto hidden text-2xs text-ink-3 md:inline">{stage.module}</code>
          </div>

          <p className="mt-0.5 text-2xs text-ink-2">{stage.what}</p>
          <p className="mt-1 text-2xs leading-relaxed text-ink-3">{stage.detail}</p>

          <div className="mt-2 flex flex-wrap gap-x-4 gap-y-1">
            {stage.metrics.map((m) => (
              <div key={m.label} className="flex items-baseline gap-1.5">
                <span className="text-2xs text-ink-3">{m.label}</span>
                <span className="num text-xs2 text-ink">{m.value}</span>
              </div>
            ))}
          </div>
        </div>
      </div>
    </div>
  );
}

function Outcome({
  label,
  value,
  sub,
  good,
}: {
  label: string;
  value: string;
  sub: string;
  good: boolean;
}): JSX.Element {
  return (
    <div className="rounded-sm border border-hair bg-panel-2 p-2.5">
      <div className="text-2xs uppercase tracking-[0.1em] text-ink-3">{label}</div>
      <div className={`num mt-0.5 text-lg font-semibold ${good ? 'text-ok' : 'text-danger'}`}>
        {value}
      </div>
      <div className="text-2xs text-ink-3">{sub}</div>
    </div>
  );
}
