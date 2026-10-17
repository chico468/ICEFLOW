/**
 * The ICEFLOW interface kit: cards, readouts, gauges, form controls and the long-running-task
 * overlay. Small, typed, and shared by every screen.
 *
 * Design rules encoded here, so screens do not have to remember them:
 *  - A Panel is an instrument card: white on the paper background, ruled, with a contact shadow.
 *  - Section titles and headline figures use the display serif; everything else is the sans.
 *  - Text is shown in sentence case. Nothing is upper-cased or letter-spaced for effect.
 *  - Colour is never the only signal: status always carries a word.
 *
 * The wording of every label, hint and message here is unchanged from the original console.
 */
import type { ReactNode } from 'react';
import { AlertTriangle, ChevronDown, Loader2 } from 'lucide-react';
import { rioColor, rioStatusLabel } from '../map/palette';
import { clamp } from '../lib/format';

// ------------------------------------------------------------------------------- panel

export function Panel({
  title,
  subtitle,
  right,
  children,
  className,
  bodyClassName,
}: {
  title?: string;
  subtitle?: string;
  right?: ReactNode;
  children: ReactNode;
  className?: string;
  bodyClassName?: string;
}): JSX.Element {
  return (
    <section className={`panel flex min-h-0 flex-col ${className ?? ''}`}>
      {title && (
        <header className="panel-head shrink-0">
          <div className="flex min-w-0 items-baseline gap-2">
            <h2 className="display truncate text-[15px] text-ink">{title}</h2>
            {subtitle && <span className="truncate text-2xs text-ink-3">{subtitle}</span>}
          </div>
          {right}
        </header>
      )}
      <div className={`min-h-0 flex-1 ${bodyClassName ?? 'p-4'}`}>{children}</div>
    </section>
  );
}

// ----------------------------------------------------------------------------- readout

export function Stat({
  label,
  value,
  unit,
  tone = 'default',
  hint,
  size = 'md',
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: 'default' | 'accent' | 'ok' | 'caution' | 'danger' | 'muted';
  hint?: string;
  size?: 'sm' | 'md' | 'lg';
}): JSX.Element {
  const toneClass = {
    default: 'text-ink',
    accent: 'text-accent',
    ok: 'text-ok',
    caution: 'text-caution',
    danger: 'text-danger',
    muted: 'text-ink-2',
  }[tone];
  const sizeClass = { sm: 'text-base', md: 'text-xl', lg: 'text-[28px]' }[size];
  return (
    <div className="min-w-0" title={hint}>
      <div className="truncate text-2xs text-ink-3">{label}</div>
      <div className={`num flex items-baseline gap-1 leading-tight ${sizeClass} ${toneClass}`}>
        <span className="display truncate">{value}</span>
        {unit && <span className="text-2xs text-ink-3">{unit}</span>}
      </div>
    </div>
  );
}

export function KeyValue({
  label,
  value,
  unit,
  tone,
}: {
  label: string;
  value: string;
  unit?: string;
  tone?: string;
}): JSX.Element {
  return (
    <div className="flex items-baseline justify-between gap-3 border-b border-hair/60 py-1.5 last:border-0">
      <span className="truncate text-2xs text-ink-3">{label}</span>
      <span className="num shrink-0 text-xs" style={tone ? { color: tone } : undefined}>
        {value}
        {unit && <span className="ml-1 text-2xs text-ink-3">{unit}</span>}
      </span>
    </div>
  );
}

export function Badge({
  children,
  tone = 'neutral',
  title,
}: {
  children: ReactNode;
  tone?: 'neutral' | 'accent' | 'ok' | 'caution' | 'danger' | 'violet';
  title?: string;
}): JSX.Element {
  const cls = {
    neutral: 'border-hair-2 text-ink-2 bg-panel-2',
    accent: 'border-accent/40 text-accent bg-accent/10',
    ok: 'border-ok/40 text-ok bg-ok/10',
    caution: 'border-caution/40 text-caution bg-caution/10',
    danger: 'border-danger/40 text-danger bg-danger/10',
    violet: 'border-violet/40 text-violet bg-violet/10',
  }[tone];
  return (
    <span className={`chip ${cls}`} title={title}>
      {children}
    </span>
  );
}

// -------------------------------------------------------------------------- RIO gauge

/**
 * The Risk Index Outcome, drawn against the POLARIS decision boundaries.
 * The scale runs from the prohibited floor (-10 and below) to the open-water ceiling
 * this matrix produces (+30 for ten tenths of ice-free water at RV 3).
 */
