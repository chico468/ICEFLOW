/**
 * The chart legend: what each coloured thing is, in what unit, and how far to trust it.
 *
 * Colours are not retyped here. The ice gradient is sampled from the same ramp function the canvas
 * paints with and the bands come from the same table, so a legend cannot say one thing while the map
 * shows another. Every layer that is on contributes a section; a layer that is loading, failed, or
 * showing the previous time says so, because an empty chart is not a statement that the sea is clear.
 */
import { useState } from 'react';
import { ChevronDown, ChevronUp } from 'lucide-react';
import type { IceField, ObservedIcebergsResponse } from '../api/types';
import type { MapScene } from '../map/MapEngine';
import { FLOW_KINDS } from '../map/flow';
import { countMissing, modeAvailability } from '../map/iceModes';
import { NO_DATA_FILL } from '../map/layers';
import { CHANGE_DEADBAND, ICE_BANDS, MAP_COLORS, bandCss, changeCss, concentrationCss, thicknessCss } from '../map/palette';

const KM_PER_DEG = 111.2;

function gradient(sampleFn: (t: number) => string, steps = 12): string {
  const stops: string[] = [];
  for (let i = 0; i <= steps; i += 1) stops.push(`${sampleFn(i / steps)} ${((i / steps) * 100).toFixed(1)}%`);
  return `linear-gradient(to right, ${stops.join(', ')})`;
}

export function cellSizeText(field: IceField): string | null {
  if (field.lats.length < 2 || field.lons.length < 2) return null;
  const dLat = Math.abs(field.lats[1] - field.lats[0]);
  const dLon = Math.abs(field.lons[1] - field.lons[0]);
  const midLat = field.lats[Math.floor(field.lats.length / 2)];
  const kmLat = dLat * KM_PER_DEG;
  const kmLon = dLon * KM_PER_DEG * Math.cos((midLat * Math.PI) / 180);
  return `${dLat.toFixed(2)}° × ${dLon.toFixed(2)}° (about ${kmLat.toFixed(0)} × ${kmLon.toFixed(0)} km)`;
}

export function formatObservedDate(iso: string | undefined): string {
  if (!iso) return 'unknown date';
  const d = new Date(`${iso}T00:00:00Z`);
  return Number.isNaN(d.getTime())
    ? iso
    : d.toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' });
}

export function observedSummary(o: ObservedIcebergsResponse): string {
  if (!o.available) return o.reason ?? 'Observed snapshot unavailable.';
  return `Observed ${formatObservedDate(o.observed_date)}, ${o.age_days} days old${o.stale ? ' (STALE)' : ''}`;
}

/**
 * One line saying what the chart is showing, for the collapsed legend. It carries the honesty flags
 * (simulated, stale) so the chip alone cannot be mistaken for a statement about live conditions.
 */
export function legendSummary(scene: MapScene, leadHours: number): string {
  const L = scene.layers;
  const parts: string[] = [];
  if (L.iceRaster) {
    const name =
      scene.rasterMode === 'thickness'
        ? 'Ice thickness'
        : scene.rasterMode === 'change'
          ? `Ice change +${leadHours} h`
          : scene.rasterMode === 'classes'
            ? 'Ice classes'
            : 'Ice concentration';
    parts.push(scene.iceField?.is_synthetic ? `${name} (simulated)` : name);
  }
  if (L.windFlow) parts.push('Wind (simulated)');
  if (L.currentFlow) parts.push('Current (simulated)');
  if (L.observedBergs && scene.observed?.available) parts.push(scene.observed.stale ? 'Observed bergs (stale)' : 'Observed bergs');
  if (L.icebergs) parts.push('Bergs (simulated)');
  return parts.join(' · ');
}

function coverageNote(f: { lats: number[]; lons: number[] }): string {
  const lat = (v: number): string => `${Math.abs(Math.round(v))} °${v < 0 ? 'S' : 'N'}`;
  const span = f.lons[f.lons.length - 1] - f.lons[0];
  return `${lat(f.lats[0])} to ${lat(f.lats[f.lats.length - 1])}, ${span >= 359 ? 'all longitudes' : `${Math.round(f.lons[0])}° to ${Math.round(f.lons[f.lons.length - 1])}°`}`;
}

