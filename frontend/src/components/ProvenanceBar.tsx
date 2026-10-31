/**
 * The honesty notice, principle P2.
 *
 * Nothing here is hardcoded. It reads /api/v1/health's `data_provenance` block and sorts whatever
 * it finds into what is real and what is a simulated stand-in, so if the backend ever swaps a
 * synthetic field for a live feed this notice changes without a code edit.
 *
 * It lives in the masthead as a single pill. The detail opens as an absolutely-positioned card
 * with a bounded height and its own scroll, so the masthead is exactly one line tall whether the
 * detail is open or shut (an earlier inline version once pushed the whole application below the fold).
 *
 * The wording is unchanged from the original console; only the presentation is new.
 */
import { useEffect, useRef, useState } from 'react';
import { ChevronDown, CircleCheck, FlaskConical, ShieldOff, WifiOff, X } from 'lucide-react';
import { useHealth } from '../api/queries';
import type { Provenance } from '../api/types';

function prettyKey(key: string): string {
  return key.replace(/_/g, ' ').replace(/\b\w/g, (c) => c.toUpperCase());
}

export function ProvenanceBar(): JSX.Element {
  const { data, isLoading, isError } = useHealth();
  const [open, setOpen] = useState(false);
  const rootRef = useRef<HTMLDivElement>(null);

  // Close on Escape or on a click outside, the way any popover should behave.
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent): void => {
      if (e.key === 'Escape') setOpen(false);
    };
    const onClick = (e: MouseEvent): void => {
      if (rootRef.current && !rootRef.current.contains(e.target as Node)) setOpen(false);
    };
    window.addEventListener('keydown', onKey);
    window.addEventListener('mousedown', onClick);
    return () => {
      window.removeEventListener('keydown', onKey);
      window.removeEventListener('mousedown', onClick);
    };
  }, [open]);

  if (isError) {
    return (
      <div
        role="alert"
        className="flex min-w-0 items-center gap-2 rounded-full border border-danger/40 bg-danger/10 px-3 py-1.5 text-2xs text-danger"
      >
        <ShieldOff size={13} className="shrink-0" />
        <span className="truncate">
          Backend unreachable. Start it with{' '}
          <code className="num rounded bg-panel px-1">uvicorn src.api.main:app --port 8000</code>
        </span>
      </div>
    );
  }

  const entries: [string, Provenance][] = data ? Object.entries(data.data_provenance) : [];
  const simulated = entries.filter(([, p]) => p.status === 'synthetic');
  // 'real-seed' means real names and origins with positions the authors seeded: NOT observations. It must not
  // share a heading with genuinely real data, so it gets its own group.
  const seeded = entries.filter(([, p]) => p.status === 'real-seed');
  const real = entries.filter(
    ([, p]) => p.status !== 'synthetic' && p.status !== 'real-seed',
  );

  function ageText(p: Provenance): string {
    if (p.age_days === null || p.age_days === undefined) return 'age unknown';
    return `${Number(p.age_days).toFixed(0)} d old`;
  }

  function validText(p: Provenance): string {
    return p.observed_date ?? 'observed date unknown';
  }

  return (
    <div ref={rootRef} className="relative z-40 min-w-0">
      <button
        type="button"
        onClick={() => setOpen((v) => !v)}
        aria-expanded={open}
        className="flex max-w-full items-center gap-2 rounded-full border border-caution/40 bg-caution/10 px-3.5 py-1.5 text-left text-2xs text-caution transition-colors hover:bg-caution/[0.16]"
      >
        <FlaskConical size={14} className="shrink-0" />
        <span className="min-w-0 truncate">
          {isLoading ? (
            'Reading data provenance…'
          ) : (
            <>
              <span className="font-semibold">Weather and ice are simulated</span>
              <span className="hidden text-caution/80 2xl:inline">
                {' '}
                &mdash; the physics, safety tables and coastline are real
              </span>
            </>
          )}
        </span>
        {data && (
          <span className="hidden shrink-0 items-center gap-1 text-ok xl:flex">
            <WifiOff size={12} />
            offline capable
          </span>
        )}
        <span className="shrink-0 text-caution/80">{open ? 'hide' : 'details'}</span>
        <ChevronDown size={13} className={`shrink-0 transition-transform ${open ? 'rotate-180' : ''}`} />
      </button>

      {open && data && (
        <div className="float absolute right-0 top-full mt-3 max-h-[min(70vh,560px)] w-[min(780px,94vw)] overflow-y-auto">
          <div className="flex items-start gap-3 px-5 py-4">
            <p className="flex-1 text-xs leading-relaxed text-ink-2">
              This system models the world rather than observing it. The environmental fields below
              are stand-ins for live satellite products; everything else is the real thing. Any
              skill figure you see is therefore measured inside a simulated environment, and moving
              to live data is a data-loading change rather than a redesign.
            </p>
            <button
              type="button"
              aria-label="Close"
              onClick={() => setOpen(false)}
              className="shrink-0 rounded-lg p-1 text-ink-3 transition-colors hover:text-ink"
            >
              <X size={16} />
            </button>
          </div>

          <div className="grid gap-5 px-5 pb-5 lg:grid-cols-2">
            <div>
              <div className="display mb-2 flex items-center gap-1.5 text-[14px] text-caution">
                <FlaskConical size={14} /> Simulated ({simulated.length})
              </div>
              <ul className="space-y-2">
                {simulated.map(([key, p]) => (
                  <li key={key} className="rounded-lg border border-caution/30 bg-caution/[0.06] p-2.5">
                    <div className="text-xs font-semibold text-caution">{prettyKey(key)}</div>
                    <div className="mt-0.5 text-2xs leading-relaxed text-ink-3">
                      Stands in for{' '}
                      <span className="text-ink-2">{p.source.replace(/^stands in for /, '')}</span>
                      {p.note ? ` · ${p.note}` : ''}. {ageText(p)}.
                    </div>
                  </li>
                ))}
              </ul>
            </div>

            {seeded.length > 0 && (
              <div>
                <div className="display mb-2 flex items-center gap-1.5 text-[14px] text-caution">
                  <FlaskConical size={14} /> Seeded from real names, not observed ({seeded.length})
                </div>
                <ul className="space-y-2">
                  {seeded.map(([key, p]) => (
                    <li key={key} className="rounded-lg border border-caution/30 bg-caution/[0.06] p-2.5">
                      <div className="text-xs font-semibold text-caution">{prettyKey(key)}</div>
                      <div className="mt-0.5 text-2xs leading-relaxed text-ink-3">
                        <span className="text-ink-2">{p.source}</span>
                        {p.note ? ` · ${p.note}` : ''}. {ageText(p)}.
                      </div>
                    </li>
                  ))}
                </ul>
              </div>
            )}

            <div>
              <div className="display mb-2 flex items-center gap-1.5 text-[14px] text-ok">
                <CircleCheck size={14} /> Real ({real.length})
              </div>
              <ul className="space-y-2">
                {real.map(([key, p]) => (
                  <li key={key} className="rounded-lg border border-ok/30 bg-ok/[0.06] p-2.5">
                    <div className="text-xs font-semibold text-ok">{prettyKey(key)}</div>
                      <div className="mt-0.5 text-2xs leading-relaxed text-ink-3">
                        <span className="text-ink-2">{p.source}</span>
                        {p.note ? ` · ${p.note}` : ''}. {ageText(p)} · {validText(p)}.
                      </div>
                  </li>
                ))}
              </ul>
            </div>
          </div>
        </div>
      )}
    </div>
  );
}

/** A compact inline version for panels that render a specific synthetic product. */
export function SyntheticChip({
  isSynthetic,
  source,
  className,
}: {
  isSynthetic: boolean | undefined;
  source: string | undefined;
  className?: string;
}): JSX.Element | null {
  if (isSynthetic === undefined) return null;
  if (!isSynthetic) {
    return (
      <span className={`chip border-ok/40 bg-ok/10 text-ok ${className ?? ''}`} title={source}>
        <CircleCheck size={12} /> real
      </span>
    );
  }
  return (
    <span
      className={`chip border-caution/40 bg-caution/10 text-caution ${className ?? ''}`}
      title={source ? `Simulated. ${source}` : 'Simulated field'}
    >
      <FlaskConical size={12} /> simulated
    </span>
  );
}
