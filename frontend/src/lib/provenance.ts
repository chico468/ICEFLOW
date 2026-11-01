/**
 * Honesty layer: normalize provenance into a single canonical shape so every
 * on-screen number carries a ProvenanceBadge whose kind is one of
 * observed / reanalysis / forecast / derived / simulated / real-seed.
 *
 * Two input shapes are accepted:
 *   1. { status, source, note, observed_date?, age_days? }   (API / current Provenance type)
 *   2. { kind, source, product, valid_time, age_hours? }     (golden-fixture provenance_by_variable)
 *
 * Shape 2 is mapped onto shape 1: kind -> status, product -> note,
 * valid_time -> observed_date, age_hours -> age_days (hours / 24).
 * The legacy kind 'synthetic' is normalized to 'simulated'. Anything
 * outside the canonical set is passed through as-is so it is never
 * silently dropped.
 */
import type { Provenance } from '../api/types';

export type ProvenanceLike =
  | Provenance
  | { kind: string; source: string; product?: string; valid_time?: string; age_hours?: number };

const CANONICAL_KINDS = new Set([
  'observed',
  'reanalysis',
  'forecast',
  'derived',
  'simulated',
  'real-seed',
]);

const LEGACY_TO_CANONICAL: Record<string, string> = {
  real: 'observed',
  'real-observation': 'observed',
  synthetic: 'simulated',
};

function canonicalKind(kind: string): string {
  const mapped = LEGACY_TO_CANONICAL[kind] ?? kind;
  return CANONICAL_KINDS.has(mapped) ? mapped : kind;
}

/**
 * Normalize a provenance record into the canonical { status, source, note,
 * observed_date?, age_days? } shape. Returns null when the record carries no
 * usable identity (no status/kind and no source).
 */
export function normalizeProvenance(p: ProvenanceLike | null | undefined): Provenance | null {
  if (!p) return null;

  // Shape 2: { kind, source, product, valid_time, age_hours? }
  if ('kind' in p) {
    if (!p.kind && !p.source) return null;
    const status = canonicalKind(p.kind);
    const ageDays = p.age_hours != null ? p.age_hours / 24 : undefined;
    return {
      status,
      source: p.source,
      note: p.product ?? '',
      ...(p.valid_time ? { observed_date: p.valid_time } : {}),
      ...(ageDays !== undefined ? { age_days: ageDays } : {}),
    };
  }

  // Shape 1: { status, source, note, observed_date?, age_days? }
  if (!p.status && !p.source) return null;
  return {
    status: canonicalKind(p.status),
    source: p.source,
    note: p.note ?? '',
    ...(p.observed_date ? { observed_date: p.observed_date } : {}),
    ...(p.age_days !== undefined ? { age_days: p.age_days } : {}),
  };
}

/** The canonical set of provenance kinds the badge honours. */
export const PROVENANCE_KINDS = ['observed', 'reanalysis', 'forecast', 'derived', 'simulated', 'real-seed'] as const;
