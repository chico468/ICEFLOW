/**
 * The chart area with two views of one voyage: the Antarctic navigation chart and a regional context map.
 *
 * Both are driven by the same scene, so the route, ports, stations and vessel are the same in each. The
 * polar chart is never unmounted: its pan, zoom and fitted route survive a trip to the regional view
 * and back, which is how the rest of the app treats screens too. While the regional view is up, the
 * polar chart is told it is inactive, so its particle overlay stops rather than animating unseen.
 */
import { useState } from 'react';
import { MapCanvas, type MapCanvasHandle } from '../map/MapCanvas';
import type { MapScene } from '../map/MapEngine';
import { RegionalMap } from '../map/RegionalMap';
import type { LatLon } from '../map/projection';
import { useAppStore } from '../store/useAppStore';
import { ScreenActiveContext, useScreenActive } from './screenActive';
import { useStageInsets } from './stageInsets';

type View = 'antarctic' | 'regional';

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: 'antarctic', label: 'Antarctic chart', hint: 'Polar stereographic navigation chart (EPSG:3031)' },
  { id: 'regional', label: 'Regional context', hint: 'Mercator map of the voyage region: ports, coasts and countries' },
];

export function ChartViews({
  scene,
  fitTargets,
  onClickPoint,
}: {
  scene: MapScene;
  fitTargets: { lat: number; lon: number }[];
  onClickPoint?: (ll: LatLon) => void;
}): JSX.Element {
  const [view, setView] = useState<View>('antarctic');
  const [polar, setPolar] = useState<MapCanvasHandle | null>(null);
  const screenActive = useScreenActive();
  const insets = useStageInsets();
  const originId = useAppStore((s) => s.planner.originId);
  const destinationId = useAppStore((s) => s.planner.destinationId);

  return (
    <div className="relative h-full w-full">
      <div
        className="absolute inset-0"
        style={{ visibility: view === 'antarctic' ? 'visible' : 'hidden' }}
        aria-hidden={view !== 'antarctic'}
      >
        <ScreenActiveContext.Provider value={screenActive && view === 'antarctic'}>
          <MapCanvas scene={scene} fitTargets={fitTargets} onClickPoint={onClickPoint} onReady={setPolar} />
        </ScreenActiveContext.Provider>
      </div>

      <div
        className="absolute inset-0"
        style={{ visibility: view === 'regional' ? 'visible' : 'hidden' }}
        aria-hidden={view !== 'regional'}
      >
        <RegionalMap
          scene={scene}
          visible={screenActive && view === 'regional'}
          polarEngine={polar?.engine ?? null}
          originId={originId}
          destinationId={destinationId}
        />
      </div>

      <div
        role="group"
        aria-label="Chart view"
        className="float absolute left-1/2 z-20 flex -translate-x-1/2 gap-1 p-1"
        style={{ top: Math.max(12, insets.top) }}
      >
        {VIEWS.map((v) => (
          <button
            key={v.id}
            type="button"
            title={v.hint}
            aria-pressed={view === v.id}
            className={`btn ${view === v.id ? 'btn-accent' : ''}`}
            onClick={() => setView(v.id)}
          >
            {v.label}
          </button>
        ))}
      </div>
    </div>
  );
}
