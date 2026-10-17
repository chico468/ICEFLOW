/**
 * Plain-English explanations for the jargon.
 *
 * This system is full of terms that are second nature to an ice navigator and opaque to everyone
 * else: RIO, POLARIS, besetting, CPA, tenths, IIEE. A judge, a new team member or a first-time
 * user should not have to look any of them up. Every such term on screen is wrapped in
 * <Explain term="rio"> so it carries its own definition.
 *
 * The rule for writing these: say what it means and why it matters, in one or two sentences,
 * without using another piece of jargon to do it.
 */
import { useEffect, useRef, useState } from 'react';
import { createPortal } from 'react-dom';
import { HelpCircle } from 'lucide-react';

export interface Definition {
  title: string;
  short: string;
  detail?: string;
}

export const GLOSSARY: Record<string, Definition> = {
  rio: {
    title: 'RIO — Risk Index Outcome',
    short: 'A safety score for this ship in this ice. Higher is safer.',
    detail:
      'From the IMO Polar Code. At 0 or above the ship may proceed normally. Between 0 and -10 it ' +
      'must slow down and an ice navigator must agree. Below -10 the voyage is not permitted at ' +
      'all, and this system will not route you there.',
  },
  polaris: {
    title: 'POLARIS',
    short: 'The international rulebook for how much ice a given ship may safely enter.',
    detail:
      'Polar Operational Limit Assessment Risk Indexing System, IMO circular MSC.1/Circ.1519. It ' +
      'pairs a ship’s ice class against each type of ice to produce the RIO score.',
  },
  ice_class: {
    title: 'Ice class',
    short: 'How much ice a ship is built to handle. PC1 is the strongest, PC7 the weakest.',
    detail:
      'A PC7 hull is meant for thin first-year ice in summer. A PC4 can work thick first-year ice ' +
      'year round. It is a structural rating, not a measure of engine power, though both matter.',
  },
  besetting: {
    title: 'Besetting',
    short: 'Getting stuck: the ice closes around the hull and the ship cannot move.',
    detail:
      'The classic polar disaster. It happens when ice converges faster than the ship can make ' +
      'way. This system predicts it from the compression index and refuses to route through it.',
  },
  compression: {
    title: 'Compression',
    short: 'Whether the ice is being squeezed together (dangerous) or pulled apart (safe).',
    detail:
      'Computed from how the ice is drifting. Where floes converge, open leads close behind you ' +
      'and pressure builds against the hull. High compression is the warning sign before besetting.',
  },
  concentration: {
    title: 'Ice concentration',
    short: 'How much of the sea surface is covered by ice, counted in tenths.',
    detail: '0/10 is open water. 10/10 is complete cover with no navigable water between floes.',
  },
  thickness: {
    title: 'Ice thickness',
    short: 'How thick the ice is. This is what actually stops a ship.',
    detail:
      'Derived from how cold it has been and for how long, plus extra where ice is being ridged ' +
      'up by pressure. Satellites cannot measure it directly at useful resolution, so it is ' +
      'calculated rather than observed.',
  },
  attainable_speed: {
    title: 'Attainable speed',
    short: 'The speed this ship can actually make in this ice — an output, not a setting.',
    detail:
      'Solved from the ice resistance against the engine power and propeller thrust. If it comes ' +
      'out at zero, the ship is beset.',
  },
  lindqvist: {
    title: 'Lindqvist model',
    short: 'The physics of how much force ice exerts on a hull.',
    detail:
      'Lindqvist (1989). Adds up the force to crush ice at the bow, bend and break the sheet, and ' +
      'push the broken pieces under the hull. It is what turns "there is ice here" into "you will ' +
      'make 6 knots and burn 1 tonne an hour".',
  },
  cpa: {
    title: 'CPA — Closest Point of Approach',
    short: 'How near a hazard will come to you, and when.',
    detail:
      'Both you and the iceberg are moving, so this compares where each will be at the same ' +
      'moment, not where they are now.',
  },
  growler: {
    title: 'Growler',
    short: 'A small chunk of ice, barely above the water, big enough to hole a ship.',
    detail:
      'Too small for satellites to see and easily lost in radar sea clutter, which is exactly ' +
      'what makes it dangerous. Bergy bits are the next size up.',
  },
  baseline_route: {
    title: 'Ice-blind route',
    short: 'The route a ship would sail without any ice information — the thing we compare against.',
    detail:
      'It avoids land, because any captain would, but it knows nothing about ice. Both routes are ' +
      'then sailed through identical physics, so the difference between them is the real benefit.',
  },
  polynya: {
    title: 'Polynya',
    short: 'An area of open water surrounded by ice, held open by wind.',
    detail:
      'Near the Antarctic coast, katabatic winds blow ice away from the shore and expose water. ' +
      'They are useful shortcuts if you can reach them.',
  },
  iiee: {
    title: 'IIEE — Integrated Ice-Edge Error',
    short: 'How often the forecast disagrees with reality about where the ice edge is.',
    detail: 'Lower is better. It is the measure that matters most for deciding where to enter the pack.',
  },
  persistence: {
    title: 'Persistence baseline',
    short: 'The lazy forecast: assume tomorrow looks exactly like today.',
    detail:
      'Surprisingly hard to beat at short range. Any real forecast has to do better than this or ' +
      'it is adding nothing, which is why it is always shown alongside ours.',
  },
  synthetic: {
    title: 'Simulated data',
    short: 'The weather and ice fields here are modelled, not measured by satellites.',
    detail:
      'The physics, the safety rules and the coastline are real. The environmental fields stand ' +
      'in for live satellite products, and swapping them for the real thing is a data-loading ' +
      'change, not a redesign.',
  },
  rio_gauge: {
    title: 'Reading the risk gauge',
    short: 'Green is safe, amber means slow down, red means do not go.',
  },
};

