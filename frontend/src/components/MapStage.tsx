/**
 * The map stage: a stable workspace in which the map is the main region and nothing else may cover it.
 *
 *   map          the chart. Its cell has a guaranteed minimum size, and every map overlay (controls, legend,
 *                layer panel, notices) is positioned inside THIS cell, so none can run underneath a panel
 *   leftDock     optional set of panels on the left, shown as vertical tabs + one visible panel
 *   rightDock    optional set of panels on the right, same idea
 *
 * WHY THIS REPLACES THE FLOATING LAYOUT
 * The earlier stage drew the chart full-bleed and floated every panel over it. That put the map's own
 * overlays and the panels in competition for the same pixels, and it relied on measured "insets" that each
 * overlay had to remember to honour. Here the regions simply do not overlap, so there is nothing to remember.
 *
 * HEIGHT / WIDTH BUDGET
 * The stage measures itself. The docks are given whatever space is left after the map's
 * minimums (300 px tall, 320 px wide), never more. If there is not enough room, a side dock stays
 * collapsed to its tab strip, and the bottom dock stays collapsed to its tab strip.
 *
 * The public props for the bottom `shelf` and optional `top`/`tray` are preserved for screens
 * that have not yet migrated to the side-dock layout (e.g. BridgeConsole, IceForecast). The Plan
 * screen uses `leftDock` and `rightDock` exclusively.
 */
import {
  Children,
  Fragment,
  cloneElement,
  isValidElement,
  useCallback,
  useEffect,
  useId,
  useMemo,
  useRef,
  useState,
  type KeyboardEvent,
  type ReactElement,
  type ReactNode,
  type RefObject,
} from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import {
  DOCK_BAR_HEIGHT,
  DOCK_PANEL_MAX,
  fullBudget,
  type StageBudget,
} from './stageBudget';
import { StageInsetsContext, type StageInsets } from './stageInsets';

/** A boolean kept in localStorage. Storage can be blocked; the choice then simply does not persist. */
function usePersistentFlag(key: string, initial: () => boolean): [boolean, (v: boolean) => void] {
  const [value, setValue] = useState<boolean>(() => {
    try {
      const raw = window.localStorage.getItem(key);
      if (raw !== null) return raw === '1';
    } catch {
      /* fall through to the default */
    }
    return initial();
  });
  const set = useCallback(
    (v: boolean) => {
      setValue(v);
      try {
        window.localStorage.setItem(key, v ? '1' : '0');
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [value, set];
}

function usePersistentString(key: string): [string | null, (v: string) => void] {
  const [value, setValue] = useState<string | null>(() => {
    try {
      return window.localStorage.getItem(key);
    } catch {
      return null;
    }
  });
  const set = useCallback(
    (v: string) => {
      setValue(v);
      try {
        window.localStorage.setItem(key, v);
      } catch {
        /* storage unavailable */
      }
    },
    [key],
  );
  return [value, set];
}

/** Short windows start with the dock closed, so the chart is not buried on first load. */
const roomForDock = (): boolean => window.innerHeight >= 800;

/** Short windows start with the side dock closed. */
const roomForSideDock = (): boolean => window.innerWidth >= 1200;

/** Flatten fragments so a `shelf` or `leftDock` written as <>...</> yields its panels. */
export function flattenPanels(node: ReactNode): ReactElement[] {
  const out: ReactElement[] = [];
  Children.forEach(node, (child) => {
    if (!isValidElement(child)) return;
    if (child.type === Fragment) {
      out.push(...flattenPanels((child.props as { children?: ReactNode }).children));
    } else {
      out.push(child);
    }
  });
  return out;
}

interface PanelProps {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
}

interface Props {
  /** Unique per screen; keys the remembered open/closed state. */
  id: string;
  /** The chart, plus any overlay that should cover the whole map. */
  map: ReactNode;
  top?: ReactNode;
  tray?: ReactNode;
  /** Bottom dock panels (tabs along the bottom). Preserved for screens that have not migrated. */
  shelf?: ReactNode;
  shelfLabel?: string;
  /** Left side dock panels (tabs vertically along the left). */
  leftDock?: ReactNode;
  /** Right side dock panels (tabs vertically along the right). */
  rightDock?: ReactNode;
  leftDockLabel?: string;
  rightDockLabel?: string;
}

/** Flat styling for content that arrives wearing a floating card (rounded, shadowed, translucent). */
const FLAT =
  '[&_.float]:rounded-none [&_.float]:border-0 [&_.float]:bg-transparent [&_.float]:shadow-none [&_.float]:backdrop-blur-none';

/** Insets are zero now: the map cell is exactly the visible map, so overlays need no clearance maths. */
const NO_INSETS: StageInsets = { left: 0, right: 0, top: 0, bottom: 0 };

function useSize(ref: RefObject<HTMLElement>): number {
  const [size, setSize] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el) {
      setSize(0);
      return undefined;
    }
    const read = (): void => {
      const rect = el.getBoundingClientRect();
      setSize(Math.round(rect.width));
    };
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref]);
  return size;
}