export function MapLegend({
  scene,
  leadHours,
  defaultOpen = false,
}: {
  scene: MapScene;
  leadHours: number;
  /** Start expanded. The chart starts collapsed; this is for printing and screenshots. */
  defaultOpen?: boolean;
}): JSX.Element | null {
  const [open, setOpen] = useState(defaultOpen);
  const L = scene.layers;
  const st = scene.status;

  const showIce = L.iceRaster;
  const showFlow = L.windFlow || L.currentFlow;
  const showBergs = L.icebergs || L.observedBergs;
  if (!showIce && !showFlow && !showBergs) return null;

  return (
    <section
      className={`float absolute z-10 overflow-y-auto px-3 py-2 ${open ? 'w-[268px]' : 'max-w-[min(360px,60%)]'}`}
      style={{
        top: 12,
        left: 12,
        maxHeight: 'calc(100% - 24px)',
      }}
      aria-label="Chart legend"
    >
      <button
        type="button"
        className="flex w-full items-center justify-between gap-2 text-left"
        aria-expanded={open}
        title={open ? 'Collapse the legend' : 'Expand the legend'}
        onClick={() => setOpen((v) => !v)}
      >
        <span className="min-w-0">
          <span className="display block text-[13px] leading-tight text-ink">Legend</span>
          {!open && <span className="block truncate text-2xs text-ink-3">{legendSummary(scene, leadHours)}</span>}
        </span>
        {open ? <ChevronUp size={14} aria-hidden className="shrink-0" /> : <ChevronDown size={14} aria-hidden className="shrink-0" />}
      </button>

      {open && (
        <div className="mt-2 space-y-3 text-2xs text-ink-2">
          {showIce && <IceSection scene={scene} leadHours={leadHours} />}
          {showFlow && <FlowSection scene={scene} />}
          {showBergs && <BergSection scene={scene} />}
          {(st.iceError || st.flowError || st.observedError) && (
            <p role="alert" className="text-danger">
              Some layers failed to load. See the notes above; nothing missing here means "clear".
            </p>
          )}
        </div>
      )}
    </section>
  );
}

// ----------------------------------------------------------------------------------- sea ice

