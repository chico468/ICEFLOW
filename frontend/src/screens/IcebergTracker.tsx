/**
 * Iceberg Tracker: the catalogue, per-berg ensemble drift, deterioration, and closest approach
 * against the planned route.
 *
 * The uncertainty envelope is the honest part of a drift forecast. A single predicted position
 * at 120 hours implies a precision nobody has; the 50 and 90 percent radii come from perturbing
 * the drag coefficients and forcing across an ensemble, and they are drawn on the chart.
 */
import { useEffect, useState } from 'react';
import { AlertTriangle } from 'lucide-react';
import {
  Area,
  AreaChart,
  CartesianGrid,
  ResponsiveContainer,
  Tooltip,
  XAxis,
  YAxis,
} from 'recharts';
import { getIcebergRisk } from '../api/client';
import { useIcebergDrift, useIcebergs, useObservedIcebergs } from '../api/queries';
import { MapCanvas } from '../map/MapCanvas';
import { MapStage } from '../components/MapStage';
import { Badge, EmptyState, ErrorNote, KeyValue, Panel, Slider, Spinner } from '../components/ui';
import { useScene } from '../hooks/useScene';
import { num } from '../lib/format';
import { formatObservedDate } from '../components/MapLegend';
import { threatColor } from '../map/palette';
import { useAppStore } from '../store/useAppStore';
import type { ClosestApproach } from '../api/types';