export function RioGauge({ rio, cap }: { rio: number; cap?: number }): JSX.Element {
  const MIN = -30;
  const MAX = 30;
  const t = clamp((rio - MIN) / (MAX - MIN), 0, 1);
  const zero = (0 - MIN) / (MAX - MIN);
  const prohibited = (-10 - MIN) / (MAX - MIN);
  const color = rioColor(rio);
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-2xs text-ink-3">POLARIS RIO</span>
        <span className="num display text-xl leading-none" style={{ color }}>
          {rio > 0 ? `+${rio}` : rio}
        </span>
      </div>
      <div className="relative mt-2 h-2.5 overflow-hidden rounded-full bg-panel-2">
        <div className="absolute inset-y-0 left-0 bg-danger/25" style={{ width: `${prohibited * 100}%` }} />
        <div
          className="absolute inset-y-0 bg-caution/25"
          style={{ left: `${prohibited * 100}%`, width: `${(zero - prohibited) * 100}%` }}
        />
        <div className="absolute inset-y-0 bg-ok/20" style={{ left: `${zero * 100}%`, right: 0 }} />
        <div className="absolute inset-y-0 w-[3px] rounded-full" style={{ left: `${t * 100}%`, background: color }} />
      </div>
      <div className="mt-1.5 flex items-center justify-between">
        <span className="text-2xs" style={{ color }}>
          {rioStatusLabel(rio)}
        </span>
        {cap !== undefined && (
          <span className="num text-2xs text-ink-3">
            cap {cap.toFixed(1)} <span className="text-ink-3">kn</span>
          </span>
        )}
      </div>
    </div>
  );
}

// ------------------------------------------------------------------------------- meter

export function Meter({
  label,
  value01,
  display,
  color = '#0B5C8E',
  warnAbove,
}: {
  label: string;
  value01: number;
  display: string;
  color?: string;
  warnAbove?: number;
}): JSX.Element {
  const v = clamp(value01, 0, 1);
  const hot = warnAbove !== undefined && v >= warnAbove;
  return (
    <div>
      <div className="flex items-baseline justify-between">
        <span className="text-2xs text-ink-3">{label}</span>
        <span className="num text-xs" style={{ color: hot ? '#B45309' : color }}>
          {display}
        </span>
      </div>
      <div className="mt-1.5 h-2 overflow-hidden rounded-full bg-panel-2">
        <div
          className="h-full rounded-full transition-[width] duration-300"
          style={{ width: `${v * 100}%`, background: hot ? '#B45309' : color }}
        />
      </div>
    </div>
  );
}

// ---------------------------------------------------------------- form controls

export function Slider({
  label,
  value,
  min,
  max,
  step,
  onChange,
  display,
  disabled,
}: {
  label: string;
  value: number;
  min: number;
  max: number;
  step: number;
  onChange: (v: number) => void;
  display: string;
  disabled?: boolean;
}): JSX.Element {
  return (
    <label className="block">
      <div className="mb-1.5 flex items-baseline justify-between">
        <span className="text-2xs text-ink-2">{label}</span>
        <span className="num text-xs text-ink">{display}</span>
      </div>
      <input
        type="range"
        className="w-full"
        min={min}
        max={max}
        step={step}
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(Number(e.target.value))}
      />
    </label>
  );
}

export function Select<T extends string>({
  label,
  value,
  options,
  onChange,
  disabled,
}: {
  label: string;
  value: T;
  options: { value: T; label: string }[];
  onChange: (v: T) => void;
  disabled?: boolean;
}): JSX.Element {
  return (
    <label className="block min-w-0">
      <div className="mb-1 text-2xs text-ink-2">{label}</div>
      <select
        className="field"
        value={value}
        disabled={disabled}
        onChange={(e) => onChange(e.target.value as T)}
      >
        {options.map((o) => (
          <option key={o.value} value={o.value}>
            {o.label}
          </option>
        ))}
      </select>
    </label>
  );
}

/** An on/off switch. The hint is the tooltip, exactly as before. */
export function Toggle({
  label,
  checked,
  onChange,
  hint,
}: {
  label: string;
  checked: boolean;
  onChange: (v: boolean) => void;
  hint?: string;
}): JSX.Element {
  return (
    <button
      type="button"
      role="switch"
      aria-checked={checked}
      onClick={() => onChange(!checked)}
      title={hint}
      className="flex w-full items-center gap-2.5 rounded-lg px-1.5 py-1 text-left text-xs text-ink-2 transition-colors hover:bg-panel-2"
    >
      <span
        className={`flex h-5 w-9 shrink-0 items-center rounded-full border px-0.5 transition-colors ${
          checked ? 'border-accent bg-accent' : 'border-hair-2 bg-panel-3'
        }`}
        aria-hidden
      >
        <span
          className={`block h-3.5 w-3.5 rounded-full transition-transform ${
            checked ? 'translate-x-4 bg-panel' : 'translate-x-0 bg-ink-3'
          }`}
        />
      </span>
      <span className="truncate">{label}</span>
    </button>
  );
}

