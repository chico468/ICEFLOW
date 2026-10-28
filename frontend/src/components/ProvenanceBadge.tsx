/**
 * A compact inline badge that says where a piece of data came from.
 *
 * Principle P2: nothing here is hardcoded. The badge renders from a typed
 * Provenance record (kind, source, product, valid_time, age_hours) and derives
 * its label, tone and icon from `kind` alone, so no per-layer text is baked in.
 *
 * Kinds: observed | real_forecast | simulated | experimental_ml | real-seed
 *   observed        -> Observed
 *   real_forecast   -> Forecast (real data)
 *   simulated       -> Simulated
 *   experimental_ml -> Experimental ML
 *   real-seed       -> Real catalogue (drift simulated)
 *
 * Used inline with layer labels and controls, where a full ProvenanceBar
 * popover would be too heavy.
 */
import { Cloud, Database, FlaskConical, Globe, Satellite } from 'lucide-react';
import type { Provenance } from '../api/types';

export type ProvenanceKind = Provenance['kind'];

const KIND_LABELS: Record<ProvenanceKind, string> = {
  observed: 'Observed',
  real_forecast: 'Forecast (real data)',
  simulated: 'Simulated',
  experimental_ml: 'Experimental ML',
  'real-seed': 'Real catalogue (drift simulated)',
};

const KIND_TONES: Record<ProvenanceKind, 'ok' | 'caution' | 'accent' | 'neutral'> = {
  observed: 'ok',
  real_forecast: 'accent',
  simulated: 'caution',
  experimental_ml: 'caution',
  'real-seed': 'neutral',
};

const KIND_ICONS: Record<ProvenanceKind, React.ElementType> = {
  observed: Satellite,
  real_forecast: Globe,
  simulated: FlaskConical,
  experimental_ml: Cloud,
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

export function provenanceKindLabel(provenance: Provenance): string {
  return KIND_LABELS[provenance.kind];
}

export function ProvenanceBadge({
  provenance,
  className,
  title,
  showAge = true,
  showIcon = true,
  size = 'md',
}: {
  /** Full Provenance record; the label, tone and icon come from its kind. */
  provenance: Provenance;
  className?: string;
  /** Optional tooltip override; defaults to provenance-derived title. */
  title?: string;
  /** Append the age (hours) to the visible label. */
  showAge?: boolean;
  showIcon?: boolean;
  size?: 'sm' | 'md' | 'lg';
}): JSX.Element {
  const label = KIND_LABELS[provenance.kind];
  const tone = KIND_TONES[provenance.kind];
  const Icon = KIND_ICONS[provenance.kind];
  const sizeClass = SIZE_CLASSES[size];
  const toneClass = TONE_CLASSES[tone];

  const parts: string[] = [provenance.source];
  if (provenance.product) parts.push(provenance.product);
  if (provenance.valid_time) parts.push(`valid ${provenance.valid_time}`);
  if (showAge && provenance.age_hours !== null && provenance.age_hours !== undefined) {
    parts.push(`${Number(provenance.age_hours).toFixed(0)} h old`);
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
      {showAge && provenance.age_hours !== null && provenance.age_hours !== undefined && (
        <span className="text-[8px] opacity-60">· {Number(provenance.age_hours).toFixed(0)} h</span>
      )}
    </span>
  );
}
