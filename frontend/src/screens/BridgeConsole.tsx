/**
 * Bridge Console: the chart, the ship's live state, the alert feed and the radar scope.
 *
 * This is the screen a watchkeeping officer would actually have in front of them, so it is
 * arranged the way an instrument panel is: the chart takes the space, the numbers that change
 * sit in a fixed rail where the eye learns to find them, and anything demanding action appears
 * as an alert rather than as a number the officer is expected to notice.
 */
import { useEffect, useMemo } from 'react';
import { AlertTriangle, Pause, Play, RotateCcw, SkipForward, Square } from 'lucide-react';
import { ChartViews } from '../components/ChartViews';
import { MapStage } from '../components/MapStage';
import { RadarScope } from '../components/RadarScope';
import {
  Badge,
  ComputeOverlay,
  EmptyState,
  ErrorNote,
  KeyValue,
  Meter,
  Panel,
  RioGauge,
  Stat,
} from '../components/ui';
import { useRadarSweep } from '../api/queries';
import { useVoyageSocket } from '../hooks/useVoyageSocket';
import { Explain } from '../components/Explain';
import { useScene } from '../hooks/useScene';
import { bearing, hoursToDhm, num, tenths } from '../lib/format';
import { besettingColor, rioStatusLabel, severityColor } from '../map/palette';
import { latestTick, useAppStore } from '../store/useAppStore';

