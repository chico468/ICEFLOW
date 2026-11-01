/**
 * Sail: the voyage bridge.
 */
import { useCallback, useEffect, useRef, useState } from 'react';
import { Play, Pause, SkipForward, Square } from 'lucide-react';
import { MapStage } from '../components/MapStage.tsx';
import { ChartViews } from '../components/ChartViews.tsx';
import { useScene } from '../hooks/useScene.ts';
import { useAppStore } from '../store/useAppStore.ts';
import { RecordedTimelineSource } from '../lib/timeline.ts';
import { SimulatedPositionSource } from '../lib/position.ts';
import { useSimClock } from '../store/useSimClock.ts';
import { ProvenanceBadge } from '../components/ProvenanceBadge.tsx';
import { Panel, EmptyState, ErrorNote, Stat } from '../components/ui.tsx';
import { num } from '../lib/format.ts';
import { normalizeProvenance, type ProvenanceLike } from '../lib/provenance.ts';

function kindBadge(prov: ProvenanceLike | null): JSX.Element | null {
  if (!prov) return null;
  const norm = normalizeProvenance(prov);
  if (!norm) return null;
  return <ProvenanceBadge provenance={norm} size="sm" showAge={false} />;
}

export function Sail(): JSX.Element {
  const { scene, fitTargets } = useScene();
  const voyage = useAppStore((s) => s.voyage);
  const phase = useAppStore((s) => s.voyagePhase);
  const error = useAppStore((s) => s.voyageError);
  const setVoyagePhase = useAppStore((s) => s.setVoyagePhase);

  const [source] = useState(() => new RecordedTimelineSource());
  const positionSourceRef = useRef<ReturnType<typeof SimulatedPositionSource> | null>(null);
  const [fix, setFix] = useState<ReturnType<typeof SimulatedPositionSource.prototype.now> | null>(null);

  useEffect(() => {
    let cancelled = false;
    source.getTimeline().then((tl) => {
      if (cancelled) return;
      useSimClock.getState().setTimeline(tl);
      positionSourceRef.current = SimulatedPositionSource({ timeline: tl });
      const first = tl[0];
      if (first) setFix({
        index: first.index, t_utc: first.t_utc, sim_hours: first.sim_hours,
        lat: first.lat, lon: first.lon, sog_kn: first.sog_kn, cog: first.cog,
        heading: first.heading, ice_conc: first.ice_conc, ice_thick_m: first.ice_thick_m,
        wind_speed_ms: first.wind_speed_ms, wind_dir_from_deg: first.wind_dir_from_deg,
        hs_m: first.hs_m, visibility_km: first.visibility_km,
        nearest_contact_nm: first.nearest_contact_nm, active_alerts: first.active_alerts,
      });
    });
    return () => { cancelled = true; };
  }, [source]);

  useEffect(() => {
    if (!positionSourceRef.current) return;
    const unsub = positionSourceRef.current.subscribe((fix: any) => setFix(fix));
    return unsub;
  }, [positionSourceRef]);

  const running = phase === 'running';
  const busy = phase === 'creating' || phase === 'connecting';
  const started = Boolean(voyage);
  const speed = useSimClock((s) => s.speed);
  const paused = useSimClock((s) => s.paused);

  const handlePause = useCallback(() => {
    useSimClock.getState().setPaused(true);
    setVoyagePhase('paused');
  }, [setVoyagePhase]);

  const handleStep = useCallback(() => {
    useSimClock.getState().setSimMs(useSimClock.getState().simMs + 6 * 3600 * 1000);
  }, []);

  const emptyState = !started ? (
    <EmptyState title="Plan a route first" detail="Go to Plan, compare candidates, then start the voyage." />
  ) : error ? (
    <ErrorNote message={error} />
  ) : null;

  const provIce = fix ? pointProvenance(fix as any, 'ice_conc') : null;

  return (
    <>
      <MapStage id="sail" map={<ChartViews scene={scene} fitTargets={fitTargets} />}
        shelf={
          <>
            {fix && (
              <Panel title="Position" subtitle={fix.t_utc}>
                <Stat label="Lat" value={num(fix.lat, 3)} unit="°" size="sm" />
                <Stat label="Lon" value={num(fix.lon, 3)} unit="°" size="sm" />
                <div className="mt-2 flex items-baseline gap-2">
                  <span className="text-2xs text-ink-3">Provenance</span>
                  {kindBadge(provIce)}
                </div>
              </Panel>
            )}
            {emptyState}
          </>
        }
      />
      <div className="mt-3 flex flex-wrap items-center justify-between gap-2 border-t border-hair pt-3">
        <div className="flex items-center gap-1">
          <span className="text-2xs text-ink-3">Sim speed</span>
          <button type="button" className="btn" onClick={handlePause} disabled={!started || busy} aria-label={paused ? 'Play' : 'Pause'}>{paused ? <Play size={13} /> : <Pause size={13} />}</button>
          <button type="button" className="btn" onClick={handleStep} disabled={!started || running || busy} aria-label="Step"><SkipForward size={13} /> Step</button>
          <button type="button" className="btn" onClick={() => setVoyagePhase('idle')} disabled={!started} aria-label="Stop"><Square size={13} /> Stop</button>
        </div>
        <div className="flex items-center gap-2">
          <button key={1} data-testid="speed-1" type="button" className={`btn ${speed === 1 ? 'btn-accent' : ''}`} onClick={() => useSimClock.getState().setSpeed(1)} disabled={!started}>1×</button>
          <button key={60} data-testid="speed-60" type="button" className={`btn ${speed === 60 ? 'btn-accent' : ''}`} onClick={() => useSimClock.getState().setSpeed(60)} disabled={!started}>60×</button>
          <button key={600} data-testid="speed-600" type="button" className={`btn ${speed === 600 ? 'btn-accent' : ''}`} onClick={() => useSimClock.getState().setSpeed(600)} disabled={!started}>600×</button>
          <button key={3600} data-testid="speed-3600" type="button" className={`btn ${speed === 3600 ? 'btn-accent' : ''}`} onClick={() => useSimClock.getState().setSpeed(3600)} disabled={!started}>3600×</button>
        </div>
      </div>
    </>
  );
}

function pointProvenance(point: any, variable: string): ProvenanceLike | null {
  const rec = point.provenance_by_variable?.[variable];
  if (!rec) return null;
  const norm = normalizeProvenance(rec);
  return norm;
}
