/**
 * The map stage: a stable workspace in which the map is the main region and nothing else may cover it.
 *
 *   top     a command bar above the map (used by Plan)
 *   map     the chart. Its cell has a guaranteed minimum height, and every map overlay (controls, legend,
 *           layer panel, notices) is positioned inside THIS cell, so none can run underneath a panel
 *   tray    a result region below the map (used by Plan)
 *   shelf   instrument panels below the map, shown as TABS, one at a time, in a collapsible dock
 *
 * WHY THIS REPLACES THE FLOATING LAYOUT
 * The earlier stage drew the chart full-bleed and floated every panel over it. That put the map's own
 * overlays and the panels in competition for the same pixels, and it relied on measured "insets" that each
 * overlay had to remember to honour. Several did not (the layer panel ran under the dock; a view switcher
 * sat on a notice). Here the regions simply do not overlap, so there is nothing to remember.
 *
 * HEIGHT BUDGET
 * The stage measures itself. The dock and the top bar are given whatever height is left after the map's
 * minimum, never more, and scroll inside themselves. If there is not enough room to open the dock, it stays
 * collapsed (its tab strip, with each panel's status badge, is always visible).
 *
 * The public props are unchanged, so screens keep passing `<Panel title=...>` children as `shelf`; the tab
 * label and badge are read from each Panel's own `title` and `right`.
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
import { DOCK_BAR_HEIGHT, DOCK_PANEL_MAX, MAP_MIN_HEIGHT, TRAY_MAX, budget } from './stageBudget';
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

/** The rendered height of an element, kept current as it resizes. Zero while it is absent. */
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

/** Short windows start with the dock closed, so the chart is not buried on first load. */
const roomForDock = (): boolean => window.innerHeight >= 800;

/** Flatten fragments so a `shelf` written as <>...</> yields its panels. */
export function flattenPanels(node: ReactNode): ReactElement[] {
  const out: ReactElement[] = [];
  Children.forEach(node, (child) => {
    if (!isValidElement(child)) return;
    if (child.type === Fragment) out.push(...flattenPanels((child.props as { children?: ReactNode }).children));
    else out.push(child);
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
  /** The chart, plus any overlay that should cover the whole map (for example a compute overlay). */
  map: ReactNode;
  top?: ReactNode;
  tray?: ReactNode;
  shelf?: ReactNode;
  shelfLabel?: string;
}

/** Flat styling for content that arrives wearing a floating card (rounded, shadowed, translucent). */
const FLAT =
  '[&_.float]:rounded-none [&_.float]:border-0 [&_.float]:bg-transparent [&_.float]:shadow-none [&_.float]:backdrop-blur-none';

/** Insets are zero now: the map cell is exactly the visible map, so overlays need no clearance maths. */
const NO_INSETS: StageInsets = { left: 0, right: 0, top: 0, bottom: 0 };

export function MapStage({ id, map, top, tray, shelf, shelfLabel = 'Panels' }: Props): JSX.Element {
  const stageRef = useRef<HTMLDivElement>(null);
  const topRef = useRef<HTMLDivElement>(null);
  const uid = useId();

  const panels = useMemo(() => flattenPanels(shelf), [shelf]);
  const hasDock = panels.length > 0;
  const hasTray = Boolean(tray);

  const [open, setOpen] = usePersistentFlag(`iceflow.${id}.dock`, roomForDock);
  const [savedTab, setSavedTab] = usePersistentString(`iceflow.${id}.dockTab`);

  const stageHeight = useHeight(stageRef, true);
  const topHeight = useHeight(topRef, Boolean(top));
  // Before the first measurement there is no height to budget against; assume room rather than flash closed.
  const room =
    stageHeight > 0
      ? budget(stageHeight, topHeight, hasDock, hasTray)
      : { panelMax: DOCK_PANEL_MAX, canOpen: true, trayMax: TRAY_MAX, topMax: 10_000 };

  const labels = panels.map((p, i) => (p.props as PanelProps).title ?? `${shelfLabel} ${i + 1}`);
  const activeIndex = Math.max(0, savedTab ? labels.indexOf(savedTab) : 0);
  const active = panels[activeIndex];
  const dockOpen = hasDock && open && room.canOpen;

  const onTabKey = (e: KeyboardEvent<HTMLDivElement>): void => {
    if (!['ArrowRight', 'ArrowLeft', 'Home', 'End'].includes(e.key)) return;
    e.preventDefault();
    const last = panels.length - 1;
    const next =
      e.key === 'Home' ? 0 : e.key === 'End' ? last : (activeIndex + (e.key === 'ArrowRight' ? 1 : -1) + panels.length) % panels.length;
    setSavedTab(labels[next]);
    document.getElementById(`${uid}-tab-${next}`)?.focus();
  };

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

      <div className="relative min-h-0 flex-1 overflow-hidden" style={{ minHeight: MAP_MIN_HEIGHT }}>
        <StageInsetsContext.Provider value={NO_INSETS}>{map}</StageInsetsContext.Provider>
      </div>

      {tray && (
        <div
          className={`shrink-0 overflow-y-auto border-t border-hair bg-panel ${FLAT}`}
          style={stageHeight > 0 ? { maxHeight: room.trayMax } : undefined}
        >
          {tray}
        </div>
      )}

      {hasDock && (
        <section className="shrink-0 border-t border-hair bg-panel" aria-label={shelfLabel}>
          <div className="flex items-stretch" style={{ height: DOCK_BAR_HEIGHT }}>
            <div role="tablist" aria-label={shelfLabel} className="flex min-w-0 flex-1 items-stretch overflow-x-auto" onKeyDown={onTabKey}>
              {panels.map((p, i) => {
                const selected = i === activeIndex;
                const props = p.props as PanelProps;
                return (
                  <button
                    key={labels[i]}
                    id={`${uid}-tab-${i}`}
                    type="button"
                    role="tab"
                    aria-selected={selected}
                    aria-controls={`${uid}-panel`}
                    tabIndex={selected ? 0 : -1}
                    onClick={() => {
                      setSavedTab(labels[i]);
                      if (!open && room.canOpen) setOpen(true);
                    }}
                    className={`flex shrink-0 items-center gap-2 whitespace-nowrap border-b-2 px-4 text-xs transition-colors ${
                      selected && dockOpen
                        ? 'border-accent font-semibold text-ink'
                        : 'border-transparent text-ink-3 hover:text-ink'
                    }`}
                  >
                    <span className="display text-[13px]">{labels[i]}</span>
                    {props.right}
                  </button>
                );
              })}
            </div>
            <button
              type="button"
              className="flex shrink-0 items-center gap-1 border-l border-hair px-3 text-2xs text-ink-3 hover:text-ink disabled:opacity-40"
              aria-expanded={dockOpen}
              aria-controls={`${uid}-panel`}
              disabled={!room.canOpen}
              title={room.canOpen ? undefined : 'Not enough window height to open the panels'}
              onClick={() => setOpen(!open)}
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
              style={{ maxHeight: room.panelMax }}
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
      )}
    </div>
  );
}
