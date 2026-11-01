/**
 * ThreeDee: WebGL 3D scene screen.
 *
 * Lazy-loaded 3D scene with WebGL feature detection and error boundary
 * falling back to the 2D bridge. Shares the sim clock with the 2D view.
 */
import { ThreeScene } from '../components/ThreeScene';
import { ViewModeToggle } from '../components/ViewModeToggle';

export function ThreeDee(): JSX.Element {
  return (
    <div className="h-full flex flex-col bg-[#0b1021] text-ink">
      <div className="flex h-14 shrink-0 items-center justify-between border-b border-hair bg-panel px-5">
        <div className="flex items-center gap-3">
          <span className="display text-[20px] tracking-[0.08em] text-accent">ICEFLOW · 3D</span>
          <span className="text-2xs text-ink-3">WebGL scene · shared clock with 2D</span>
        </div>
        <ViewModeToggle />
      </div>
      <div className="flex-1 relative">
        <ThreeScene />
      </div>
    </div>
  );
}
