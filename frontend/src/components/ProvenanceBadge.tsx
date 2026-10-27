/**
 * A compact inline badge that says where a piece of data came from.
 *
 * Principle P2: nothing here is hardcoded. It reads a Provenance record from
 * /api/v1/health and renders a colored chip so the user can see at a glance
 * whether a layer is observed, a real-data feed, or a simulated stand-in.
 *
 * Used inline with layer labels and controls, where a full ProvenanceBar
 * popover would be too heavy.
 *
 * Two usage modes:
 *  - Pass a full `Provenance` object (looked up from /api/v1/health).
 *  - Pass a simple `status` string ('synthetic' | 'observation' | 'real')
 *    when the provenance is known from the layer's source type.
 */
import { Cloud, Database, FlaskConical, Globe, Satellite } from 'lucide-react';
import type { Provenance } from '../api/types';

export type SourceStatus = 'synthetic' | 'observation' | 'real' | 'analysis' | 'forecast';

const STATUS_LABELS: Record<SourceStatus, string> = {
  synthetic: 'Simulated',
  observation: 'Observed',
  real: 'Real',
  analysis: 'Analysis',
  forecast: 'Forecast',
};

const STATUS_TONES: Record<SourceStatus, 'ok' | 'caution' | 'accent' | 'neutral'> = {
  synthetic: 'caution',
  observation: 'ok',
  real: 'ok',
  analysis: 'accent',
  forecast: 'accent',
};

const STATUS_ICONS: Record<SourceStatus, React.ElementType> = {
  synthetic: FlaskConical,
  observation: Satellite,
  real: Database,
  analysis: Cloud,
  forecast: Globe,
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

/** Resolve a Provenance object to a SourceStatus. */
export function provenanceToStatus(provenance: Provenance | undefined): SourceStatus {
  if (!provenance) return 'synthetic';
  if (provenance.status === 'real-observation') return 'observation';
  if (provenance.status === 'synthetic' || provenance.status === 'real-seed') return 'synthetic';
  if (provenance.status === 'real') {
    if (provenance.source?.toLowerCase().includes('gfs') || provenance.source?.toLowerCase().includes('noaa')) {
      return 'forecast';
    }
    if (provenance.source?.toLowerCase().includes('copernicus')) return 'analysis';
    return 'real';
  }
  return 'synthetic';
}

/** Resolve a Provenance object to a display label. */
export function provenanceLabel(provenance: Provenance | undefined): string {
  const status = provenanceToStatus(provenance);
  return STATUS_LABELS[status];
}

export function ProvenanceBadge({
  provenance,
  status,
  source,
  className,
  title,
  showIcon = true,
  size = 'md',
}: {
  /** Full Provenance record (takes priority over `status`). */
  provenance?: Provenance;
  /** Shorthand: pass a status string instead of a full Provenance object. */
  status?: SourceStatus;
  /** Custom source label shown in the title. */
  source?: string;
  className?: string;
  title?: string;
  showIcon?: boolean;
  size?: 'sm' | 'md' | 'lg';
}): JSX.Element {
  const resolvedStatus = provenance ? provenanceToStatus(provenance) : (status ?? 'synthetic');
  const Icon = STATUS_ICONS[resolvedStatus];
  const tone = STATUS_TONES[resolvedStatus];
  const label = STATUS_LABELS[resolvedStatus];
  const sizeClass = SIZE_CLASSES[size];
  const toneClass = TONE_CLASSES[tone];
  const badgeTitle = title
    ?? (provenance?.source ? `${provenance.source}${provenance.note ? ` — ${provenance.note}` : ''}` : source ?? 'Unknown provenance');
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
    </span>
  );
}
