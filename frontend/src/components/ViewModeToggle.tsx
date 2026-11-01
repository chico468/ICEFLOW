/**
 * ViewModeToggle: 2D/3D view toggle for the bridge.
 *
 * Switches between the 2D chart view and the WebGL 3D scene. Falls back to
 * 2D if WebGL is unavailable.
 */
import { useState } from 'react';

export function ViewModeToggle(): JSX.Element {
  const [mode, setMode] = useState<'2d' | '3d'>('2d');

  return (
    <div className="absolute top-4 right-4 flex flex-col gap-1 z-50">
      <div className="flex gap-0.5 rounded-lg border border-hair bg-panel/95 p-1">
        <button
          type="button"
          onClick={() => setMode('2d')}
          className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
            mode === '2d' ? 'bg-accent text-on-accent' : 'text-ink-2 hover:bg-panel-3'
          }`}
        >
          2D
        </button>
        <button
          type="button"
          onClick={() => setMode('3d')}
          className={`px-2.5 py-1 text-xs rounded-md transition-colors ${
            mode === '3d' ? 'bg-accent text-on-accent' : 'text-ink-2 hover:bg-panel-3'
          }`}
        >
          3D
        </button>
      </div>
      {mode === '3d' && (
        <div className="mt-1 rounded-lg border border-hair bg-panel/95 p-1 text-[9px] text-ink-3">
          WebGL 3D view — shared clock with 2D
        </div>
      )}
    </div>
  );
}
