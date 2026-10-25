import { AlertTriangle } from 'lucide-react';

export function SimulatedNotice({ className = '' }: { className?: string }): JSX.Element {
  return (
    <div
      role="note"
      className={`flex items-start gap-2 rounded-md border border-caution/60 bg-caution/10 p-2 text-xs text-ink ${className}`}
    >
      <AlertTriangle className="mt-0.5 h-3.5 w-3.5 text-caution" aria-hidden="true" />
      <p>Planned on simulated ice and weather. Not for navigation.</p>
    </div>
  );
}

export default SimulatedNotice;