function IceSection({ scene, leadHours }: { scene: MapScene; leadHours: number }): JSX.Element {
  const { iceField: field, rasterMode: mode, status: st } = scene;
  const avail = modeAvailability(field, leadHours, {
    field: scene.iceFieldBase,
    loading: st.baseLoading,
    error: st.baseError,
  })[mode];
  // Only describe a colour scale the chart is actually painting. An unavailable mode shows why, not a legend.
  const drawn = avail.available;
  const classed = drawn && (mode === 'concentration' || mode === 'classes');
  const missing = countMissing(mode === 'thickness' ? field?.thickness_m : field?.concentration);

  let title = 'Sea-ice concentration';
  let unit = 'percent of each cell covered by ice';
  if (mode === 'thickness') {
    title = 'Sea-ice thickness';
    unit = 'metres';
  } else if (mode === 'change') {
    title = `Change in concentration, +${leadHours} h vs +0 h`;
    unit = 'percentage points';
  }

  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-medium text-ink">{title}</span>
        {field?.is_synthetic && <span className="rounded bg-panel-3 px-1.5 py-px text-[10px] text-ink-2">SIMULATED</span>}
      </div>
      <div className="mb-1 text-ink-3">{unit}</div>

      {field && !drawn && (
        <p role="status" className="my-1 rounded border border-hair-2 bg-panel-2 px-2 py-1.5 text-warn">
          {avail.reason} Nothing is drawn for this mode.
        </p>
      )}

      {classed && (
        <>
          <div
            className="h-3 rounded-sm border border-hair-2"
            style={{ background: gradient((t) => concentrationCss(t)) }}
            role="img"
            aria-label="Concentration from 0 to 100 percent, pale to deep blue"
          />
          <div className="relative mb-1 mt-0.5 h-3 num text-[10px] text-ink-3">
            {[0, 15, 40, 70, 90, 100].map((p) => (
              <span
                key={p}
                className="absolute -translate-x-1/2"
                style={{ left: `${p}%`, transform: p === 0 ? 'none' : p === 100 ? 'translateX(-100%)' : undefined }}
              >
                {p}
              </span>
            ))}
          </div>
          <ul className="mt-1 space-y-0.5">
            {ICE_BANDS.map((b) => (
              <li key={b.key} className="flex items-center gap-1.5">
                <span className="inline-block h-2.5 w-4 shrink-0 rounded-sm border border-hair-2" style={{ background: bandCss(b) }} />
                <span className="flex-1 truncate">{b.label}</span>
                <span className="num text-ink-3">
                  {Math.round(b.from * 100)}–{Math.min(100, Math.round(b.to * 100))}%
                </span>
              </li>
            ))}
          </ul>
          <p className="mt-1 text-ink-3">
            The 15 % boundary is the ice-edge threshold this model uses. Bands are display classes, not an official
            ice-chart code.
          </p>
        </>
      )}

      {drawn && mode === 'thickness' && (
        <>
          <div className="h-3 rounded-sm border border-hair-2" style={{ background: gradient((t) => thicknessCss(t * 3)) }} />
          <div className="mt-0.5 flex justify-between num text-[10px] text-ink-3">
            <span>0</span>
            <span>1</span>
            <span>2</span>
            <span>3 m</span>
          </div>
        </>
      )}

      {drawn && mode === 'change' && (
        <>
          <div
            className="h-3 rounded-sm border border-hair-2"
            style={{
              background: `linear-gradient(to right, ${changeCss(-0.5)}, rgba(255,255,255,0) 45%, rgba(255,255,255,0) 55%, ${changeCss(0.5)})`,
            }}
          />
          <div className="mt-0.5 flex justify-between num text-[10px] text-ink-3">
            <span>−50 (retreat)</span>
            <span>0</span>
            <span>+50 (advance)</span>
          </div>
          <p className="mt-1 text-ink-3">
            Changes smaller than {Math.round(CHANGE_DEADBAND * 100)} points are left unpainted so model noise is not drawn.
          </p>
          <p className="mt-1 text-ink-3">
            Indigo: more ice at +{leadHours} h than at +0 h. Teal: less. Both fields are the same simulation, so this
            is the model's own change, not an observed one.
          </p>
        </>
      )}

      {drawn && missing.missing > 0 && (
        <div className="mt-1.5 flex items-center gap-1.5">
          <span className="inline-block h-2.5 w-4 shrink-0 rounded-sm border border-hair-2" style={{ background: NO_DATA_FILL }} aria-hidden />
          <span>
            No data: {missing.missing.toLocaleString('en-GB')} of {missing.total.toLocaleString('en-GB')} cells. Not zero ice.
          </span>
        </div>
      )}

      <div className="mt-1.5 flex items-center gap-1.5">
        <span className="inline-block h-0.5 w-4 bg-[#1B6A9C] outline outline-2 outline-white/80" aria-hidden />
        <span>Ice edge (15 % contour, per longitude)</span>
      </div>

      {field && (
        <div className="mt-1 text-ink-3">
          <div>Valid +{field.lead_hours} h of the model run.</div>
          {cellSizeText(field) && (
            <div>
              Grid cell {cellSizeText(field)}. Each cell is a single value: detail finer than this is not in the data.
            </div>
          )}
        </div>
      )}
      {field?.is_synthetic && (
        <p className="mt-1 text-ink-3">Model output, not satellite observation. Do not read it as the real ice edge.</p>
      )}

      {st.iceLoading && !field && <p className="mt-1 text-ink-3">Loading the ice field…</p>}
      {st.iceUpdating && field && (
        <p role="status" className="mt-1 text-warn">
          Showing the previous forecast time while +{leadHours} h loads.
        </p>
      )}
      {st.iceError && (
        <p role="alert" className="mt-1 text-danger">
          Ice field unavailable: {st.iceError}. A blank chart here is NOT open water.
        </p>
      )}
      {!st.iceLoading && !st.iceError && !field && (
        <p className="mt-1 text-warn">No ice data for this view. That is a missing layer, not clear water.</p>
      )}
    </div>
  );
}

// ---------------------------------------------------------------------------------------- flow

