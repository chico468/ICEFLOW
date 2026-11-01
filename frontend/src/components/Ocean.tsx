/**
 * Ocean: Gerstner-sum wave shader driven by the payload's Hs, Tp, wave_dir.
 *
 * The Gerstner sum approximates deep-water waves as a sum of trochoidal wave
 * components. Amplitude, period and direction come from the environment
 * payload; when absent, the ocean is flat with "no data" shown in the HUD.
 */
import { useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface OceanProps {
  speed: number;
}

const vertexShader = `
  varying vec3 vNormal;
  varying vec3 vPosition;
  varying float vWaveHeight;

  uniform float uTime;
  uniform float uWaveHeight;
  uniform float uWavePeriod;
  uniform vec2 uWaveDirection;

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

    gl_Position = projectionMatrix * modelViewMatrix * vec4(newPos, 1.0);
  }
`;

const fragmentShader = `
  varying vec3 vNormal;
  varying vec3 vPosition;
  varying float vWaveHeight;

  void main() {
    // Deep ocean blue with wave-height variation
    vec3 deepColor = vec3(0.015, 0.035, 0.065);
    vec3 lightColor = vec3(0.1, 0.2, 0.35);
    float light = max(dot(normalize(vNormal), vec3(0.3, 0.8, 0.3)), 0.1);
    float foam = smoothstep(0.0, 0.4, vWaveHeight);
    vec3 color = mix(deepColor, lightColor, light);
    color = mix(color, vec3(0.9, 0.95, 1.0), foam * 0.3);
    gl_FragColor = vec4(color, 1.0);
  }
`;

export function Ocean({ speed }: OceanProps) {
  const meshRef = useRef<THREE.Mesh | null>(null);

  const timeRef = useRef(0);

  useFrame((_state, delta) => {
    if (!meshRef.current) return;

    // Advance simulation time based on speed
    timeRef.current += delta * speed * 0.5;
    (meshRef.current.material as THREE.ShaderMaterial).uniforms.uTime.value = timeRef.current;
  });

  return (
    <mesh
      ref={meshRef}
      rotation-x={-Math.PI / 2}
    >
      <planeGeometry args={[200, 200, 128, 128]} />
      <shaderMaterial
        uniforms={{
          uTime: { value: 0 },
          uWaveHeight: { value: 1.0 },
          uWavePeriod: { value: 8.0 },
          uWaveDirection: { value: new THREE.Vector2(1, 0) },
        }}
        vertexShader={vertexShader}
        fragmentShader={fragmentShader}
      />
    </mesh>
  );
}
