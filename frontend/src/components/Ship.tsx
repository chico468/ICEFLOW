/**
 * Ship: procedural icebreaker/research vessel in side third-person view.
 *
 * The ship moves left to right while the world scrolls at SOG. A procedural
 * hull is used (no external asset download), keeping the bundle under budget.
 * No live GPS claim: position comes from the sim clock / timeline.
 */
import { useEffect, useRef } from 'react';
import { useFrame } from '@react-three/fiber';
import * as THREE from 'three';

interface ShipProps {
  speed: number;
}

export function Ship({ speed }: ShipProps) {
  const meshRef = useRef<THREE.Group | null>(null);

  // Build a procedural hull: elongated rounded box with superstructure
  useEffect(() => {
    if (!meshRef.current) return;

    const group = meshRef.current;

    // Hull
    const hullGeo = new THREE.CylinderGeometry(0.6, 0.6, 8, 16, 1, true, 0, Math.PI);
    hullGeo.rotateZ(Math.PI / 2);
    const hullMat = new THREE.MeshStandardMaterial({ color: 0x204060, roughness: 0.6 });
    const hull = new THREE.Mesh(hullGeo, hullMat);
    hull.castShadow = true;
    hull.receiveShadow = true;
    group.add(hull);

    // Superstructure
    const superGeo = new THREE.BoxGeometry(1.2, 1.0, 2.5);
    const superMat = new THREE.MeshStandardMaterial({ color: 0x405060, roughness: 0.5 });
    const superstructure = new THREE.Mesh(superGeo, superMat);
    superstructure.position.set(0, 1.2, 0);
    superstructure.castShadow = true;
    group.add(superstructure);

    // Bridge windows
    const winGeo = new THREE.PlaneGeometry(0.8, 0.6);
    const winMat = new THREE.MeshBasicMaterial({ color: 0x40a0d0, transparent: true, opacity: 0.8 });
    const win = new THREE.Mesh(winGeo, winMat);
    win.position.set(0, 1.2, 1.3);
    group.add(win);

    // Deck details
    const deckGeo = new THREE.BoxGeometry(0.9, 0.1, 7.5);
    const deckMat = new THREE.MeshStandardMaterial({ color: 0x304050 });
    const deck = new THREE.Mesh(deckGeo, deckMat);
    deck.position.set(0, 0.55, 0);
    group.add(deck);
  }, []);

  // World scrolls at SOG: ship stays centered, world moves backward
  useFrame((_state, delta) => {
    if (!meshRef.current) return;
    const scrollSpeed = (10 / 20) * delta; // world scroll speed proportional to SOG
    meshRef.current.position.x += scrollSpeed * speed * 0.5;
  });

  return (
    <group ref={meshRef} position={[0, 0, 0]}>
      <mesh
        geometry={new THREE.CylinderGeometry(0.6, 0.6, 8, 16, 1, true, 0, Math.PI)}
        material={new THREE.MeshStandardMaterial({ color: 0x204060, roughness: 0.6 })}
      />
    </group>
  );
}
