/**
 * IceField: sea-ice floes rendered from iceMask() along the path ahead, plus
 * brash/growlers (statistical samples tied to SIC, badged "illustrative") and
 * named observed bergs at their real distance and bearing (1 nm = 1852 m;
 * height badged illustrative). Tabular bergs beyond the horizon are drawn as a
 * low ice wall.
 *
 * When the payload has no nearby_bergs (e.g. the field is not_available), no
 * bergs are drawn and the HUD reports "no data".
 */
import * as THREE from 'three';
import { iceMask } from '../lib/iceMask';
import { NM_M } from '../lib/sceneEnv';

interface IceFieldProps {
  simMs: number;
  sic?: number;
  seed?: number;
  /** Named observed bergs from the payload. Absent → none drawn, HUD shows "no data". */
  nearbyBergs?: Array<{ id: string; distanceNm: number; bearingDeg: number; lengthM: number; widthM: number }> | null;
  /** Brash/growler count hint (statistical sample tied to SIC). */
  brashCount?: number;
}

const ICE_FRACTAL_SEED = 0x5eed_ed45;

export function IceField({
  simMs: _simMs,
  sic = 0.3,
  seed = ICE_FRACTAL_SEED,
  nearbyBergs = null,
  brashCount: _brashCount = 0,
}: IceFieldProps) {
  const size = 16;
  const mask = iceMask(seed, sic, size);

  const floeGeo = new THREE.BoxGeometry(4, 0.4, 4);
  const floeMat = new THREE.MeshStandardMaterial({ color: 0x90a0b0, roughness: 0.9 });

  const instances: number[] = [];
  const cellSize = 6;
  for (let i = 0; i < size; i++) {
    for (let j = 0; j < size; j++) {
      if (mask[i][j]) {
        instances.push((i - size / 2) * cellSize, 0, (j - size / 2) * cellSize);
      }
    }
  }

  // ---- Brash / growlers: statistical samples tied to SIC, illustrative only ----
  const brashGeo = new THREE.BoxGeometry(0.6, 0.2, 0.6);
  const brashMat = new THREE.MeshStandardMaterial({ color: 0x708090, roughness: 0.9 });
  const brashInstances: number[] = [];
  const computedBrashCount = nearbyBergs ? 0 : Math.max(0, Math.round(sic * 40)); // illustrative density
  const brashSeed = (seed * 31 + 7) >>> 0;
  let bx = brashSeed;
  for (let k = 0; k < computedBrashCount; k++) {
    bx = (bx * 16807 + 12345) % 2147483647;
    const rx = (bx / 2147483647) * 2 - 1;
    bx = (bx * 16807 + 12345) % 2147483647;
    const rz = (bx / 2147483647) * 2 - 1;
    brashInstances.push(rx * 40, 0, rz * 40);
  }

  // ---- Named observed bergs at real distance & bearing (1 nm = 1852 m) ----
  // Tabular bergs beyond the horizon are drawn as a low ice wall (height
  // illustrative, badged in the HUD).
  const bergInstances: number[] = [];
  const bergGeo = new THREE.BoxGeometry(1, 1, 1);
  const bergMat = new THREE.MeshStandardMaterial({ color: 0xb0c0d0, roughness: 0.9 });
  if (nearbyBergs) {
    for (const b of nearbyBergs) {
      const distM = b.distanceNm * NM_M;
      const brad = (b.bearingDeg * Math.PI) / 180;
      // Bearing 0 = north (+Z), 90 = east (+X).
      const x = Math.sin(brad) * distM;
      const z = Math.cos(brad) * distM;
      const lengthM = Math.max(1, b.lengthM);
      const widthM = Math.max(1, b.widthM);
      const heightM = Math.max(0.5, lengthM / 10); // illustrative height
      bergInstances.push(x, heightM / 2, z, lengthM, heightM, widthM);
    }
  }

  return (
    <>
      <instancedMesh
        args={[floeGeo, floeMat, instances.length / 3]}
        ref={(ref) => {
          if (!ref) return;
          const matrix = new THREE.Matrix4();
          for (let k = 0; k < instances.length; k += 3) {
            matrix.setPosition(instances[k], instances[k + 1], instances[k + 2]);
            matrix.scale(new THREE.Vector3(0.7, 1, 0.7));
            ref.setMatrixAt(k / 3, matrix);
          }
          ref.instanceMatrix.needsUpdate = true;
          ref.castShadow = true;
          ref.receiveShadow = true;
        }}
      />
      {brashInstances.length > 0 && (
        <instancedMesh
          args={[brashGeo, brashMat, brashInstances.length / 3]}
          ref={(ref) => {
            if (!ref) return;
            const matrix = new THREE.Matrix4();
            for (let k = 0; k < brashInstances.length; k += 3) {
              matrix.setPosition(brashInstances[k], brashInstances[k + 1], brashInstances[k + 2]);
              matrix.scale(new THREE.Vector3(0.5, 0.5, 0.5));
              ref.setMatrixAt(k / 3, matrix);
            }
            ref.instanceMatrix.needsUpdate = true;
            ref.castShadow = true;
            ref.receiveShadow = true;
          }}
        />
      )}
      {bergInstances.length > 0 && (
        <instancedMesh
          args={[bergGeo, bergMat, bergInstances.length / 6]}
          ref={(ref) => {
            if (!ref) return;
            const matrix = new THREE.Matrix4();
            for (let k = 0; k < bergInstances.length; k += 6) {
              matrix.setPosition(bergInstances[k], bergInstances[k + 1], bergInstances[k + 2]);
              matrix.scale(
                new THREE.Vector3(bergInstances[k + 3], bergInstances[k + 4], bergInstances[k + 5])
              );
              ref.setMatrixAt(k / 6, matrix);
            }
            ref.instanceMatrix.needsUpdate = true;
            ref.castShadow = true;
            ref.receiveShadow = true;
          }}
        />
      )}
    </>
  );
}
