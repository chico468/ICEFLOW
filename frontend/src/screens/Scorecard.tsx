/**
 * Scorecard: evidence behind the forecast numbers.
 *
 * Every number carries a provenance badge (kind + age) so a reviewer can answer
 * "which of these numbers came from the world?" without reading code.
 * Built first against a fixture JSON; when /api/v1/evidence/scorecard is
 * unreachable the fixture is shown instead, flagged as such.
 */
import { useQuery } from '@tanstack/react-query';
import * as api from '../api/client';
import type { Provenance, ScorecardResponse } from '../api/types';
import { ProvenanceBadge } from '../components/ProvenanceBadge';
import { Panel, Stat } from '../components/ui';
import { int, num, shortIso } from '../lib/format';
import { scorecardFixture, scorecardIsSampleData } from '../lib/scorecard';

const MODEL_PROVENANCE: Record<string, Provenance> = {
  damped_persistence: {
    status: 'forecast',
    source: 'damped-persistence baseline',
    note: 'sea-ice concentration hindcast',
  },
  gbm_residual: {
    status: 'experimental_ml',
    source: 'gradient-boosted residual model',
    note: 'sea-ice concentration hindcast',
  },
  constant_velocity_damped: {
    status: 'forecast',
    source: 'constant-velocity drift',
    note: 'iceberg drift hindcast',
  },
  'ml_residual_on_velocity': {
    status: 'experimental_ml',
    source: 'ML residual on velocity',
    note: 'iceberg drift hindcast',
  },
};

function modelProvenance(model: string): Provenance {
  return MODEL_PROVENANCE[model] ?? { status: 'synthetic', source: 'unspecified model', note: model };
}

