/**
 * X-band radar plan-position indicator.
 *
 * Drawn head-up, the way a bridge radar is normally set: the ship's head is at the top and
 * contacts sit at their relative bearing, because that is the frame an officer conning the ship
 * is actually thinking in.
 *
 * The honest part of this display is the footer. The simulation knows how many real targets
 * exist and how many the radar painted, so it reports the misses. Growlers with little freeboard
 * disappear into sea clutter, and a display that implied otherwise would be teaching the wrong
 * lesson about the one hazard most likely to hole a hull.
 */
import type { RadarSweep } from '../api/types';
import { num } from '../lib/format';
import { threatColor } from '../map/palette';
import { EmptyState } from './ui';

const SIZE = 240;
const CENTRE = SIZE / 2;
const RADIUS = CENTRE - 14;

export function RadarScope({ sweep }: { sweep: RadarSweep | null }): JSX.Element {
  if (!sweep) {
    return <EmptyState title="Radar offline" detail="Start a voyage to run the sweep." />;
  }

  const maxRange = sweep.max_range_nm || 6;
  const rings = [0.25, 0.5, 0.75, 1].map((f) => f * RADIUS);
  const alertRing = (3 / maxRange) * RADIUS;

  return (
    <div>
      <svg viewBox={`0 0 ${SIZE} ${SIZE}`} className="mx-auto block w-full max-w-[260px]">
        <defs>
          <radialGradient id="clutter" cx="50%" cy="50%" r="50%">
            <stop offset="0%" stopColor="#22D3EE" stopOpacity={0.10 + sweep.sea_clutter_level * 0.42} />
            <stop offset="35%" stopColor="#22D3EE" stopOpacity={0.05 + sweep.sea_clutter_level * 0.20} />
            <stop offset="100%" stopColor="#22D3EE" stopOpacity={0} />
          </radialGradient>
        </defs>

        <circle cx={CENTRE} cy={CENTRE} r={RADIUS} fill="#0A1220" stroke="#1E2E44" />
        {/* Sea clutter, which is why small ice goes undetected close in. */}
        <circle cx={CENTRE} cy={CENTRE} r={RADIUS} fill="url(#clutter)" />

        {rings.map((r, i) => (
          <circle key={r} cx={CENTRE} cy={CENTRE} r={r} fill="none" stroke="#1E2E44" strokeDasharray="2 3">
            <title>{`${num(((i + 1) / 4) * maxRange, 1)} nm`}</title>
          </circle>
        ))}

        {/* The three-mile tactical perimeter. */}
        {alertRing < RADIUS && (
          <circle cx={CENTRE} cy={CENTRE} r={alertRing} fill="none" stroke="#FBBF24" strokeOpacity={0.45} strokeDasharray="4 3" />
        )}

        {[0, 45, 90, 135, 180, 225, 270, 315].map((deg) => {
          const rad = (deg * Math.PI) / 180;
          return (
            <line
              key={deg}
              x1={CENTRE}
              y1={CENTRE}
              x2={CENTRE + RADIUS * Math.sin(rad)}
              y2={CENTRE - RADIUS * Math.cos(rad)}
              stroke="#1E2E44"
              strokeWidth={0.5}
            />
          );
        })}

        {/* Own ship, head up. */}
        <polygon
          points={`${CENTRE},${CENTRE - 7} ${CENTRE - 4},${CENTRE + 5} ${CENTRE + 4},${CENTRE + 5}`}
          fill="#22D3EE"
        />

        {sweep.contacts.map((c) => {
          const rad = (c.relative_bearing_deg * Math.PI) / 180;
          const rr = Math.min(1, c.range_nm / maxRange) * RADIUS;
          const x = CENTRE + rr * Math.sin(rad);
          const y = CENTRE - rr * Math.cos(rad);
          const colour = threatColor(c.threat_level);
          const size = 2 + Math.min(3.5, c.estimated_length_m / 40);
          return (
            <g key={c.contact_id}>
              <circle cx={x} cy={y} r={size} fill={colour} fillOpacity={0.35 + c.detection_confidence * 0.6} />
              <circle cx={x} cy={y} r={size + 2.5} fill="none" stroke={colour} strokeOpacity={0.5} strokeWidth={0.7} />
              <title>
                {`${c.size_class.replace(/_/g, ' ')} — ${num(c.range_nm, 2)} nm at ${num(c.bearing_deg, 0)}°, ` +
                  `CPA ${num(c.cpa_nm, 2)} nm in ${num(c.tcpa_minutes, 0)} min, ` +
                  `confidence ${num(c.detection_confidence * 100, 0)}%`}
              </title>
            </g>
          );
        })}

        <text x={CENTRE} y={12} textAnchor="middle" className="fill-ink-3" style={{ fontSize: 8 }}>
          HEAD UP
        </text>
        <text x={SIZE - 4} y={SIZE - 4} textAnchor="end" className="fill-ink-3" style={{ fontSize: 8 }}>
          {num(maxRange, 0)} nm
        </text>
      </svg>

      <div className="mt-2 space-y-1 text-2xs">
        <div className="flex justify-between text-ink-3">
          <span>Sea clutter</span>
          <span className="num text-ink-2">
            {num(sweep.sea_clutter_level * 100, 0)}% · Hs {num(sweep.sig_wave_height_m, 1)} m
          </span>
        </div>
        <div className="flex justify-between text-ink-3">
          <span>Effective growler range</span>
          <span className="num text-ink-2">{num(sweep.detection_range_nm, 2)} nm</span>
        </div>
        <div className="flex justify-between text-ink-3">
          <span>Painted / real targets</span>
          <span className="num text-ink-2">
            {sweep.detected_true_count} / {sweep.true_target_count}
          </span>
        </div>
        <div className="flex justify-between">
          <span className="text-ink-3">Undetected targets</span>
          <span className="num text-danger">
            {sweep.estimated_missed_targets}
            {sweep.missed_within_alert_range > 0 && (
              <span className="text-caution"> ({sweep.missed_within_alert_range} inside 3 nm)</span>
            )}
          </span>
        </div>
        <div className="flex justify-between text-ink-3">
          <span>False alarms</span>
          <span className="num text-ink-2">{sweep.false_alarm_count}</span>
        </div>
        <p className="pt-1 text-ink-3/80">
          Contact count is a lower bound. Low-freeboard ice is lost in clutter, which is precisely
          what makes growlers dangerous.
        </p>
      </div>
    </div>
  );
}