export function BridgeConsole(): JSX.Element {
  const { scene, fitTargets } = useScene();
  const voyage = useAppStore((s) => s.voyage);
  const phase = useAppStore((s) => s.voyagePhase);
  const error = useAppStore((s) => s.voyageError);
  const ticks = useAppStore((s) => s.ticks);
  const alerts = useAppStore((s) => s.alerts);
  const planner = useAppStore((s) => s.planner);
  const routeAlternatives = useAppStore((s) => s.routeAlternatives);
  const selectedCandidateId = useAppStore((s) => s.selectedCandidateId);
  const setSelectedCandidateId = useAppStore((s) => s.setSelectedCandidateId);
  const planStale = useAppStore((s) => s.planStale);
  const setInspect = useAppStore((s) => s.setInspect);
  const setRadar = useAppStore((s) => s.setRadar);
  const setScreen = useAppStore((s) => s.setScreen);
  const simpleMode = useAppStore((s) => s.simpleMode);

  const controller = useVoyageSocket();
  const tick = latestTick(ticks);

  // Keep the radar sweep in step with the ship. It is a separate request because a sweep is
  // cheap and the officer may want to refresh it while the voyage is paused.
  const sweep = useRadarSweep(
    tick?.latitude ?? null,
    tick?.longitude ?? null,
    tick?.heading_deg ?? 0,
    tick?.speed_knots ?? 0,
    tick?.sim_hours ?? 0,
  );
  useEffect(() => {
    if (sweep.data) setRadar(sweep.data);
  }, [sweep.data, setRadar]);

  const running = phase === 'running';
  const busy = phase === 'creating' || phase === 'connecting';
  const started = Boolean(voyage);
  const selectedCandidate = routeAlternatives.find((candidate) => candidate.id === selectedCandidateId);
  const routeSelectionBlocked = planStale || (routeAlternatives.length > 0 && !selectedCandidate?.is_feasible);

  const openAlerts = useMemo(
    () => [...alerts].reverse().slice(0, 24),
    [alerts],
  );

  return (
    <MapStage
      id="sail"
      map={
        <>
        <ChartViews
          scene={scene}
          fitTargets={fitTargets}
          onClickPoint={(ll) => setInspect(ll)}
          onSelectRouteCandidate={setSelectedCandidateId}
          voyagePhase={phase}
          onPlay={controller.play}
          onPause={controller.pause}
          onStep={controller.step}
        />

        {busy && (
          <ComputeOverlay
            title="Planning and creating voyage"
            elapsedMs={controller.elapsedMs}
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

        {!started && !busy && (
          <div className="pointer-events-none absolute inset-x-0 bottom-9 p-3">
            <div className="pointer-events-auto mx-auto max-w-md rounded border border-hair-2 bg-panel/95 p-3 text-center">
              <div className="text-xs text-ink-2">
                No voyage under way. Start one to see the ship sail the planned track.
              </div>
              <button
                type="button"
                className="btn btn-accent mt-2"
                disabled={routeSelectionBlocked}
                onClick={() =>
                  void controller.begin({
                    origin_id: planner.originId,
                    destination_id: planner.destinationId,
                    vessel_key: planner.vesselKey,
                    ice_class: planner.iceClass,
                    weights: selectedCandidate?.weights ?? planner.weights,
                    route_profile_id: selectedCandidate?.id ?? 'balanced',
                    departure_time_hours: planner.departureTimeHours,
                    grid_resolution_deg: planner.gridResolutionDeg,
                    avoid_icebergs: planner.avoidIcebergs,
                  })
                }
              >
                Start {selectedCandidate?.name ?? 'Balanced'} voyage: {planner.originId.replace(/_/g, ' ')} to{' '}
                {planner.destinationId.replace(/_/g, ' ')}
              </button>
              {planStale && (
                <div role="alert" className="mt-2 text-2xs text-danger">
                  Passage conditions changed after comparison. Return to Plan and recalculate candidates before sailing.
                </div>
              )}
              {!planStale && routeAlternatives.length > 0 && !selectedCandidate?.is_feasible && (
                <div role="alert" className="mt-2 text-2xs text-danger">
                  Select a feasible route in Plan before starting this voyage.
                </div>
              )}
              <div className="mt-1 text-2xs text-ink-3">
                Planning runs the full optimisation on the server and takes 15 to 30 seconds.
              </div>
            </div>
          </div>
        )}
        </>
      }
      shelf={
        <>
        <Panel
          title="Vessel"
          subtitle={voyage ? `${voyage.vessel_name} — ${voyage.ice_class}` : 'No voyage'}
          right={
            <Badge tone={running ? 'ok' : started ? 'caution' : 'neutral'}>
              {/*
                Show the LIVE phase, not the status stamped on the voyage when it was created.
                That field says PLANNED and is never revised by a tick, so the badge read
                "PLANNED" while the ship was visibly two thousand miles down the track.
              */}
              {tick?.is_beset
                ? 'BESET'
                : running
                  ? 'UNDER WAY'
                  : phase === 'paused'
                    ? 'PAUSED'
                    : phase === 'done'
                      ? 'ARRIVED'
                      : started
                        ? (voyage?.status ?? 'PLANNED')
                        : 'IDLE'}
            </Badge>
          }
        >
          {tick ? (
            <>
              <div className="grid grid-cols-2 gap-2">
                <Stat label="Speed" value={num(tick.speed_knots, 1)} unit="kn" size="lg" tone="accent" />
                <Stat label="Heading" value={bearing(tick.heading_deg)} size="lg" />
                <Stat label="Made good" value={num(tick.distance_travelled_nm, 0)} unit="nm" />
                <Stat label="Remaining" value={num(tick.distance_remaining_nm, 0)} unit="nm" />
              </div>

              <div className="mt-3">
                <div className="mb-1 flex items-center justify-between">
                  <Explain term="rio">
                    <span className="text-2xs text-ink-3">
                      Ice risk score
                    </span>
                  </Explain>
                  <span className="text-2xs text-ink-3">higher is safer</span>
                </div>
                <RioGauge rio={tick.rio} cap={tick.polaris_speed_cap_knots} />
                <div className="mt-1 text-2xs text-ink-3">
                  {rioStatusLabel(tick.rio)} — speed limit {num(tick.polaris_speed_cap_knots, 1)} kn,{' '}
                  <Explain term="attainable_speed">
                    <span>this ship can make {num(tick.attainable_speed_knots, 1)} kn</span>
                  </Explain>
                </div>
              </div>

              <div className="mt-3 space-y-1.5">
                <Meter
                  label="Power"
                  value01={tick.power_utilisation_percent / 100}
                  display={`${num(tick.required_power_kw, 0)} kW · ${num(tick.power_utilisation_percent, 0)}%`}
                  warnAbove={0.9}
                />
                <Meter
                  label="Ice concentration"
                  value01={tick.ice_concentration}
                  display={`${tenths(tick.ice_concentration)} · ${num(tick.ice_thickness_m, 2)} m`}
                  color="#3D5666"
                />
                <Meter
                  label="Ice pressure"
                  value01={tick.compression_index}
                  display={tick.besetting_risk}
                  color={besettingColor(tick.besetting_risk)}
                  warnAbove={0.6}
                />
                <div className="flex flex-wrap gap-x-3 gap-y-1 pt-0.5 text-2xs text-ink-3">
                  <Explain term="compression">
                    <span>What is ice pressure?</span>
                  </Explain>
                  <Explain term="besetting">
                    <span>What does beset mean?</span>
                  </Explain>
                </div>
              </div>

              <div className="mt-3">
                <KeyValue label="Fuel burned" value={num(tick.fuel_used_tonnes, 1)} unit="t MGO" />
                <KeyValue label="Burn rate" value={num(tick.fuel_rate_kg_per_hour, 0)} unit="kg/h" />
                <KeyValue label="CO2" value={num(tick.co2_tonnes, 1)} unit="t" />
                <KeyValue label="Elapsed" value={hoursToDhm(tick.sim_hours)} />
                <KeyValue label="ETA" value={hoursToDhm(tick.eta_hours)} />
                <KeyValue label="Progress" value={num(tick.progress_percent, 1)} unit="%" />
              </div>

              <div className={simpleMode ? 'hidden' : 'mt-3 border-t border-hair pt-2'}>
                <KeyValue label="Wind" value={`${num(tick.wind_speed_ms, 1)} m/s from ${bearing(tick.wind_dir_from_deg)}`} />
                <KeyValue label="Sea state" value={num(tick.wave_height_m, 1)} unit="m Hs" />
                <KeyValue label="Air / sea" value={`${num(tick.air_temp_c, 1)} / ${num(tick.sst_c, 1)}`} unit="°C" />
                <KeyValue label="Visibility" value={num(tick.visibility_km, 1)} unit="km" />
                <KeyValue label="Ice stage" value={tick.ice_type.replace(/_/g, ' ')} />
              </div>
            </>
          ) : (
            <EmptyState
              title="No live data"
              detail="Start a voyage to stream the ship's state hour by hour."
            />
          )}
        </Panel>

        <Panel
          title="Voyage control"
          right={
            <span className="num text-2xs text-ink-3">
              {controller.connected ? 'socket open' : 'socket closed'}
            </span>
          }
        >
          {error && <ErrorNote message={error} />}
          <div className="flex flex-wrap gap-1.5">
            <button
              type="button"
              className="btn"
              disabled={!started || busy}
              onClick={() => (running ? controller.pause() : controller.play())}
            >
              {running ? <Pause size={13} /> : <Play size={13} />}
              {running ? 'Pause' : 'Play'}
            </button>
            <button type="button" className="btn" disabled={!started || running || busy} onClick={() => controller.step()}>
              <SkipForward size={13} />
              Step
            </button>
            <button type="button" className="btn" disabled={!started || busy} onClick={() => controller.reroute()}>
              <RotateCcw size={13} />
              Re-route
            </button>
            <button type="button" className="btn" disabled={!started} onClick={() => controller.disconnect()}>
              <Square size={13} />
              Stop
            </button>
            <button type="button" className="btn" onClick={() => setScreen('planner')}>
              Plan a different passage
            </button>
          </div>
          <div className="mt-2 text-2xs text-ink-3">
            Re-planning from the ship's present position keeps the track already sailed and records
            the diversion.
          </div>
        </Panel>

        <Panel
          title="Alerts"
          right={<Badge tone={alerts.length ? 'caution' : 'neutral'}>{alerts.length}</Badge>}
          bodyClassName="max-h-72 overflow-y-auto"
        >
          {openAlerts.length === 0 ? (
            <EmptyState title="No alerts" detail="Conditions are within limits." />
          ) : (
            <ul className="space-y-1.5">
              {openAlerts.map((a) => (
                <li key={a.alert_id} className="rounded-sm border border-hair bg-panel-2 p-2">
                  <div className="flex items-center gap-1.5">
                    <AlertTriangle size={12} style={{ color: severityColor(a.severity) }} />
                    <span
                      className="text-2xs"
                      style={{ color: severityColor(a.severity) }}
                    >
                      {a.code.replace(/_/g, ' ')}
                    </span>
                    <span className="num ml-auto text-2xs text-ink-3">+{num(a.sim_hours, 0)} h</span>
                  </div>
                  <div className="mt-1 text-xs2 text-ink-2">{a.message}</div>
                  <div className="mt-0.5 text-2xs text-ink-3">{a.advisory}</div>
                </li>
              ))}
            </ul>
          )}
        </Panel>

        <Panel
          title="X-band radar"
          subtitle="Near-field growler detection"
          right={
            sweep.data ? (
              <Badge tone={sweep.data.contacts.length ? 'caution' : 'neutral'}>
                {sweep.data.contacts.length} contacts
              </Badge>
            ) : undefined
          }
        >
          <RadarScope sweep={sweep.data ?? null} />
        </Panel>
        </>
      }
    />
  );
}
