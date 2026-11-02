/**
 * Ocean: Gerstner-sum wave shader driven by the payload's Hs, Tp, wave_dir.
 *
 * Whitecap coverage is driven by wind speed: absent wind → "no data" and the
 * ocean stays flat (no fabricated whitecaps). Amplitude, period and direction
 * come from the environment payload; when Hs is absent the ocean is flat.
 */
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';
import type { SceneEnvironment } from '../lib/sceneEnv';

interface OceanProps {
  speed: number;
  env?: SceneEnvironment;
  segments?: number;
}

const vertexShader = `
  varying vec3 vNormal;
  varying vec3 vPosition;
  varying float vWaveHeight;
  varying float vWhitecap;

  uniform float uTime;
  uniform float uWaveHeight;
  uniform float uWavePeriod;
  uniform vec2 uWaveDirection;
  uniform float uWindSpeed;
  uniform float uHasWind;

  // Gerstner sum: multiple trochoidal components
  float gerstner(vec2 p, float t) {
    float h = 0.0;
    int n = 5;
    for (int i = 0; i < n; i++) {
      float freq = float(i + 1) * 0.8;
      float amp = uWaveHeight / float(n) * (1.0 - float(i) / float(n));
      float phase = dot(p, uWaveDirection * freq) - t * freq * 0.5;
      h += amp * cos(phase);
    }
    return h;
  }

  void main() {
    vNormal = normal;
    vPosition = position;

    float h = gerstner(position.xz, uTime);
    vWaveHeight = h;

    vec3 newPos = position;
    newPos.y = h;

    // Gerstner horizontal displacement
    vec2 dir = normalize(uWaveDirection);
    float steepness = 0.3;
    newPos.x -= dir.x * steepness * h * 0.5;
    newPos.z -= dir.y * steepness * h * 0.5;

    // Whitecaps where the slope is steep and wind is present.
    float slope = abs(h * 1.5);
    vWhitecap = uHasWind * smoothstep(0.3, 0.8, slope);

    gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
  }
`;

const fragmentShader = `
  varying vec3 vNormal;
  varying vec3 vPosition;
  varying float vWaveHeight;
  varying float vWhitecap;

  void main() {
    vec3 deepColor = vec3(0.015, 0.035, 0.065);
    vec3 lightColor = vec3(0.1, 0.2, 0.35);
    float light = max(dot(normalize(vNormal), vec3(0.3, 0.8, 0.3)), 0.1);
    float foam = smoothstep(0.0, 0.4, vWaveHeight);
    vec3 color = mix(deepColor, lightColor, light);
    color = mix(color, vec3(0.9, 0.95, 1.0), foam * 0.3);
    // Wind-driven whitecaps.
    color = mix(color, vec3(1.0), vWhitecap * 0.9);
    gl_FragColor = vec4(color, 1.0);
  }
`;

export function Ocean({ speed, env, segments }: OceanProps) {
  const meshRef = useRef<THREE.Mesh | null>(null);
  const timeRef = useRef(0);

  const hsM = env?.waveHeightM ?? 0;
  const periodS = env?.wavePeriodS ?? 8;
  const windMs = env?.windSpeedMs ?? 0;
  const hasWind = windMs != null && windMs > 0;
  const dir = env?.waveDirDeg ?? 0;
  const rad = (dir * Math.PI) / 180;
  const waveDir = new THREE.Vector2(Math.sin(rad), -Math.cos(rad)); // direction waves travel TO

  useFrame((_state, delta) => {
    if (!meshRef.current) return;
    timeRef.current += delta * speed * 0.5;
    const m = meshRef.current.material as THREE.ShaderMaterial;
    m.uniforms.uTime.value = timeRef.current;
    m.uniforms.uWaveHeight.value = hsM;
    m.uniforms.uWavePeriod.value = periodS;
    m.uniforms.uWaveDirection.value = waveDir;
    m.uniforms.uWindSpeed.value = windMs;
    m.uniforms.uHasWind.value = hasWind ? 1 : 0;
  });

  return (
    <mesh
      ref={meshRef}
      rotation-x={-Math.PI / 2}
    >
      <planeGeometry args={[200, 200, segments ?? 128, segments ?? 128]} />
      <shaderMaterial
        uniforms={{
          uTime: { value: 0 },
          uWaveHeight: { value: hsM },
          uWavePeriod: { value: periodS },
          uWaveDirection: { value: waveDir },
          uWindSpeed: { value: windMs },
          uHasWind: { value: hasWind ? 1 : 0 },
        }}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
      />
    </mesh>
  );
}