export function IcebergTracker(): JSX.Element {
  const { scene, fitTargets } = useScene({ showBergDrift: true });
  const leadHours = useAppStore((s) => s.leadHours);
  const selectedBergId = useAppStore((s) => s.selectedBergId);
  const setSelectedBergId = useAppStore((s) => s.setSelectedBergId);
  const setBergDrift = useAppStore((s) => s.setBergDrift);
  const bergForecastHours = useAppStore((s) => s.bergForecastHours);
  const setBergForecastHours = useAppStore((s) => s.setBergForecastHours);
  const planner = useAppStore((s) => s.planner);
  const plan = useAppStore((s) => s.plan);

  const catalogue = useIcebergs(leadHours);
  const observed = useObservedIcebergs();
  const drift = useIcebergDrift(selectedBergId, bergForecastHours, 12);

  const [approaches, setApproaches] = useState<ClosestApproach[] | null>(null);
  const [riskLoading, setRiskLoading] = useState(false);
  const [riskError, setRiskError] = useState<string | null>(null);

  useEffect(() => {
    setBergDrift(drift.data ?? null);
  }, [drift.data, setBergDrift]);

  async function checkRoute(): Promise<void> {
    setRiskLoading(true);
    setRiskError(null);
    try {
      const res = await getIcebergRisk({
        origin_id: planner.originId,
        destination_id: planner.destinationId,
        vessel_key: planner.vesselKey,
        ice_class: planner.iceClass,
        weights: planner.weights,
        avoid_icebergs: planner.avoidIcebergs,
      });
      setApproaches(res.approaches);
    } catch (err) {
      setRiskError(err instanceof Error ? err.message : String(err));
    } finally {
      setRiskLoading(false);
    }
  }

  const deterioration = (drift.data?.trajectory ?? []).map((p) => ({
    hour: p.hour,
    length: p.length_m,
    r90: p.uncertainty_radius_90_km,
    r50: p.uncertainty_radius_50_km,
  }));

  return (
    <MapStage
      id="bergs"
      map={<MapCanvas scene={scene} fitTargets={fitTargets} />}
      shelf={
        <>
        <Panel
          title="Tracked catalogue"
          subtitle="US National Ice Center naming; positions propagated by the drift model"
          right={<Badge tone="neutral">{catalogue.data?.count ?? 0}</Badge>}
        >
          {!catalogue.data ? (
            <Spinner label="Loading catalogue" />
          ) : (
            <div className="overflow-x-auto">
              <table className="w-full text-2xs">
                <thead className="text-ink-3">
                  <tr>
                    <th className="text-left font-normal">Berg</th>
                    <th className="text-left font-normal">Origin</th>
                    <th className="text-right font-normal">Length</th>
                    <th className="text-right font-normal">Position</th>
                  </tr>
                </thead>
                <tbody>
                  {catalogue.data.icebergs.map((b) => {
                    const active = b.berg_id === selectedBergId;
                    return (
                      <tr
                        key={b.berg_id}
                        onClick={() => setSelectedBergId(active ? null : b.berg_id)}
                        className={`cursor-pointer border-t border-hair/60 ${
                          active ? 'bg-accent/10 text-accent' : 'text-ink-2 hover:bg-panel-2'
                        }`}
                      >
                        <td className="py-1 font-sans">{b.berg_id}</td>
                        <td className="py-1 font-sans text-ink-3">{b.origin}</td>
                        <td className="num py-1 text-right">{num(b.length_m / 1000, 1)} km</td>
                        <td className="num py-1 text-right text-ink-3">
                          {num(b.forecast_latitude ?? b.latitude, 1)}, {num(b.forecast_longitude ?? b.longitude, 1)}
                        </td>
                      </tr>
                    );
                  })}
                </tbody>
              </table>
              <p className="mt-1 text-2xs text-ink-3">
                Click a berg to run a 12-member ensemble drift forecast and draw it on the chart.
              </p>
            </div>
          )}
        </Panel>

        <Panel
          title="Observed snapshot"
          subtitle="USNIC-format file, not a live feed"
          right={
            observed.data?.available ? (
              <Badge tone={observed.data.stale ? 'caution' : 'ok'}>
                {observed.data.stale ? 'STALE' : 'Current'} · {observed.data.age_days} d
              </Badge>
            ) : undefined
          }
        >
          {observed.isLoading ? (
            <Spinner label="Loading observed snapshot" />
          ) : observed.error ? (
            <ErrorNote
              message={observed.error instanceof Error ? observed.error.message : String(observed.error)}
              onRetry={() => void observed.refetch()}
            />
          ) : !observed.data?.available ? (
            <EmptyState
              title="No observed snapshot"
              detail={`${observed.data?.reason ?? 'Not available.'} ${observed.data?.setup ?? ''}`}
            />
          ) : (
            <div>
              <p className={`mb-2 text-2xs ${observed.data.stale ? 'text-caution' : 'text-ink-2'}`}>
                {observed.data.stale_note}
              </p>
              <div className="max-h-44 overflow-auto">
                <table className="w-full text-2xs">
                  <thead className="text-ink-3">
                    <tr>
                      <th className="text-left font-normal">Berg</th>
                      <th className="text-right font-normal">L × W (nm)</th>
                      <th className="text-right font-normal">Position at {formatObservedDate(observed.data.observed_date)}</th>
                    </tr>
                  </thead>
                  <tbody>
                    {observed.data.icebergs.map((b) => (
                      <tr key={b.id} className="border-t border-hair/60 text-ink-2">
                        <td className="py-1 font-sans">{b.id}</td>
                        <td className="num py-1 text-right">
                          {num(b.length_nm, 0)} × {num(b.width_nm, 0)}
                        </td>
                        <td className="num py-1 text-right text-ink-3">
                          {num(b.latitude, 2)}, {num(b.longitude, 2)}
                        </td>
                      </tr>
                    ))}
                  </tbody>
                </table>
              </div>
              <ul className="mt-2 list-disc space-y-0.5 pl-4 text-2xs text-ink-3">
                {(observed.data.limitations ?? []).map((l) => (
                  <li key={l}>{l}</li>
                ))}
                <li>{observed.data.source}</li>
              </ul>
            </div>
          )}
        </Panel>

        {selectedBergId && (
          <Panel
            title={`${selectedBergId} drift forecast`}
            right={drift.isFetching ? <Badge tone="accent">computing</Badge> : undefined}
          >
            <Slider
              label="Forecast horizon"
              value={bergForecastHours}
              min={24}
              max={240}
              step={24}
              display={`${num(bergForecastHours, 0)} h`}
              onChange={setBergForecastHours}
            />
            {drift.data ? (
              <>
                <div className="mt-2">
                  <KeyValue label="Net displacement" value={num(drift.data.net_displacement_km, 1)} unit="km" />
                  <KeyValue label="Mean speed" value={num(drift.data.mean_speed_knots, 3)} unit="kn" />
                  <KeyValue label="Mass lost" value={num(drift.data.mass_lost_percent, 2)} unit="%" />
                  <KeyValue label="Size class" value={`${drift.data.initial_size_class} → ${drift.data.final_size_class}`} />
                  <KeyValue label="Integration" value={drift.data.integration_scheme} />
                </div>

                {drift.data.force_budget && (
                  <div className="mt-2 border-t border-hair pt-2">
                    <div className="mb-1 text-2xs text-ink-3">
                      Force budget (MN)
                    </div>
                    <KeyValue label="Water drag" value={num(drift.data.force_budget.water_drag_mn, 3)} />
                    <KeyValue label="Air drag" value={num(drift.data.force_budget.air_drag_mn, 3)} />
                    <KeyValue label="Coriolis" value={num(drift.data.force_budget.coriolis_mn, 3)} />
                    <KeyValue label="Pressure gradient" value={num(drift.data.force_budget.pressure_gradient_mn, 3)} />
                    <KeyValue label="Wave radiation" value={num(drift.data.force_budget.wave_radiation_mn, 3)} />
                    <KeyValue
                      label="Drag response time"
                      value={num(drift.data.force_budget.response_timescale_hours, 1)}
                      unit="h"
                    />
                  </div>
                )}

                <div className="mt-3 h-36">
                  <ResponsiveContainer width="100%" height="100%">
                    <AreaChart data={deterioration} margin={{ top: 4, right: 6, bottom: 0, left: -20 }}>
                      <CartesianGrid stroke="rgb(var(--c-hair))" strokeDasharray="2 3" />
                      <XAxis dataKey="hour" stroke="rgb(var(--c-ink-3))" tick={{ fontSize: 10 }} unit="h" />
                      <YAxis stroke="rgb(var(--c-ink-3))" tick={{ fontSize: 10 }} />
                      <Tooltip
                        contentStyle={{ background: 'rgb(var(--c-panel))', border: '1px solid rgb(var(--c-hair-2))', fontSize: 11 }}
                      />
                      <Area
                        type="monotone"
                        dataKey="r90"
                        name="90% radius (km)"
                        stroke="rgb(var(--c-violet))"
                        fill="rgb(var(--c-violet))"
                        fillOpacity={0.18}
                      />
                      <Area
                        type="monotone"
                        dataKey="r50"
                        name="50% radius (km)"
                        stroke="rgb(var(--c-accent))"
                        fill="rgb(var(--c-accent))"
                        fillOpacity={0.25}
                      />
                    </AreaChart>
                  </ResponsiveContainer>
                </div>
                <p className="text-2xs text-ink-3">
                  Positional uncertainty from a 12-member ensemble with perturbed drag coefficients
                  and forcing.
                </p>
              </>
            ) : (
              <Spinner label="Integrating drift" />
            )}
          </Panel>
        )}

        <Panel
          title="Closest approach to the planned route"
          right={
            <button type="button" className="btn" disabled={riskLoading} onClick={() => void checkRoute()}>
              {riskLoading ? 'Checking…' : 'Check'}
            </button>
          }
        >
          {riskError && <ErrorNote message={riskError} />}
          {!approaches ? (
            <EmptyState
              title="Not checked"
              detail={
                plan
                  ? 'Run the check to test every catalogued berg against the planned track in time.'
                  : 'Plan a voyage first, then check the catalogue against it.'
              }
            />
          ) : (
            <ul className="space-y-1">
              {approaches.slice(0, 6).map((a) => (
                <li
                  key={a.berg_id}
                  className="flex items-center gap-2 border-b border-hair/50 py-1 last:border-0"
                >
                  <span className="font-sans text-xs2 text-ink-2">{a.berg_id}</span>
                  <span className="num ml-auto text-xs2" style={{ color: threatColor(a.threat_level) }}>
                    {num(a.distance_nm, 1)} nm
                  </span>
                  <span className="num text-2xs text-ink-3">+{num(a.time_hours, 0)} h</span>
                  <span
                    className="text-2xs"
                    style={{ color: threatColor(a.threat_level) }}
                  >
                    {a.threat_level}
                  </span>
                </li>
              ))}
              {approaches[0] && approaches[0].threat_level !== 'LOW' && (
                <li className="mt-1 flex items-start gap-2 rounded-sm border border-caution/40 bg-caution/10 p-2 text-2xs text-caution">
                  <AlertTriangle size={12} className="mt-0.5 shrink-0" />
                  <span>{approaches[0].advisory}</span>
                </li>
              )}
            </ul>
          )}
          <p className="mt-1 text-2xs text-ink-3">
            Both objects are moving, so the berg position is interpolated to the ship's arrival
            time rather than compared statically.
          </p>
        </Panel>
        </>
      }
    />
  );
}