/** A native <details> disclosure, so it is keyboard-operable with no script. */
export function Disclosure({
  title,
  children,
  defaultOpen = false,
}: {
  title: string;
  children: ReactNode;
  defaultOpen?: boolean;
}): JSX.Element {
  return (
    <details className="group" open={defaultOpen}>
      <summary className="flex cursor-pointer list-none items-center justify-between rounded-lg py-1.5 text-xs text-ink-2 transition-colors hover:text-accent [&::-webkit-details-marker]:hidden">
        <span>{title}</span>
        <ChevronDown size={15} className="transition-transform group-open:rotate-180" />
      </summary>
      <div className="pt-2">{children}</div>
    </details>
  );
}

// -------------------------------------------------------------------- loading overlay

/**
 * Long calls (route optimisation and voyage creation both run 15 to 25 seconds) must
 * never show a frozen screen. This states what is being computed and keeps a live
 * elapsed clock, so it is obvious the system is working rather than hung.
 */
export function ComputeOverlay({
  title,
  steps,
  elapsedMs,
  expectedMs = 20_000,
}: {
  title: string;
  steps: string[];
  elapsedMs: number;
  expectedMs?: number;
}): JSX.Element {
  const progress = clamp(elapsedMs / expectedMs, 0, 0.97);
  const activeStep = Math.min(steps.length - 1, Math.floor(progress * steps.length));
  return (
    <div
      className="absolute inset-0 z-30 flex items-center justify-center bg-ground/70 backdrop-blur-sm"
      role="status"
      aria-live="polite"
    >
      <div className="float w-[420px] max-w-[92%] p-5">
        <div className="flex items-center gap-2 text-accent">
          <Loader2 size={15} className="animate-spin" />
          <span className="display text-base">{title}</span>
        </div>
        <div className="mt-3 h-1.5 overflow-hidden rounded-full bg-panel-3">
          <div
            className="h-full rounded-full bg-accent transition-[width] duration-200"
            style={{ width: `${progress * 100}%` }}
          />
        </div>
        <ul className="mt-3 space-y-1.5">
          {steps.map((s, i) => (
            <li
              key={s}
              className={`flex items-start gap-2 text-2xs ${
                i < activeStep ? 'text-ink-3 line-through' : i === activeStep ? 'text-ink' : 'text-ink-3/70'
              }`}
            >
              <span className="mt-[5px] block h-1 w-1 shrink-0 rounded-full bg-current" />
              <span>{s}</span>
            </li>
          ))}
        </ul>
        <div className="num mt-3 flex items-baseline justify-between text-2xs text-ink-3">
          <span>{(elapsedMs / 1000).toFixed(1)} s elapsed</span>
          <span>typically 15 to 25 s</span>
        </div>
      </div>
    </div>
  );
}

export function ErrorNote({ message, onRetry }: { message: string; onRetry?: () => void }): JSX.Element {
  return (
    <div
      role="alert"
      className="flex items-start gap-2 rounded-lg border border-danger/40 bg-danger/10 p-2.5 text-xs text-danger"
    >
      <AlertTriangle size={14} className="mt-0.5 shrink-0" />
      <div className="min-w-0 flex-1">
        <div className="break-words">{message}</div>
        {onRetry && (
          <button className="btn mt-2 !border-danger/40 !text-danger" onClick={onRetry}>
            Retry
          </button>
        )}
      </div>
    </div>
  );
}

export function Spinner({ label }: { label: string }): JSX.Element {
  return (
    <div className="flex items-center gap-2 text-2xs text-ink-3">
      <Loader2 size={14} className="animate-spin" />
      {label}
    </div>
  );
}

export function EmptyState({ title, detail }: { title: string; detail: string }): JSX.Element {
  return (
    <div className="flex h-full flex-col items-center justify-center gap-1.5 p-6 text-center">
      <div className="display text-[15px] text-ink-2">{title}</div>
      <div className="max-w-sm text-xs leading-relaxed text-ink-3">{detail}</div>
    </div>
  );
}