function FlowSection({ scene }: { scene: MapScene }): JSX.Element {
  const { envField: f, status: st, layers: L } = scene;
  const kinds = [L.windFlow && FLOW_KINDS.wind, L.currentFlow && FLOW_KINDS.current].filter(Boolean) as (typeof FLOW_KINDS)['wind'][];
  return (
    <div>
      <div className="mb-1 flex items-baseline justify-between">
        <span className="font-medium text-ink">Flow</span>
        {f?.is_synthetic && <span className="rounded bg-panel-3 px-1.5 py-px text-[10px] text-ink-2">SIMULATED</span>}
      </div>
      {kinds.map((k) => (
        <div key={k.kind} className="mb-1.5">
          <div className="flex justify-between">
            <span>{k.label}</span>
            <span className="num text-ink-3">0 – {k.maxSpeed} m/s</span>
          </div>
          <div
            className="h-2.5 rounded-sm border border-hair-2"
            style={{ background: `linear-gradient(to right, ${k.ramp.map((c) => `rgb(${c.join(',')})`).join(', ')})` }}
            role="img"
            aria-label={`${k.label} speed, light is slow and dark is fast`}
          />
        </div>
      ))}
      <p className="text-ink-3">
        Direction is where the {L.windFlow && L.currentFlow ? 'wind blows and the water flows' : L.windFlow ? 'wind blows' : 'water flows'}.
        Colour is the true speed. Particle speed and arrow length are a visual aid, scaled differently for wind and
        current, and are not a real-time drift. Arrows are longer where the flow is faster; wind arrows have an open
        head and current arrows a solid one.
      </p>
      {f && (
        <p className="mt-1 text-ink-3">
          Model hour +{f.valid_time_hours}. {f.source ?? ''}
        </p>
      )}
      {st.flowLoading && !f && <p className="mt-1 text-ink-3">Loading wind and current…</p>}
      {st.flowError && (
        <p role="alert" className="mt-1 text-danger">
          Flow data unavailable: {st.flowError}. Nothing is animated.
        </p>
      )}
      <p className="mt-1 text-ink-3">
        Field covers {f ? coverageNote(f) : '78 °S to 28 °S, all longitudes'}. Not shown north of that: the
        simulated fields have no continental land mask.
      </p>
      {L.currentFlow && (
        <p className="mt-1 text-ink-3">
          The simulated current changes direction sharply between neighbouring cells, so its pattern looks
          irregular. That is the data, not a drawing fault. The simulated fields also do not match across
          the 180° meridian, so flow stops there.
        </p>
      )}
    </div>
  );
}

// --------------------------------------------------------------------------------------- bergs

function BergSection({ scene }: { scene: MapScene }): JSX.Element {
  const { layers: L, observed: o, status: st } = scene;
  return (
    <div>
      <div className="mb-1 font-medium text-ink">Icebergs</div>
      {L.icebergs && (
        <div className="mb-1 flex items-start gap-1.5">
          <span
            className="mt-0.5 inline-block h-3 w-3 shrink-0 rounded-full border"
            style={{ borderColor: MAP_COLORS.iceberg, background: 'rgba(91,63,209,0.18)' }}
            aria-hidden
          />
          <span>
            <span className="text-ink">Simulated catalogue.</span> Positions are seeded and drifted by the model: not
            observations.
          </span>
        </div>
      )}
      {L.observedBergs && (
        <div className="flex items-start gap-1.5">
          <svg width="12" height="12" viewBox="0 0 12 12" className="mt-0.5 shrink-0" aria-hidden>
            <path
              d="M6 1 L11 6 L6 11 L1 6 Z"
              fill="none"
              stroke={o?.stale ? MAP_COLORS.observedBergStale : MAP_COLORS.observedBerg}
              strokeWidth="1.4"
            />
          </svg>
          <span>
            <span className="text-ink">Observed snapshot (USNIC-format).</span>{' '}
            {o ? (
              <>
                <span className={o.stale ? 'font-medium text-warn' : ''}>{observedSummary(o)}.</span>{' '}
                {o.available && 'Not where the bergs are now; not used by the route planner. Circles show equivalent area; orientation unknown.'}
              </>
            ) : st.observedError ? (
              <span className="text-danger">Unavailable: {st.observedError}.</span>
            ) : (
              <span className="text-ink-3">Loading…</span>
            )}
          </span>
        </div>
      )}
    </div>
  );
}
