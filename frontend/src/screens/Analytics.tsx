/**
 * Analytics: the evidence behind the headline numbers.
 *
 * Every panel here exists to let someone check a claim rather than accept it — the fuel and time
 * comparison, the RIO profile along the track, the Lindqvist resistance breakdown, and the
 * satellite bandwidth budget, which is measured by building and gzipping both payloads rather
 * than asserted.
 */
import {
  Bar,
  BarChart,
  CartesianGrid,
  Legend,
  Line,
  LineChart,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { useBandwidth, useSpeedPowerCurve } from '../api/queries';
import { Badge, EmptyState, KeyValue, Panel, Stat } from '../components/ui';
import { bytes, num, signed } from '../lib/format';
import { useAppStore } from '../store/useAppStore';

const AXIS = { stroke: '#587383', tick: { fontSize: 10 } } as const;
const TOOLTIP = {
  contentStyle: { background: '#FFFFFF', border: '1px solid #AEBEC6', fontSize: 11 },
  labelStyle: { color: '#3D5666' },
} as const;

export function Analytics(): JSX.Element {
  const plan = useAppStore((s) => s.plan);
  const planner = useAppStore((s) => s.planner);
  const bandwidth = useBandwidth(0.5, 4);
  const curve = useSpeedPowerCurve(planner.vesselKey, 0.8);

  const comparison = plan
    ? [
        {
          metric: 'Distance (nm)',
          baseline: plan.baseline?.total_distance_nm ?? 0,
          optimised: plan.optimized?.total_distance_nm ?? 0,
        },
        {
          metric: 'Time (h)',
          baseline: plan.baseline?.total_transit_hours ?? 0,
          optimised: plan.optimized?.total_transit_hours ?? 0,
        },
        {
          metric: 'Fuel (t)',
          baseline: plan.baseline?.total_fuel_burn_tonnes ?? 0,
          optimised: plan.optimized?.total_fuel_burn_tonnes ?? 0,
        },
        {
          metric: 'CO2 (t)',
          baseline: plan.baseline?.total_co2_tonnes ?? 0,
          optimised: plan.optimized?.total_co2_tonnes ?? 0,
        },
      ]
    : [];

  const rioProfile = (plan?.optimized?.waypoints ?? []).map((w) => ({
    nm: Math.round(w.distance_from_start_nm),
    rio: w.rio_score,
    concentration: w.ice_concentration * 10,
    speed: w.speed_knots,
    thickness: w.ice_thickness_m,
  }));

  const speedSeries = curve.data
    ? curve.data.speeds_knots.map((v, i) => {
        const row: Record<string, number> = { speed: v };
        curve.data!.series.forEach((s) => {
          row[`h${s.ice_thickness_m}`] = s.required_power_kw[i] / 1000;
        });
        return row;
      })
    : [];

  return (
    <div className="h-full overflow-y-auto p-4">
      <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="Optimised against ice-blind baseline"
          subtitle={plan ? plan.savings_method : 'Plan a voyage to populate this'}
        >
          {!plan ? (
            <EmptyState title="No plan" detail="Use the Voyage Planner first." />
          ) : (
            <>
              <div className="mb-3 grid grid-cols-3 gap-2">
                <Stat
                  label="Fuel saved"
                  value={signed(plan.fuel_saved_percentage, 2)}
                  unit="%"
                  tone={plan.fuel_saved_percentage >= 0 ? 'ok' : 'danger'}
                />
                <Stat
                  label="Time saved"
                  value={num(plan.time_saved_hours, 0)}
                  unit="h"
                  tone={plan.time_saved_hours >= 0 ? 'ok' : 'danger'}
                />
                <Stat
                  label="Cost avoided"
                  value={signed(plan.cost_saved_inr / 1e5, 2)}
                  unit="lakh INR"
                  tone={plan.cost_saved_inr >= 0 ? 'ok' : 'danger'}
                />
              </div>
              <div className="h-52">
                <ResponsiveContainer width="100%" height="100%">
                  <BarChart data={comparison} margin={{ top: 4, right: 6, bottom: 0, left: -14 }}>
                    <CartesianGrid stroke="#D3DDE2" strokeDasharray="2 3" />
                    <XAxis dataKey="metric" {...AXIS} />
                    <YAxis {...AXIS} />
                    <Tooltip {...TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    <Bar dataKey="baseline" name="Ice-blind" fill="#B45309" />
                    <Bar dataKey="optimised" name="Optimised" fill="#0B5C8E" />
                  </BarChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-2xs text-ink-3">
                A negative fuel saving is a real outcome, not an error: on some legs the safe route
                is longer and the added distance costs more than the ice it avoids.
              </p>
            </>
          )}
        </Panel>

        <Panel title="Along the optimised route" subtitle="POLARIS index, ice and speed">
          {rioProfile.length === 0 ? (
            <EmptyState title="No route" detail="Plan a voyage first." />
          ) : (
            <div className="h-64">
              <ResponsiveContainer width="100%" height="100%">
                <LineChart data={rioProfile} margin={{ top: 4, right: 6, bottom: 0, left: -18 }}>
                  <CartesianGrid stroke="#D3DDE2" strokeDasharray="2 3" />
                  <XAxis dataKey="nm" {...AXIS} unit=" nm" />
                  <YAxis {...AXIS} />
                  <Tooltip {...TOOLTIP} />
                  <Legend wrapperStyle={{ fontSize: 10 }} />
                  <Line type="monotone" dataKey="rio" name="RIO" stroke="#1F7A4D" dot={false} strokeWidth={2} />
                  <Line type="monotone" dataKey="concentration" name="Ice (tenths)" stroke="#3D5666" dot={false} />
                  <Line type="monotone" dataKey="speed" name="Speed (kn)" stroke="#0B5C8E" dot={false} />
                  <Line type="monotone" dataKey="thickness" name="Thickness (m)" stroke="#5B3FD1" dot={false} />
                </LineChart>
              </ResponsiveContainer>
            </div>
          )}
        </Panel>

        <Panel
          title="Lindqvist speed–power"
          subtitle={curve.data ? `${curve.data.vessel} at 8/10 concentration` : 'Loading'}
        >
          {speedSeries.length === 0 ? (
            <EmptyState title="No curve" detail="Backend unreachable." />
          ) : (
            <>
              <div className="h-56">
                <ResponsiveContainer width="100%" height="100%">
                  <LineChart data={speedSeries} margin={{ top: 4, right: 6, bottom: 0, left: -14 }}>
                    <CartesianGrid stroke="#D3DDE2" strokeDasharray="2 3" />
                    <XAxis dataKey="speed" {...AXIS} unit=" kn" />
                    <YAxis {...AXIS} unit=" MW" />
                    <Tooltip {...TOOLTIP} />
                    <Legend wrapperStyle={{ fontSize: 10 }} />
                    {(curve.data?.series ?? []).map((s, i) => (
                      <Line
                        key={s.ice_thickness_m}
                        type="monotone"
                        dataKey={`h${s.ice_thickness_m}`}
                        name={`${s.ice_thickness_m} m ice`}
                        stroke={['#0B5C8E', '#0F766E', '#A16207', '#B45309', '#B3261E'][i % 5]}
                        dot={false}
                      />
                    ))}
                  </LineChart>
                </ResponsiveContainer>
              </div>
              <p className="mt-1 text-2xs text-ink-3">
                Power required against speed. Where a curve crosses the installed power, that is
                the ship's attainable speed — which is how the optimiser derives it rather than
                assuming it.
              </p>
            </>
          )}
        </Panel>

        <Panel
          title="Satellite bandwidth budget"
          subtitle="Measured, not asserted"
          right={
            bandwidth.data ? (
              <Badge tone={bandwidth.data.within_budget ? 'ok' : 'danger'}>
                {bandwidth.data.within_budget ? 'within budget' : 'over budget'}
              </Badge>
            ) : undefined
          }
        >
          {!bandwidth.data ? (
            <EmptyState title="No data" detail="Backend unreachable." />
          ) : (
            <>
              <div className="mb-2 grid grid-cols-2 gap-2">
                <Stat
                  label="Daily total"
                  value={num(bandwidth.data.daily_total_kb, 1)}
                  unit="KB"
                  size="lg"
                  tone="accent"
                />
                <Stat label="Budget" value={num(bandwidth.data.budget_kb, 0)} unit="KB/day" tone="muted" />
              </div>
              <KeyValue label="Full raster" value={bytes(bandwidth.data.full_raster_bytes)} />
              <KeyValue label="Raster, gzipped" value={bytes(bandwidth.data.full_raster_gzip_bytes)} />
              <KeyValue label="Contour payload, gzipped" value={bytes(bandwidth.data.contour_payload_gzip_bytes)} />
              <KeyValue label="Delta payload, gzipped" value={bytes(bandwidth.data.delta_payload_gzip_bytes)} />
              <KeyValue label="Updates per day" value={num(bandwidth.data.updates_per_day, 0)} />
              <KeyValue label="Grid cells" value={num(bandwidth.data.domain.grid_cells, 0)} />
              <KeyValue
                label="Compression vs raster"
                value={`${num(bandwidth.data.compression_ratio_vs_raster, 1)}×`}
              />
              <p className="mt-1 text-2xs text-ink-3">{bandwidth.data.method}</p>
            </>
          )}
        </Panel>
      </div>
    </div>
  );
}
