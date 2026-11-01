/**
 * Sky: skybox/dome colored from the payload's sun azimuth/elevation.
 *
 * Below the horizon → night palette; above → day palette with sun gradient.
 * If sun data is absent, the HUD shows "no data" and the sky is a neutral
 * twilight color.
 */
import { useEffect, useRef } from 'react';
import * as THREE from 'three';

interface SkyProps {
  sunAzimuthDeg?: number;
  sunElevationDeg?: number;
}

export function Sky({ sunAzimuthDeg, sunElevationDeg }: SkyProps = {}) {
  const sphereRef = useRef<THREE.Mesh | null>(null);

  useEffect(() => {
    if (!sphereRef.current) return;

    const material = sphereRef.current.material as THREE.ShaderMaterial;

    const hasData = sunAzimuthDeg != null && sunElevationDeg != null;

    // Day/night based on elevation
    const isDay = (sunElevationDeg ?? -10) > -5;
    const dayColor = new THREE.Color(0x4080ff);
    const nightColor = new THREE.Color(0x050515);
    const twilightColor = new THREE.Color(0x203050);

    const skyColor = isDay ? dayColor : sunElevationDeg! > -15 ? twilightColor : nightColor;
    material.uniforms.uSkyColor.value = skyColor;

    // Sun position in sky
    const az = ((sunAzimuthDeg ?? 0) * Math.PI) / 180;
    const el = ((sunElevationDeg ?? 0) * Math.PI) / 180;
    material.uniforms.uSunDir.value = new THREE.Vector3(
      Math.sin(az) * Math.cos(el),
      Math.sin(el),
      Math.cos(az) * Math.cos(el)
    );

    material.uniforms.uHasData.value = hasData ? 1 : 0;
  }, [sunAzimuthDeg, sunElevationDeg]);

  return (
    <mesh
      ref={sphereRef}
      scale={new THREE.Vector3(1000, 1000, 1000)}
    >
      <sphereGeometry args={[1, 64, 64]} />
      <shaderMaterial
        uniforms={{
          uSkyColor: { value: new THREE.Color(0x4080ff) },
          uSunDir: { value: new THREE.Vector3(0, 1, 0) },
          uHasData: { value: 0 },
        }}
        vertexShader={`
          varying vec3 vWorldPos;
          varying vec3 vSunDir;
          varying float vHasData;
          void main() {
            vWorldPos = (modelMatrix * vec4(position, 1.0)).xyz;
            vSunDir = normalize(vec3(0.0, 1.0, 0.0));
            vHasData = 0.0;
            gl_Position = projectionMatrix * modelViewMatrix * vec4(position, 1.0);
          }
        `}
        fragmentShader={`
          varying vec3 vWorldPos;
          varying vec3 vSunDir;
          varying float vHasData;
          uniform vec3 uSkyColor;
          uniform vec3 uSunDir;
          uniform float uHasData;
          void main() {
            float height = vWorldPos.y / 1000.0;
            float tide = smoothstep(-0.3, 0.3, height);
            vec3 sky = mix(uSkyColor * 0.5, uSkyColor, tide);
            if (vHasData > 0.5) {
              float sunDot = dot(normalize(vWorldPos), vSunDir);
              float sunGlow = pow(max(sunDot, 0.0), 64.0);
              sky += sunGlow * vec3(1.0, 0.9, 0.7) * 0.5;
              float horizonGlow = pow(max(dot(normalize(vWorldPos), vec3(0, 1, 0)), 0.0), 4.0);
              sky += horizonGlow * vec3(1.0, 0.8, 0.5) * 0.3;
            }
            gl_FragColor = vec4(sky, 1.0);
          }
        `}
        side={THREE.BackSide}
        depthWrite={false}
      />
    </mesh>
  );
}
