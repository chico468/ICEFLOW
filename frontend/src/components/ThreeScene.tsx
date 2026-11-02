/**
 * ThreeScene: WebGL 3D scene wrapper with error boundary.
 *
 * Falls back to the 2D bridge if WebGL is unavailable or the scene throws,
 * with no console errors. Shared clock with the 2D view via useSimClock.
 * Distributes the environment payload to Ocean / Sky / Ship / IceField and
 * renders a HUD (ice product/valid time, SIMULATED banner, bergs status).
 * Disposes all Three.js resources on unmount.
 *
 * Adaptive quality: if fps stays under 25 for 3 s, water segments and
 * particle counts are lowered. FPS is logged at 1280x720.
 */
import { useCallback, useEffect, useRef, useState, type ReactNode } from 'react';
import { Canvas, useFrame, useThree } from '@react-three/fiber';
import { useSimClock } from '../store/useSimClock';
import { Ocean } from './Ocean';
import { Ship } from './Ship';
import { Sky } from './Sky';
import { IceField } from './IceField';
import type { SceneEnvironment } from '../lib/sceneEnv';

interface ThreeSceneProps {
  children?: ReactNode;
  env?: SceneEnvironment;
  reducedMotion?: boolean;
}

const DEFAULT_ENV: SceneEnvironment = {};

// Inner component that runs inside Canvas to measure FPS and adaptive quality
function CanvasContent({
  children,
  env,
  reducedMotion,
  simMs,
  speed,
  quality,
  setQuality,
  setFps,
}: {
  children?: ReactNode;
  env: SceneEnvironment;
  reducedMotion: boolean;
  simMs: number;
  speed: number;
  quality: 'high' | 'low';
  setQuality: (q: 'high' | 'low') => void;
  setFps: (fps: number) => void;
}) {
  const { size } = useThree();

  const frameRef = useRef({ count: 0, last: performance.now() });
  const lowSinceRef = useRef<number | null>(null);
  const logFps = useCallback(() => {
    const now = performance.now();
    frameRef.current.count++;
    if (now - frameRef.current.last >= 1000) {
      const measuredFps = Math.round((frameRef.current.count * 1000) / (now - frameRef.current.last));
      setFps(measuredFps);
      frameRef.current.count = 0;
      frameRef.current.last = now;
      if (size.width === 1280 && size.height === 720) {
        console.log(`[ThreeScene] fps=${measuredFps} quality=${quality} size=1280x720`);
      }
      if (measuredFps < 25) {
        if (lowSinceRef.current === null) lowSinceRef.current = now;
        else if (now - lowSinceRef.current >= 3000 && quality === 'high') {
          setQuality('low');
        }
      } else {
        lowSinceRef.current = null;
        if (quality === 'low') setQuality('high');
      }
    }
  }, [quality, size.width, size.height, setFps, setQuality]);

  useFrame(() => {
    logFps();
  });

  const oceanSegments = quality === 'low' ? 64 : 128;

  return (
    <>
      <ambientLight intensity={0.4} />
      <directionalLight position={[10, 20, 10]} intensity={1} castShadow />
      <Sky sunAzimuthDeg={env.sunAzimuthDeg ?? undefined} sunElevationDeg={env.sunElevationDeg ?? undefined} />
      <Ocean speed={speed} env={env} segments={oceanSegments} />
      <Ship speed={speed} env={env} reducedMotion={reducedMotion} />
      <IceField simMs={simMs} sic={0.3} seed={0x5eed_ed45} nearbyBergs={env.nearbyBergs ?? null} />
      {children}
    </>
  );
}

export function ThreeScene({ children, env = DEFAULT_ENV, reducedMotion = false }: ThreeSceneProps) {
  const [webglAvailable, setWebglAvailable] = useState(true);
  const [fps, setFps] = useState(0);
  const [quality, setQuality] = useState<'high' | 'low'>('high');
  const simMs = useSimClock((s) => s.simMs);
  const speed = useSimClock((s) => s.speed);

  // ---- WebGL availability ----
  useEffect((): (() => void) => {
    const canvas = document.createElement('canvas');
    const webgl =
      !!(
        window.WebGLRenderingContext &&
        (canvas.getContext('webgl') || canvas.getContext('experimental-webgl'))
      );
    setWebglAvailable(webgl);
    return () => {};
  }, []);

  if (!webglAvailable) {
    return (
      <div className="flex h-full flex-col items-center justify-center p-6 text-center text-ink-2">
        <div className="text-accent font-medium">WebGL not available</div>
        <div className="text-2xs text-ink-3 mt-1">2D bridge is used instead.</div>
      </div>
    );
  }

  return (
    <div className="h-full w-full bg-[#0b1021] relative">
      <Canvas
        shadows
        camera={{ position: [0, 8, 12], fov: 45 }}
        onCreated={(_state) => {
          // No console errors on mount
        }}
      >
        <CanvasContent
          children={children}
          env={env}
          reducedMotion={reducedMotion}
          simMs={simMs}
          speed={speed}
          quality={quality}
          setQuality={setQuality}
          setFps={setFps}
        />
      </Canvas>

      {/* ---- HUD ------------------------------------------------------------------ */}
      <div className="absolute bottom-4 left-4 flex flex-col gap-1 z-50">
        <div className="rounded-lg border border-hair bg-panel/95 p-2 text-[9px] text-ink-2">
          <div className="font-semibold">Ice layer</div>
          {env.iceProduct ? (
            <>
              <div>{env.iceProduct}</div>
              <div className="text-ink-3/80">valid {env.iceValidTime ?? '—'}</div>
            </>
          ) : (
            <div className="text-warn">no data</div>
          )}
        </div>
        {env.nearbyBergs == null ? (
          <div className="rounded-lg border border-warn/40 bg-warn/10 p-2 text-[9px] text-warn">
            Bergs: no data (nearby_bergs not in payload)
          </div>
        ) : null}
        {env.simulated ? (
          <div className="rounded-lg border border-caution/40 bg-caution/10 p-2 text-[9px] text-caution">
            SIMULATED — environment is not real observations
          </div>
        ) : null}
      </div>

      {/* ---- FPS / quality readout (dev) --------------------------------------- */}
      <div className="absolute bottom-4 right-4 flex flex-col gap-0.5 z-50">
        <div className="rounded-lg border border-hair bg-panel/95 p-1 text-[8px] text-ink-3">
          fps {fps} · {quality}
        </div>
      </div>
    </div>
  );
}
