/**
 * A compact inline badge that says where a piece of data came from.
 *
 * Principle P2: nothing here is hardcoded. The badge renders from a typed
 * Provenance record (status, source, note, observed_date, age_days) and derives
 * its label, tone and icon from `status` alone, so no per-layer text is baked in.
 *
 * Statuses: observed (real / real-observation), reanalysis, forecast, derived,
 * simulated (synthetic), real-seed, plus any unknown string passed through as-is.
 *   observed        -> Observed
 *   reanalysis      -> Reanalysis
 *   forecast        -> Forecast
 *   derived         -> Derived
 *   simulated       -> Simulated
 *   real-seed       -> Real catalogue (drift modelled)
 *
 * Used inline with layer labels and controls, where a full ProvenanceBar
 * popover would be too heavy.
 */
import { Cloud, Database, FlaskConical, Globe, Satellite } from 'lucide-react';
import type { Provenance } from '../api/types';

export type ProvenanceStatus = Provenance['status'];

const KIND_LABELS: Record<string, string> = {
  real: 'Observed',
  'real-observation': 'Observed',
  reanalysis: 'Reanalysis',
  forecast: 'Forecast',
  derived: 'Derived',
  synthetic: 'Simulated',
  'real-seed': 'Real catalogue (drift modelled)',
  'experimental_ml': 'Experimental ML',
};

function provenanceLabel(status: ProvenanceStatus): string {
  return KIND_LABELS[status] ?? status.split(/[_-]+/).map((part) => part.slice(0, 1).toUpperCase() + part.slice(1)).join(' ');
}

const KIND_TONES: Record<string, 'ok' | 'caution' | 'accent' | 'neutral'> = {
  real: 'ok',
  'real-observation': 'ok',
  reanalysis: 'accent',
  forecast: 'accent',
  derived: 'accent',
  synthetic: 'caution',
  'real-seed': 'neutral',
};

const KIND_ICONS: Record<string, React.ElementType> = {
  real: Satellite,
  'real-observation': Satellite,
  reanalysis: Globe,
  forecast: Globe,
  derived: Cloud,
  synthetic: FlaskConical,
  'real-seed': Database,
};

const SIZE_CLASSES = {
  sm: 'px-1 py-0.5 text-[8px]',
  md: 'px-1.5 py-0.5 text-[9px]',
  lg: 'px-2 py-1 text-[10px]',
};

const TONE_CLASSES = {
  ok: 'border-ok/40 bg-ok/10 text-ok',
  caution: 'border-caution/40 bg-caution/10 text-caution',
  accent: 'border-accent/40 bg-accent/10 text-accent',
  neutral: 'border-hair-2 text-ink-2 bg-panel-2',
};

export function provenanceStatusLabel(provenance: Provenance): string {
  return provenanceLabel(provenance.status);
}

export function ProvenanceBadge({
  provenance,
  className,
  title,
  showAge = true,
  showIcon = true,
  size = 'md',
}: {
  /** Full Provenance record; the label, tone and icon come from its status. */
  provenance: Provenance;
  className?: string;
  /** Optional tooltip override; defaults to provenance-derived title. */
  title?: string;
  /** Append the age (days) to the visible label. */
  showAge?: boolean;
  showIcon?: boolean;
  size?: 'sm' | 'md' | 'lg';
}): JSX.Element {
  const label = provenanceLabel(provenance.status);
  const tone = KIND_TONES[provenance.status] ?? 'neutral';
  const Icon = KIND_ICONS[provenance.status] ?? Globe;
  const sizeClass = SIZE_CLASSES[size];
  const toneClass = TONE_CLASSES[tone];

  const parts: string[] = [provenance.source];
  if (provenance.note) parts.push(provenance.note);
  if (provenance.observed_date) parts.push(`observed ${provenance.observed_date}`);
  if (showAge && provenance.age_days !== null && provenance.age_days !== undefined) {
    parts.push(`${Number(provenance.age_days).toFixed(0)} d old`);
  }
  const badgeTitle = title ?? parts.join(' · ');

  return (
    <span
      className={`inline-flex items-center gap-0.5 rounded ${sizeClass} font-medium ${toneClass} ${className ?? ''}`}
      title={badgeTitle}
    >
      {showIcon && (
        <Icon
          size={size === 'sm' ? 8 : size === 'lg' ? 12 : 10}
          className="shrink-0"
        />
      )}
      {label}
      {showAge && provenance.age_days !== null && provenance.age_days !== undefined && (
        <span className="text-[8px] opacity-60">· {Number(provenance.age_days).toFixed(0)} d</span>
      )}
    </span>
  );
}
