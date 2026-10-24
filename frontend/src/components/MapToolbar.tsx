/**
 * The one place map controls live: a compact cluster in the top-right of the map cell.
 *
 * Both charts (polar and regional) render this same component in this same position, so a control never
 * moves when the view changes, and there is exactly one stack per visible chart. It is positioned against
 * the map cell, not the window, so it cannot end up under a panel.
 *
 *   lead      an optional first row (the Polar / Regional view switch)
 *   children  groups of <ToolButton>; a divider is drawn between groups
 */
import type { ReactNode } from 'react';

export function MapToolbar({ lead, groups }: { lead?: ReactNode; groups: ReactNode[] }): JSX.Element {
  return (
    <div className="absolute right-3 top-3 z-10 flex flex-col items-end gap-2" role="toolbar" aria-label="Map controls">
      {lead}
      {groups.map((g, i) => (
        <div key={i} className="map-tools flex flex-col divide-y divide-hair overflow-hidden rounded-lg border border-hair-2 bg-panel shadow-card">
          {g}
        </div>
      ))}
    </div>
  );
}

export function ToolButton({
  label,
  hint,
  onClick,
  children,
  pressed,
  disabled,
  controls,
  expanded,
}: {
  label: string;
  hint?: string;
  onClick: () => void;
  children: ReactNode;
  pressed?: boolean;
  disabled?: boolean;
  controls?: string;
  expanded?: boolean;
}): JSX.Element {
  return (
    <button
      type="button"
      className={`map-tool ${pressed ? 'map-tool-on' : ''}`}
      title={hint ?? label}
      aria-label={label}
      aria-pressed={pressed}
      aria-expanded={expanded}
      aria-controls={controls}
      disabled={disabled}
      onClick={onClick}
    >
      {children}
    </button>
  );
}

/** A two-way segmented switch, used for the Polar / Regional view. */
export function Segmented<T extends string>({
  label,
  value,
  options,
  onChange,
}: {
  label: string;
  value: T;
  options: { id: T; label: string; hint?: string }[];
  onChange: (v: T) => void;
}): JSX.Element {
  return (
    <div role="group" aria-label={label} className="flex overflow-hidden rounded-lg border border-hair-2 bg-panel shadow-card">
      {options.map((o) => (
        <button
          key={o.id}
          type="button"
          title={o.hint}
          aria-pressed={value === o.id}
          onClick={() => onChange(o.id)}
          className={`px-2.5 py-1.5 text-2xs transition-colors ${
            value === o.id ? 'bg-accent font-semibold text-on-accent' : 'text-ink-2 hover:bg-panel-2 hover:text-ink'
          }`}
        >
          {o.label}
        </button>
      ))}
    </div>
  );
}
