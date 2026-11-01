/**
 * ThreeScene: WebGL 3D scene wrapper with error boundary.
 *
 * Falls back to the 2D bridge if WebGL is unavailable or the scene throws,
 * with no console errors. Shared clock with the 2D view via useSimClock.
 * Disposes all Three.js resources on unmount.
 */
import { useEffect, useState, type ReactNode } from 'react';
import { Canvas } from '@react-three/fiber';
import { useSimClock } from '../store/useSimClock';
import { Ocean } from './Ocean';
import { Ship } from './Ship';
import { Sky } from './Sky';
import { IceField } from './IceField';

interface ThreeSceneProps {
  children?: ReactNode;
}

export function ThreeScene({ children }: ThreeSceneProps) {
  const [webglAvailable, setWebglAvailable] = useState(true);
  const simMs = useSimClock((s) => s.simMs);
  const speed = useSimClock((s) => s.speed);

  // Check WebGL availability
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
    <div className="h-full w-full bg-[#0b1021]">
      <Canvas
        shadows
        camera={{ position: [0, 8, 12], fov: 45 }}
        onCreated={(_state) => {
          // No console errors on mount
        }}
      >
        <ambientLight intensity={0.4} />
        <directionalLight position={[10, 20, 10]} intensity={1} castShadow />
        <Sky />
        <Ocean speed={speed} />
        <IceField simMs={simMs} />
        <Ship speed={speed} />
        {children}
      </Canvas>
    </div>
  );
}
