/**
 * Application shell: a masthead across the top, a navigation rail down the left, and the working
 * area beside it.
 *
 * Five views, named for what the operator does in them:
 *   Plan      choose a passage and get a recommended route
 *   Sail      watch the ship follow it and handle re-routing
 *   Sea ice   the ice forecast
 *   Icebergs  tracked bergs and where they are heading
 *   Insights  the numbers behind the recommendation
 *
 * Plan and Sail are the main flow and are always shown. The other three appear in Full view, as
 * before; the Simple/Full switch behaves exactly as it did.
 *
 * All views stay mounted and are hidden rather than unmounted. Each holds a map canvas and a
 * viewport the user has panned and zoomed; rebuilding that on every tab change would lose their
 * place, and a chart that forgets where you were looking is an irritating one.
 */
import { Activity, BarChart3, ClipboardList, Layers, Ship, Snowflake } from 'lucide-react';
import { ProvenanceBar } from './components/ProvenanceBar';
import { ProvenanceBadge } from './components/ProvenanceBadge';
import { ScreenActiveContext } from './components/screenActive';
import { useHealth } from './api/queries';
import { Analytics } from './screens/Analytics';
import { BridgeConsole } from './screens/BridgeConsole';
import { IceForecast } from './screens/IceForecast';
import { IcebergTracker } from './screens/IcebergTracker';
import { Sail } from './screens/Sail';
import { Scorecard } from './screens/Scorecard';
import { VoyagePlanner } from './screens/VoyagePlanner';
import { useAppStore, type ScreenId } from './store/useAppStore';

interface Tab {
  id: ScreenId;
  label: string;
  icon: typeof Ship;
  /** Shown in Simple view. */
  simple: boolean;
}

const TABS: Tab[] = [
  { id: 'planner', label: 'Plan', icon: Layers, simple: true },
  { id: 'bridge', label: 'Sail', icon: Ship, simple: true },
  { id: 'sail', label: 'Voyage', icon: Ship, simple: false },
  { id: 'forecast', label: 'Sea ice', icon: Snowflake, simple: false },
  { id: 'icebergs', label: 'Icebergs', icon: Activity, simple: false },
  { id: 'analytics', label: 'Insights', icon: BarChart3, simple: false },
  { id: 'scorecard', label: 'Scorecard', icon: ClipboardList, simple: false },
];

export function App(): JSX.Element {
  const screen = useAppStore((s) => s.screen);
  const setScreen = useAppStore((s) => s.setScreen);
  const simpleMode = useAppStore((s) => s.simpleMode);
  const setSimpleMode = useAppStore((s) => s.setSimpleMode);
  const health = useHealth();

  const online = health.isSuccess;
  const visibleTabs = simpleMode ? TABS.filter((t) => t.simple) : TABS;

  // If the user switches to Simple while on an advanced screen, move them somewhere that exists.
  const activeScreen: ScreenId = visibleTabs.some((t) => t.id === screen) ? screen : 'planner';

  return (
    <div className="flex h-screen flex-col overflow-hidden bg-ground text-ink">
      <header className="relative z-40 flex h-14 shrink-0 items-center gap-4 border-b border-hair bg-panel px-5">
        <div className="flex min-w-0 shrink-0 items-baseline gap-3">
          <span className="display text-[22px] tracking-[0.08em] text-accent">ICEFLOW</span>
          <span className="hidden truncate text-2xs text-ink-3 xl:inline">
            AI/ML-Enabled Antarctic Navigation Decision Support Platform
          </span>
        </div>

        <div className="flex min-w-0 flex-1 justify-center">
          {activeScreen === 'planner' || activeScreen === 'bridge' ? (
            <div className="flex items-center gap-2 text-2xs">
              <span className="text-ink-3">Regional data:</span>
              <ProvenanceBadge provenance={{ status: 'observed', source: 'Copernicus sea-ice edge', note: 'OSI-SAF NRT product' }} size="sm" />
              <ProvenanceBadge provenance={{ status: 'forecast', source: 'GFS wind', note: '0.25 degree analysis' }} size="sm" />
              <ProvenanceBadge provenance={{ status: 'simulated', source: 'Model iceberg catalogue', note: 'RK4 drift from seeded positions' }} size="sm" />
            </div>
          ) : (
            <ProvenanceBar />
          )}
        </div>

        <div className="flex shrink-0 items-center gap-3">
          <button
            type="button"
            onClick={() => setSimpleMode(!simpleMode)}
            className={`rounded-full border px-3.5 py-1.5 text-xs transition-colors ${
              simpleMode
                ? 'border-hair-2 bg-panel text-ink-2 hover:border-accent hover:text-accent'
                : 'border-violet/50 bg-violet/10 text-violet'
            }`}
            title={
              simpleMode
                ? 'Show the ice forecast, iceberg and analytics screens'
                : 'Hide the analytical screens and show only the main flow'
            }
          >
            {simpleMode ? 'Simple view' : 'Full view'}
          </button>

          <div className="flex items-center gap-2 border-l border-hair pl-3" role="status">
            <span className={`block h-2 w-2 rounded-full ${online ? 'bg-ok' : 'bg-danger'}`} aria-hidden />
            <span className="text-xs text-ink-2">{online ? 'Connected' : 'Backend offline'}</span>
          </div>
        </div>
      </header>

      <div className="flex min-h-0 flex-1">
        <nav aria-label="Views" className="flex w-[72px] shrink-0 flex-col items-stretch gap-1 border-r border-hair bg-panel px-2 py-2.5">
          {visibleTabs.map(({ id, label, icon: Icon }) => {
            const active = activeScreen === id;
            return (
              <button
                key={id}
                type="button"
                onClick={() => setScreen(id)}
                aria-current={active ? 'page' : undefined}
                className={`flex flex-col items-center gap-1 rounded-lg px-1 py-2.5 text-2xs transition-colors ${
                  active
                    ? 'bg-accent font-semibold text-on-accent shadow-card'
                    : 'text-ink-2 hover:bg-panel-3 hover:text-ink'
                }`}
              >
                <Icon size={20} aria-hidden />
                <span>{label}</span>
              </button>
            );
          })}
        </nav>

        <main className="relative min-h-0 min-w-0 flex-1">
          <Screen id="planner" active={activeScreen}>
            <VoyagePlanner />
          </Screen>
          <Screen id="bridge" active={activeScreen}>
            <BridgeConsole />
          </Screen>
          <Screen id="sail" active={activeScreen}>
            <Sail />
          </Screen>
          <Screen id="forecast" active={activeScreen}>
            <IceForecast />
          </Screen>
          <Screen id="icebergs" active={activeScreen}>
            <IcebergTracker />
          </Screen>
          <Screen id="analytics" active={activeScreen}>
            <Analytics />
          </Screen>
          <Screen id="scorecard" active={activeScreen}>
            <Scorecard />
          </Screen>
        </main>
      </div>
    </div>
  );
}

function Screen({
  id,
  active,
  children,
}: {
  id: ScreenId;
  active: ScreenId;
  children: React.ReactNode;
}): JSX.Element {
  const visible = id === active;
  return (
    <div
      className="absolute inset-0 overflow-hidden"
      style={{ visibility: visible ? 'visible' : 'hidden', pointerEvents: visible ? 'auto' : 'none' }}
      aria-hidden={!visible}
    >
      <ScreenActiveContext.Provider value={visible}>{children}</ScreenActiveContext.Provider>
    </div>
  );
}