export function Scorecard(): JSX.Element {
  const { data: scorecard, isError, isLoading, error } = useQuery<ScorecardResponse>({
    queryKey: ['evidence-scorecard'],
    queryFn: async () => {
      try {
        return await api.getScorecard();
      } catch {
        return scorecardFixture as ScorecardResponse;
      }
    },
    staleTime: Infinity,
  });

  if (isLoading) {
    return (
      <div className="flex h-full flex-col items-center justify-center gap-1.5 p-6 text-center">
        <div className="display text-[15px] text-ink-2">Loading scorecard</div>
        <div className="max-w-sm text-xs leading-relaxed text-ink-3">
          Fetching /api/v1/evidence/scorecard
        </div>
      </div>
    );
  }

  // Never present fixture numbers as real results: when the endpoint is unreachable (or there is no
  // data at all) we fall back to the fixture and flag it prominently as sample data.
  const apiUnavailable = isError;
  const s: ScorecardResponse = apiUnavailable || !scorecard ? scorecardFixture : scorecard;
  const sampleData = apiUnavailable || !scorecard || scorecardIsSampleData(s, apiUnavailable);

  return (
    <div className="h-full overflow-y-auto p-4">
      {sampleData && (
        <div className="mb-3 rounded-xl border border-[rgb(var(--c-warn))] bg-[rgb(var(--c-warn))]/10 p-3">
          <div className="flex items-start gap-2">
            <div className="shrink-0 border border-[rgb(var(--c-warn))] rounded p-[2px]">
              <span className="block text-[10px] font-semibold text-[rgb(var(--c-warn))]">SAMPLE DATA</span>
            </div>
            <div className="text-xs leading-relaxed">
              <div className="font-semibold text-ink">SAMPLE DATA, not real results</div>
              <div className="mt-0.5 text-[11px] text-ink-3/80">
                {apiUnavailable
                  ? `The scorecard endpoint could not be reached${error ? ` (${error.message})` : ''}, so the fixture below is shown instead.`
                  : 'No scorecard data is available, so the fixture below is shown instead.'}
                {' '}
                These numbers are sample data — do not use them as real results.
              </div>
            </div>
          </div>
        </div>
      )}

      <div className="mx-auto grid max-w-[1500px] grid-cols-1 gap-4 lg:grid-cols-2">
        <Panel
          title="Scorecard"
          subtitle={sampleData ? 'Fixture (backend unreachable)' : shortIso(s.generated_at)}
        >
          <div className="mb-3 grid grid-cols-2 gap-3 sm:grid-cols-4">
            <Stat label="Data source" value={s.data_source} tone={s.data_source === 'real' ? 'ok' : 'caution'} />
            <Stat label="Product" value={s.product ?? '—'} size="sm" />
            <Stat label="Version" value={s.version ?? '—'} size="sm" />
            <Stat label="Git SHA" value={s.git_sha ?? '—'} size="sm" />
            <Stat label="Train years" value={trainYearsText(s.train_years)} size="sm" />
            <Stat label="Test years" value={trainYearsText(s.test_years)} size="sm" />
          </div>
          {s.caveats.length > 0 && (
            <div className="mt-2 border-t border-hair/60 pt-2 space-y-1">
              <div className="text-2xs text-ink-3 font-medium">Caveats</div>
              {s.caveats.map((c, i) => (
                <div key={i} className="text-2xs text-ink-3/80 leading-relaxed">
                  • {c}
                </div>
              ))}
            </div>
          )}
          <div className="mt-2 inline-flex items-center gap-1 rounded px-1.5 py-0.5 text-[8px] border border-hair-2 text-ink-2 bg-panel-2">
            {sampleData ? 'Falling back to fixture' : 'Live endpoint /api/v1/evidence/scorecard'}
            {isError && <span className="text-[8px] opacity-60">· {error?.message ?? 'unreachable'}</span>}
          </div>
        </Panel>

        <Panel title="Rows" subtitle="Hindcast skill by task, lead, domain and season">
          <div className="overflow-x-auto">
            <table className="min-w-full text-2xs border-collapse border border-hair/60">
              <thead>
                <tr className="border-b border-hair/60">
                  {['Task', 'Lead (d)', 'Domain', 'Season', 'Model', 'RMSE / error', '90% CI', 'Skill vs base.', 'n', 'Provenance'].map(
                    (h) => (
                      <th key={h} className="text-left pb-1.5 text-ink-3 font-normal">{h}</th>
                    )
                  )}
                </tr>
              </thead>
              <tbody>
                {s.rows.map((row, i) => (
                  <tr key={i} className="border-b border-hair/60 last:border-0">
                    <td className="py-1.5 text-ink">{row.task}</td>
                    <td className="py-1.5 text-ink">{int(row.lead_days)}</td>
                    <td className="py-1.5 text-ink-2">{row.domain}</td>
                    <td className="py-1.5 text-ink-2">{row.season}</td>
                    <td className="py-1.5 text-ink">{row.model}</td>
                    <td className="py-1.5 text-ink num">
                      {row.rmse != null ? num(row.rmse, 4) : row.error_km != null ? `${num(row.error_km, 1)} km` : '—'}
                    </td>
                    <td className="py-1.5 text-ink-2">[{row.ci[0].toFixed(3)}, {row.ci[1].toFixed(3)}]</td>
                    <td className="py-1.5 text-ink-2">
                      {row.skill_vs_baseline != null ? `${signed(row.skill_vs_baseline, 2)}` : '—'}
                    </td>
                    <td className="py-1.5 text-ink">{int(row.n)}</td>
                    <td className="py-1.5">
                      <ProvenanceBadge provenance={modelProvenance(row.model)} size="sm" showAge={false} />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>

        <Panel title="Promoted" subtitle="Promotion gate: RMSE beats tuned baseline, CI excludes zero, both seasons">
          <div className="grid grid-cols-2 gap-3 sm:grid-cols-4">
            {[
              { label: 'SIC lead 3', ok: s.promoted.sic['3'] ?? false },
              { label: 'SIC lead 7', ok: s.promoted.sic['7'] ?? false },
              { label: 'SIC lead 14', ok: s.promoted.sic['14'] ?? false },
              { label: 'Iceberg lead 1', ok: s.promoted.iceberg['1'] ?? false },
              { label: 'Iceberg lead 3', ok: s.promoted.iceberg['3'] ?? false },
              { label: 'Iceberg lead 7', ok: s.promoted.iceberg['7'] ?? false },
            ].map(({ label, ok }) => (
              <Stat key={label} label={label} value={ok ? 'yes' : 'no'} tone={ok ? 'ok' : 'danger'} size="sm" />
            ))}
          </div>
        </Panel>

        <Panel title="Conformal coverage" subtitle="90% intervals, stratified by lead and concentration bin">
          <div className="overflow-x-auto">
            <table className="min-w-full text-2xs border-collapse border border-hair/60">
              <thead>
                <tr className="border-b border-hair/60">
                  <th className="text-left pb-1.5 text-ink-3 font-normal">Lead (d)</th>
                  <th className="text-left pb-1.5 text-ink-3 font-normal">Target</th>
                  <th className="text-left pb-1.5 text-ink-3 font-normal">Empirical</th>
                  <th className="text-left pb-1.5 text-ink-3 font-normal">Provenance</th>
                </tr>
              </thead>
              <tbody>
                {Object.entries(s.coverage).map(([leadDays, cov]) => (
                  <tr key={leadDays} className="border-b border-hair/60 last:border-0">
                    <td className="py-1.5 text-ink">{leadDays}</td>
                    <td className="py-1.5 text-ink-2">{pct(cov.target)}</td>
                    <td className="py-1.5 text-ink-2">{cov.empirical == null ? '—' : pct(cov.empirical)}</td>
                    <td className="py-1.5">
                      <ProvenanceBadge
                        provenance={{ status: 'forecast', source: 'conformal calibration', note: 'validation residuals' }}
                        size="sm"
                        showAge={false}
                      />
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        </Panel>
      </div>
    </div>
  );
}

function pct(f: number): string {
  return `${(f * 100).toFixed(0)}%`;
}

function trainYearsText(years: number[] | null | undefined): string {
  return years?.length ? years.join('–') : '—';
}

function signed(v: number, digits = 2): string {
  return `${v >= 0 ? '+' : ''}${v.toFixed(digits)}`;
}
