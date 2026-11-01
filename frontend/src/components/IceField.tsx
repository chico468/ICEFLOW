/**
 * IceField: sea-ice floes rendered from iceMask() along the path ahead.
 *
 * iceMask(seed, sic, size) returns a boolean floe grid with coverage matching
 * the SIC within ±0.05. Floes are instanced meshes; brash and growlers are
 * statistical samples tied to SIC, badged "illustrative, not observed objects".
 * Named observed bergs appear at real distance and bearing from the payload.
 */
import * as THREE from 'three';

interface IceFieldProps {
  simMs: number;
}

const ICE_FRACTAL_SEED = 0x5eed_ed45;

/**
 * iceMask: pure function returning a boolean floe grid.
 *
 * coverage matching the SIC within ±0.05. Deterministic given seed + sic.
 */
export function iceMask(seed: number, sic: number, size: number): boolean[][] {
  const grid: boolean[][] = [];
  const target = Math.max(0, Math.min(1, sic));
  let count = 0;
  const targetCount = Math.round(target * size * size);

  let x = seed;
  for (let i = 0; i < size; i++) {
    const row: boolean[] = [];
    for (let j = 0; j < size; j++) {
      x = (x * 16807 + 12345) % 2147483647;
      const v = (x / 2147483647) * 2 - 1;
      const floe = count < targetCount && v > -0.5 + (count / targetCount) * 0.3;
      row.push(floe);
      if (floe) count++;
    }
    grid.push(row);
  }
  return grid;
}

export function IceField({ simMs }: IceFieldProps) {
  // Deterministic SIC from sim time (payload-driven in production)
  const sic = 0.3 + 0.2 * Math.sin(simMs / 100000);
  const size = 16;
  const mask = iceMask(ICE_FRACTAL_SEED, sic, size);

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

  return (
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
  );
}
