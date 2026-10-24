/**
 * The chart area with two views of one voyage: the Antarctic navigation chart and a regional context map.
 *
 * Both are driven by the same scene, so the route, ports, stations and vessel are the same in each. The
 * polar chart is never unmounted: its pan, zoom and fitted route survive a trip to the regional view
 * and back, which is how the rest of the app treats screens too. While the regional view is up, the
 * polar chart is told it is inactive, so its particle overlay stops rather than animating unseen.
 *
 * VISIBILITY RULE (do not break). App hides an inactive screen with `visibility: hidden` on the screen
 * wrapper. CSS visibility is inherited, but a descendant that sets `visibility: visible` explicitly escapes
 * its hidden ancestor and paints over whatever screen is showing. So a view that is ACTIVE must set nothing
 * (it inherits), and only an inactive view sets `hidden`. Never write `visibility: 'visible'` below the
 * screen wrapper; tests/visibility-rule.test.ts fails the build if anyone does.
 */
import { useState } from 'react';
import { MapCanvas, type MapCanvasHandle } from '../map/MapCanvas';
import type { MapScene } from '../map/MapEngine';
import type { RouteProfileId } from '../api/types';
import { RegionalMap } from '../map/RegionalMap';
import type { LatLon } from '../map/projection';
import { useAppStore } from '../store/useAppStore';
import { ScreenActiveContext, useScreenActive } from './screenActive';
import { Segmented } from './MapToolbar';

type View = 'antarctic' | 'regional';

const HIDDEN = { visibility: 'hidden' } as const;

const VIEWS: { id: View; label: string; hint: string }[] = [
  { id: 'antarctic', label: 'Polar', hint: 'Antarctic navigation chart (polar stereographic, EPSG:3031)' },
  { id: 'regional', label: 'Regional', hint: 'Mercator map of the voyage region: ports, coasts and countries' },
];

export function ChartViews({
  scene,
  fitTargets,
  onClickPoint,
  onSelectRouteCandidate,
}: {
  scene: MapScene;
  fitTargets: { lat: number; lon: number }[];
  onClickPoint?: (ll: LatLon) => void;
  onSelectRouteCandidate?: (id: RouteProfileId) => void;
}): JSX.Element {
  const [view, setView] = useState<View>('antarctic');
  const [polar, setPolar] = useState<MapCanvasHandle | null>(null);
  const screenActive = useScreenActive();
  const originId = useAppStore((s) => s.planner.originId);
  const destinationId = useAppStore((s) => s.planner.destinationId);

  const lead = <Segmented label="Chart view" value={view} options={VIEWS} onChange={setView} />;

  return (
    <div className="relative h-full w-full">
      <div
        className="absolute inset-0"
        style={view === 'antarctic' ? undefined : HIDDEN}
        aria-hidden={view !== 'antarctic'}
      >
        <ScreenActiveContext.Provider value={screenActive && view === 'antarctic'}>
          <MapCanvas scene={scene} fitTargets={fitTargets} onClickPoint={onClickPoint} onReady={setPolar} toolbarLead={lead} />
        </ScreenActiveContext.Provider>
      </div>

      <div
        className="absolute inset-0"
        style={view === 'regional' ? undefined : HIDDEN}
        aria-hidden={view !== 'regional'}
      >
        <RegionalMap
          scene={scene}
          visible={screenActive && view === 'regional'}
          polarEngine={polar?.engine ?? null}
          originId={originId}
          destinationId={destinationId}
          onSelectRouteCandidate={onSelectRouteCandidate ?? (() => undefined)}
          toolbarLead={lead}
        />
      </div>

    </div>
  );
}