function useHeight(ref: RefObject<HTMLElement>, active: boolean): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || !active) {
      setHeight(0);
      return undefined;
    }
    const read = (): void => setHeight(Math.round(el.getBoundingClientRect().height));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, active]);
  return height;
}

interface DockState {
  open: boolean;
  savedTab: string | null;
  setSavedTab: (v: string) => void;
  setOpen: (v: boolean) => void;
}

function useDockState(id: string, initial: boolean): DockState {
  const [open, setOpen] = usePersistentFlag(`iceflow.${id}.dock`, () => initial);
  const [savedTab, setSavedTab] = usePersistentString(`iceflow.${id}.dockTab`);
  return { open, savedTab, setSavedTab, setOpen };
}

function SideDock({
  uid,
  label,
  panels,
  side,
  open,
  canOpen,
  panelMax,
  onOpen,
  onTab,
  savedTab,
}: {
  uid: string;
  label: string;
  panels: ReactElement[];
  side: 'left' | 'right';
  open: boolean;
  canOpen: boolean;
  panelMax: number;
  onOpen: (v: boolean) => void;
  onTab: (v: string) => void;
  savedTab: string | null;
}): JSX.Element | null {
  if (panels.length === 0) return null;
  const labels = panels.map((p, i) => (p.props as PanelProps).title ?? `${label} ${i + 1}`);
  const activeIndex = Math.max(0, savedTab ? labels.indexOf(savedTab) : 0);
  const active = panels[activeIndex];
  const dockOpen = open && canOpen;

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (!['ArrowUp', 'ArrowDown', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const last = panels.length - 1;
    const next =
      e.key === 'Home' ? 0 : e.key === 'End' ? last : (activeIndex + (e.key === 'ArrowDown' ? 1 : -1) + panels.length) % panels.length;
    onTab(labels[next]);
    document.getElementById(`${uid}-${side}tab-${next}`)?.focus();
  };

  return (
    <section
      data-testid={`${side}-dock`}
      aria-label={label}
      className={`flex shrink-0 items-stretch border-${side === 'left' ? 'r' : 'l'} border-hair bg-panel`}
    >
      <div
        role="tablist"
        aria-label={label}
        aria-orientation="vertical"
        className="flex min-w-0 flex-col items-stretch overflow-y-auto"
        onKeyDown={onTabKey}
      >
        {panels.map((p, i) => {
          const selected = i === activeIndex;
          const props = p.props as PanelProps;
          return (
            <div
              key={labels[i]}
              className={`flex items-center justify-between border-b border-hair/50 transition-colors ${
                selected && dockOpen ? 'bg-accent/5' : ''
              }`}
            >
              <button
                id={`${uid}-${side}tab-${i}`}
                type="button"
                role="tab"
                aria-selected={selected}
                aria-controls={`${uid}-${side}panel`}
                tabIndex={selected ? 0 : -1}
                onClick={() => {
                  onTab(labels[i]);
                  if (!open && canOpen) onOpen(true);
                }}
                className={`flex-1 truncate px-3 py-2 text-left text-2xs ${
                  selected && dockOpen ? 'font-semibold text-accent' : 'text-ink-2 hover:text-ink'
                }`}
              >
                {labels[i]}
              </button>
              {props.right && <span className="shrink-0 pr-2">{props.right}</span>}
            </div>
          );
        })}
      </div>

      {dockOpen && active && (
        <div
          id={`${uid}-${side}panel`}
          role="tabpanel"
          aria-labelledby={`${uid}-${side}tab-${activeIndex}`}
          className="overflow-y-auto border-t border-hair"
          style={{ maxWidth: panelMax, width: panelMax === 0 ? 280 : undefined }}
        >
          {(active.props as PanelProps).subtitle && (
            <p className="px-4 pt-2 text-2xs text-ink-3">{(active.props as PanelProps).subtitle}</p>
          )}
          {cloneElement(active as ReactElement<Record<string, unknown>>, {
            title: undefined,
            subtitle: undefined,
            right: undefined,
            className: '!rounded-none !border-0 !bg-transparent !shadow-none',
          })}
        </div>
      )}
    </section>
  );
}

function BottomDock({
  uid,
  label,
  panels,
  open,
  canOpen,
  panelMax,
  onOpen,
  onTab,
  savedTab,
}: {
  uid: string;
  label: string;
  panels: ReactElement[];
  open: boolean;
  canOpen: boolean;
  panelMax: number;
  onOpen: (v: boolean) => void;
  onTab: (v: string) => void;
  savedTab: string | null;
}): JSX.Element | null {
  if (panels.length === 0) return null;
  const labels = panels.map((p, i) => (p.props as PanelProps).title ?? `${label} ${i + 1}`);
  const activeIndex = Math.max(0, savedTab ? labels.indexOf(savedTab) : 0);
  const active = panels[activeIndex];
  const dockOpen = open && canOpen;

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const last = panels.length - 1;
    const next =
      e.key === 'Home' ? 0 : e.key === 'End' ? last : (activeIndex + (e.key === 'ArrowRight' ? 1 : -1) + panels.length) % panels.length;
    onTab(labels[next]);
    document.getElementById(`${uid}-tab-${next}`)?.focus();
  };

  return (
    <section data-testid="dock" className="shrink-0 border-t border-hair bg-panel" aria-label={label}>
      <div className="flex items-stretch" style={{ height: DOCK_BAR_HEIGHT }}>
        <div
          role="tablist"
          aria-label={label}
          className="flex min-w-0 flex-1 items-stretch overflow-x-auto"
          onKeyDown={onTabKey}
        >
          {panels.map((p, i) => {
            const selected = i === activeIndex;
            const props = p.props as PanelProps;
            return (
              <div
                key={labels[i]}
                className={`flex shrink-0 items-center gap-2 border-b-2 pr-3 transition-colors ${
                  selected && dockOpen ? 'border-accent' : 'border-transparent'
                }`}
              >
                <button
                  id={`${uid}-tab-${i}`}
                  type="button"
                  role="tab"
                  aria-selected={selected}
                  aria-controls={`${uid}-panel`}
                  tabIndex={selected ? 0 : -1}
                  onClick={() => {
                    onTab(labels[i]);
                    if (!open && canOpen) onOpen(true);
                  }}
                  className={`h-full whitespace-nowrap pl-4 text-xs transition-colors ${
                    selected && dockOpen ? 'font-semibold text-ink' : 'text-ink-3 hover:text-ink'
                  }`}
                >
                  <span className="display text-[13px]">{labels[i]}</span>
                </button>
                {props.right}
              </div>
            );
          })}
        </div>
        <button
          type="button"
          className="flex shrink-0 items-center gap-1 border-l border-hair px-3 text-2xs text-ink-3 hover:text-ink disabled:opacity-40"
          aria-expanded={dockOpen}
          aria-controls={`${uid}-panel`}
          disabled={!canOpen}
          title={canOpen ? undefined : 'Not enough window height to open the panels'}
          onClick={() => onOpen(!open)}
        >
          {dockOpen ? 'Hide' : 'Show'}
          {dockOpen ? <ChevronDown size={14} aria-hidden /> : <ChevronUp size={14} aria-hidden />}
        </button>
      </div>

      {dockOpen && active && (
        <div
          id={`${uid}-panel`}
          role="tabpanel"
          aria-labelledby={`${uid}-tab-${activeIndex}`}
          className="overflow-y-auto border-t border-hair bg-panel"
          style={{ maxHeight: panelMax }}
        >
          {(active.props as PanelProps).subtitle && (
            <p className="px-4 pt-2 text-2xs text-ink-3">{(active.props as PanelProps).subtitle}</p>
          )}
          {cloneElement(active as ReactElement<Record<string, unknown>>, {
            title: undefined,
            subtitle: undefined,
            right: undefined,
            className: '!rounded-none !border-0 !bg-transparent !shadow-none',
          })}
        </div>
      )}
    </section>
  );
}