/**
 * Wraps a label so it carries its own definition. Shown on hover and on click, because a touch
 * screen on a bridge console has no hover.
 */
export function Explain({
  term,
  children,
  className,
}: {
  term: keyof typeof GLOSSARY | string;
  children?: React.ReactNode;
  className?: string;
}): JSX.Element {
  const [open, setOpen] = useState(false);
  const [pos, setPos] = useState<{ left: number; top: number; above: boolean } | null>(null);
  const anchorRef = useRef<HTMLSpanElement>(null);
  const def = GLOSSARY[term];

  // The popup renders through a portal onto document.body rather than inline.
  //
  // These labels sit inside scrolling instrument rails with `overflow-y-auto`, and an absolutely
  // positioned child of a scrolling box is clipped by it: the tooltip would be sliced in half or
  // hidden entirely depending on where the panel happened to be scrolled. A portal escapes the
  // clip, and the position is measured from the trigger each time it opens.
  useEffect(() => {
    if (!open || !anchorRef.current) return;
    const rect = anchorRef.current.getBoundingClientRect();
    const WIDTH = 260;
    const MARGIN = 8;
    const left = Math.min(Math.max(MARGIN, rect.left), window.innerWidth - WIDTH - MARGIN);
    // Prefer above the label; drop below when there is not enough room up there.
    const above = rect.top > 190;
    setPos({ left, top: above ? rect.top - MARGIN : rect.bottom + MARGIN, above });
  }, [open]);

  useEffect(() => {
    if (!open) return;
    const close = (): void => setOpen(false);
    window.addEventListener('scroll', close, true);
    window.addEventListener('resize', close);
    return () => {
      window.removeEventListener('scroll', close, true);
      window.removeEventListener('resize', close);
    };
  }, [open]);

  if (!def) return <>{children}</>;

  return (
    <span
      ref={anchorRef}
      className={`inline-flex items-center gap-1 ${className ?? ''}`}
      onMouseEnter={() => setOpen(true)}
      onMouseLeave={() => setOpen(false)}
    >
      {children}
      <button
        type="button"
        aria-label={`What is ${def.title}?`}
        onClick={(e) => {
          e.stopPropagation();
          setOpen((v) => !v);
        }}
        className="text-ink-3 transition-colors hover:text-accent"
      >
        <HelpCircle size={11} />
      </button>
      {open &&
        pos &&
        createPortal(
          <div
            className="pointer-events-none fixed z-[100] w-[260px] rounded border border-hair-2 bg-panel-3 p-2 text-left shadow-2xl"
            style={{
              left: pos.left,
              top: pos.top,
              transform: pos.above ? 'translateY(-100%)' : undefined,
            }}
          >
            <div className="text-2xs font-semibold text-accent">
              {def.title}
            </div>
            <div className="mt-1 text-2xs leading-relaxed text-ink">{def.short}</div>
            {def.detail && (
              <div className="mt-1 text-2xs leading-relaxed text-ink-3">{def.detail}</div>
            )}
          </div>,
          document.body,
        )}
    </span>
  );
}
