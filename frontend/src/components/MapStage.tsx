/**
 * The map stage: the chart fills the whole area beside the navigation rail, and everything else
 * floats over it.
 *
 *   top     a command bar across the top edge (used by Plan)
 *   tray    a result card along the bottom edge (used by Plan)
 *   shelf   a row of instrument cards along the bottom edge, collapsible (used by the other views)
 *
 * Why this layout. The map is the product. Docking panels beside it, or stacking a results card
 * under it, spends a third of the screen on chrome and leaves the ocean cramped. Here the canvas
 * is always full-bleed and the instruments sit over its margins.
 *
 * The stage measures what it covers and publishes it (StageInsets), so the map can frame a route
 * inside the part that is actually visible and keep its own controls and scale bar clear.
 */
import { useCallback, useEffect, useMemo, useRef, useState, type ReactNode, type RefObject } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
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

/** The rendered height of an element, kept current as it resizes. Zero while it is absent. */
function useHeight(ref: RefObject<HTMLDivElement>, active: boolean): number {
  const [height, setHeight] = useState(0);
  useEffect(() => {
    const el = ref.current;
    if (!el || !active) {
      setHeight(0);
      return;
    }
    const read = (): void => setHeight(Math.round(el.getBoundingClientRect().height));
    read();
    const observer = new ResizeObserver(read);
    observer.observe(el);
    return () => observer.disconnect();
  }, [ref, active]);
  return height;
}

/** Short windows start with the instrument shelf closed, so the chart is not buried on first load. */
const roomForShelf = (): boolean => window.innerHeight >= 800;

const EDGE = 16; // distance of floating cards from the stage edge
const BREATH = 8; // extra clearance the map keeps beyond a card

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

export function MapStage({ id, map, top, tray, shelf, shelfLabel = 'Panels' }: Props): JSX.Element {
  const topRef = useRef<HTMLDivElement>(null);
  const bottomRef = useRef<HTMLDivElement>(null);
  const [shelfOpen, setShelfOpen] = usePersistentFlag(`iceflow.${id}.shelf`, roomForShelf);

  const topHeight = useHeight(topRef, Boolean(top));
  const bottomHeight = useHeight(bottomRef, Boolean(tray) || Boolean(shelf));

  const insets = useMemo<StageInsets>(
    () => ({
      left: 0,
      right: 0,
      top: topHeight > 0 ? topHeight + EDGE + BREATH : 0,
      bottom: bottomHeight > 0 ? bottomHeight + EDGE + BREATH : 0,
    }),
    [topHeight, bottomHeight],
  );

  return (
    <div className="relative h-full w-full overflow-hidden bg-ground">
      <StageInsetsContext.Provider value={insets}>
        <div className="absolute inset-0">{map}</div>

        {top && (
          <div ref={topRef} className="absolute inset-x-4 top-4 z-20">
            {top}
          </div>
        )}

        {(tray || shelf) && (
          <div ref={bottomRef} className="pointer-events-none absolute inset-x-4 bottom-4 z-20 flex flex-col gap-2">
            {tray}
            {shelf && (
              <>
                <button
                  type="button"
                  onClick={() => setShelfOpen(!shelfOpen)}
                  aria-expanded={shelfOpen}
                  className="btn pointer-events-auto self-start !rounded-full !py-1.5 pl-3.5 pr-3 shadow-card"
                >
                  {shelfLabel}
                  {shelfOpen ? <ChevronDown size={14} /> : <ChevronUp size={14} />}
                </button>
                {shelfOpen && (
                  <div className="pointer-events-auto flex h-[min(300px,36vh)] gap-3 overflow-x-auto pb-1 [&>*]:h-full [&>*]:w-[340px] [&>*]:shrink-0 [&>*]:overflow-y-auto">
                    {shelf}
                  </div>
                )}
              </>
            )}
          </div>
        )}
      </StageInsetsContext.Provider>
    </div>
  );
}