export function MapStage({
  id,
  map,
  top,
  tray,
  shelf,
  shelfLabel = 'Panels',
  leftDock,
  rightDock,
  leftDockLabel = 'Left panels',
  rightDockLabel = 'Right panels',
}: Props): JSX.Element {
  const stageRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const uid = useId();

  const leftPanels = useMemo(() => flattenPanels(leftDock), [leftDock]);
  const rightPanels = useMemo(() => flattenPanels(rightDock), [rightDock]);
  const bottomPanels = useMemo(() => flattenPanels(shelf), [shelf]);

  const hasBottomDock = bottomPanels.length > 0;
  const hasLeftDock = leftPanels.length > 0;
  const hasRightDock = rightPanels.length > 0;
  const hasTray = Boolean(tray);

  const bottomDockState = useDockState(`${id}.bottom`, roomForDock());
  const leftDockState = useDockState(`${id}.left`, roomForSideDock());
  const rightDockState = useDockState(`${id}.right`, roomForSideDock());

  const stageHeight = useHeight(stageRef, true);
  const stageWidth = useSize(stageRef);
  const topHeight = useHeight(topRef, Boolean(top));

  const room = useMemo(
    () =>
      stageHeight > 0 && stageWidth > 0
        ? fullBudget(stageWidth, stageHeight, topHeight, hasBottomDock, hasTray, hasLeftDock, hasRightDock, leftDockState.open, rightDockState.open)
        : {
            panelMax: DOCK_PANEL_MAX,
            canOpen: true,
            trayMax: 360,
            topMax: 10_000,
            mapHeight: 300,
            leftCanOpen: true,
            leftPanelMax: 480,
            rightCanOpen: true,
            rightPanelMax: 480,
            mapWidth: 320,
          } as StageBudget,
    [stageHeight, stageWidth, topHeight, hasBottomDock, hasTray, hasLeftDock, hasRightDock, leftDockState.open, rightDockState.open],
  );

  return (
    <div ref={stageRef} className="flex h-full min-h-0 w-full flex-col overflow-hidden bg-ground">
      {top && (
        <div
          ref={topRef}
          className={`shrink-0 overflow-y-auto border-b border-hair bg-panel px-4 py-2.5 ${FLAT}`}
          style={stageHeight > 0 ? { maxHeight: room.topMax } : undefined}
        >
          {top}
        </div>
      )}

      <div data-testid="map-cell" className="relative min-h-0 flex-1 overflow-hidden" style={{ minHeight: room.mapHeight, minWidth: room.mapWidth }}>
        <div className="absolute inset-0 flex">
          {hasLeftDock && (
            <SideDock
              uid={uid}
              label={leftDockLabel}
              panels={leftPanels}
              side="left"
              open={leftDockState.open}
              canOpen={room.leftCanOpen}
              panelMax={room.leftPanelMax}
              onOpen={leftDockState.setOpen}
              onTab={leftDockState.setSavedTab}
              savedTab={leftDockState.savedTab}
            />
          )}

          <div data-testid="map-inner" className="relative min-w-0 flex-1 overflow-hidden">
            <StageInsetsContext.Provider value={NO_INSETS}>{map}</StageInsetsContext.Provider>
          </div>

          {hasRightDock && (
            <SideDock
              uid={uid}
              label={rightDockLabel}
              panels={rightPanels}
              side="right"
              open={rightDockState.open}
              canOpen={room.rightCanOpen}
              panelMax={room.rightPanelMax}
              onOpen={rightDockState.setOpen}
              onTab={rightDockState.setSavedTab}
              savedTab={rightDockState.savedTab}
            />
          )}
        </div>
      </div>

      {tray && (
        <div
          className={`shrink-0 overflow-y-auto border-t border-hair bg-panel ${FLAT}`}
          style={stageHeight > 0 ? { maxHeight: room.trayMax } : undefined}
        >
          {tray}
        </div>
      )}

      {hasBottomDock && (
        <BottomDock
          uid={uid}
          label={shelfLabel}
          panels={bottomPanels}
          open={bottomDockState.open}
          canOpen={room.canOpen}
          panelMax={room.panelMax}
          onOpen={(v) => {
            bottomDockState.setOpen(v);
            if (v) bottomDockState.setSavedTab(bottomDockState.savedTab ?? '');
          }}
          onTab={bottomDockState.setSavedTab}
          savedTab={bottomDockState.savedTab}
        />
      )}
    </div>
  );
}
