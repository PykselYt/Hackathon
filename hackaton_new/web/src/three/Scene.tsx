import { useMemo, useRef } from "react";
import { useFrame } from "@react-three/fiber";
import * as THREE from "three";
import type { Network, XY } from "../types";
import { buildCity, toWorld } from "./geometry";
import { BUS_LENGTH, CAR_LENGTH, busGeometry, carGeometry, pedestrianGeometry } from "./models";
import { frameStore, type Sampled, type Sim } from "./frameStore";

/* ---------- shared resources (one GPU upload, used by every view) ---------- */

const MAT = {
  ground: new THREE.MeshStandardMaterial({ color: "#f2f4f7", roughness: 1 }),
  road: new THREE.MeshStandardMaterial({ color: "#a7afbb", roughness: 0.95, side: THREE.DoubleSide }),
  sidewalk: new THREE.MeshStandardMaterial({ color: "#dde2e9", roughness: 1, side: THREE.DoubleSide }),
  marking: new THREE.MeshBasicMaterial({ color: "#ffffff", side: THREE.DoubleSide }),
  centerLine: new THREE.MeshBasicMaterial({ color: "#fafafa", side: THREE.DoubleSide }),
  zebra: new THREE.MeshBasicMaterial({ color: "#ffffff", side: THREE.DoubleSide }),
  building: new THREE.MeshStandardMaterial({ color: "#ffffff", roughness: 0.9, transparent: true, opacity: 0.92 }),
  buildingEdge: new THREE.LineBasicMaterial({ color: "#c9d1dc", transparent: true, opacity: 0.8 }),
  vehicle: new THREE.MeshStandardMaterial({ vertexColors: true, roughness: 0.5, metalness: 0.12 }),
  pole: new THREE.MeshStandardMaterial({ color: "#4a5160", roughness: 0.6 }),
  lamp: new THREE.MeshBasicMaterial({ toneMapped: false }),
  stopBar: new THREE.MeshBasicMaterial({ toneMapped: false, transparent: true, opacity: 0.9 }),
  crossingGlow: new THREE.MeshBasicMaterial({ transparent: true, opacity: 0.45, depthWrite: false, toneMapped: false }),
  detection: new THREE.LineBasicMaterial({ vertexColors: true, transparent: true, opacity: 0.95, toneMapped: false }),
};
const GEO = {
  car: carGeometry(),
  bus: busGeometry(),
  ped: pedestrianGeometry(),
  pole: new THREE.CylinderGeometry(0.09, 0.12, 4.2, 6).translate(0, 2.1, 0),
  lamp: new THREE.SphereGeometry(0.42, 12, 10),
  unitBox: new THREE.BoxGeometry(1, 1, 1),
  unitPlane: new THREE.PlaneGeometry(1, 1).rotateX(-Math.PI / 2),
};

const LIGHT_COLOR = {
  green: new THREE.Color("#22d36b"),
  yellow: new THREE.Color("#ffb020"),
  red: new THREE.Color("#ff3b30"),
};
const WHITE = new THREE.Color("#ffffff");
const STOPPED = new THREE.Color("#ff8a80");
const CROSS_GREEN = new THREE.Color("#34c759");
const CROSS_RED = new THREE.Color("#ffffff");

const MAX_CARS = 1500;
const MAX_BUSES = 80;
const MAX_PEDS = 800;

function lampColor(state: string | undefined, links: number[]): THREE.Color {
  if (!state) return LIGHT_COLOR.red;
  let best: keyof typeof LIGHT_COLOR = "red";
  for (const i of links) {
    const ch = state[i];
    if (ch === "G" || ch === "g") return LIGHT_COLOR.green;
    if (ch === "y" || ch === "Y") best = "yellow";
  }
  return LIGHT_COLOR[best];
}

/* ---------- static city ---------- */

export function StaticCity({ net }: { net: Network }) {
  const city = buildCity(net);
  return (
    <group>
      <mesh geometry={city.ground} material={MAT.ground} position={[0, -0.02, 0]} />
      <mesh geometry={city.roads} material={MAT.road} />
      <mesh geometry={city.sidewalks} material={MAT.sidewalk} />
      <mesh geometry={city.markings} material={MAT.marking} />
      <mesh geometry={city.centerLines} material={MAT.centerLine} />
      <mesh geometry={city.zebras} material={MAT.zebra} />
      <mesh geometry={city.buildings} material={MAT.building} />
      <lineSegments geometry={city.buildingEdges} material={MAT.buildingEdge} />
    </group>
  );
}

/* ---------- traffic ---------- */

const dummy = new THREE.Object3D();
const tint = new THREE.Color();

function place(mesh: THREE.InstancedMesh, i: number, center: XY, s: Sampled, length: number, zoomScale: number) {
  const a = (s.angle * Math.PI) / 180;
  // SUMO reports the front bumper; models are centred on their footprint
  const cx = s.x - Math.sin(a) * (length / 2);
  const cy = s.y - Math.cos(a) * (length / 2);
  dummy.position.set(cx - center[0], 0, -(cy - center[1]));
  dummy.rotation.set(0, -a, 0);
  const grow = Math.min(1, 0.35 + s.age / 1.2); // newcomers scale in
  dummy.scale.setScalar(grow * zoomScale);
  dummy.updateMatrix();
  mesh.setMatrixAt(i, dummy.matrix);
  // stopped vehicles fade towards red, so queues read at a glance
  const k = Math.max(0, Math.min(1, 1 - s.speed / 2.5));
  mesh.setColorAt(i, tint.copy(WHITE).lerp(STOPPED, k * 0.85));
}

export function Traffic({ net, sim, detection }: { net: Network; sim: Sim; detection: boolean }) {
  const center = buildCity(net).center;
  const cars = useRef<THREE.InstancedMesh>(null);
  const buses = useRef<THREE.InstancedMesh>(null);
  const peds = useRef<THREE.InstancedMesh>(null);
  const lines = useRef<THREE.LineSegments>(null);
  const vmap = useMemo(() => new Map<number, Sampled>(), []);
  const pmap = useMemo(() => new Map<number, Sampled>(), []);
  const boxGeo = useMemo(() => {
    const g = new THREE.BufferGeometry();
    const n = (MAX_CARS + MAX_BUSES + MAX_PEDS) * 24;
    g.setAttribute("position", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    g.setAttribute("color", new THREE.BufferAttribute(new Float32Array(n * 3), 3));
    return g;
  }, []);

  useFrame(({ camera }) => {
    if (!cars.current || !buses.current || !peds.current) return;
    // seen from high up, vehicles grow (up to 3x) so the overview still shows traffic
    const zoomScale = Math.min(3, Math.max(1, camera.position.y / 180));
    frameStore.vehicles(sim, vmap);
    frameStore.pedestrians(sim, pmap);
    let nc = 0;
    let nb = 0;
    let np = 0;
    for (const s of vmap.values()) {
      if (s.kind === 1) {
        if (nb < MAX_BUSES) place(buses.current, nb++, center, s, BUS_LENGTH, zoomScale);
      } else if (nc < MAX_CARS) place(cars.current, nc++, center, s, CAR_LENGTH, zoomScale);
    }
    for (const s of pmap.values()) {
      if (np >= MAX_PEDS) break;
      dummy.position.set(s.x - center[0], 0.14, -(s.y - center[1]));
      dummy.rotation.set(0, (-s.angle * Math.PI) / 180, 0);
      dummy.scale.setScalar(zoomScale);
      dummy.updateMatrix();
      peds.current.setMatrixAt(np++, dummy.matrix);
    }
    for (const [m, n] of [[cars.current, nc], [buses.current, nb], [peds.current, np]] as const) {
      m.count = n;
      m.instanceMatrix.needsUpdate = true;
      if (m.instanceColor) m.instanceColor.needsUpdate = true;
    }
    if (detection && lines.current) writeBoxes(boxGeo, center, vmap, pmap);
  });

  return (
    <group>
      <instancedMesh ref={cars} args={[GEO.car, MAT.vehicle, MAX_CARS]} frustumCulled={false} />
      <instancedMesh ref={buses} args={[GEO.bus, MAT.vehicle, MAX_BUSES]} frustumCulled={false} />
      <instancedMesh ref={peds} args={[GEO.ped, MAT.vehicle, MAX_PEDS]} frustumCulled={false} />
      {detection && <lineSegments ref={lines} geometry={boxGeo} material={MAT.detection} frustumCulled={false} />}
    </group>
  );
}

/* ---------- lidar-style detection boxes ---------- */

const BOX = {
  car: { w: 2.1, h: 1.7, l: 4.9, c: new THREE.Color("#00c2ff") },
  bus: { w: 2.8, h: 3.5, l: 12.4, c: new THREE.Color("#ffcc00") },
  ped: { w: 0.8, h: 1.9, l: 0.8, c: new THREE.Color("#ff2d95") },
};
const EDGES = [[0, 1], [1, 2], [2, 3], [3, 0], [4, 5], [5, 6], [6, 7], [7, 4], [0, 4], [1, 5], [2, 6], [3, 7]];

function writeBoxes(g: THREE.BufferGeometry, center: XY, vmap: Map<number, Sampled>, pmap: Map<number, Sampled>) {
  const pos = g.attributes.position.array as Float32Array;
  const col = g.attributes.color.array as Float32Array;
  let v = 0;
  const corners: number[][] = Array.from({ length: 8 }, () => [0, 0, 0]);
  const add = (s: Sampled, spec: (typeof BOX)["car"], frontAnchored: boolean) => {
    const a = (s.angle * Math.PI) / 180;
    const fx = Math.sin(a);
    const fy = Math.cos(a);
    const cx = frontAnchored ? s.x - fx * (spec.l / 2 - 0.2) : s.x;
    const cy = frontAnchored ? s.y - fy * (spec.l / 2 - 0.2) : s.y;
    let k = 0;
    for (const hz of [0, spec.h]) {
      for (const [sl, sw] of [[1, 1], [1, -1], [-1, -1], [-1, 1]]) {
        const x = cx + fx * (sl * spec.l) / 2 + fy * (sw * spec.w) / 2;
        const y = cy + fy * (sl * spec.l) / 2 - fx * (sw * spec.w) / 2;
        corners[k][0] = x - center[0];
        corners[k][1] = hz + 0.05;
        corners[k][2] = -(y - center[1]);
        k++;
      }
    }
    for (const [i, j] of EDGES) {
      for (const p of [corners[i], corners[j]]) {
        pos[v * 3] = p[0];
        pos[v * 3 + 1] = p[1];
        pos[v * 3 + 2] = p[2];
        col[v * 3] = spec.c.r;
        col[v * 3 + 1] = spec.c.g;
        col[v * 3 + 2] = spec.c.b;
        v++;
      }
    }
  };
  for (const s of vmap.values()) add(s, s.kind === 1 ? BOX.bus : BOX.car, true);
  for (const s of pmap.values()) add(s, BOX.ped, false);
  g.setDrawRange(0, v);
  g.attributes.position.needsUpdate = true;
  g.attributes.color.needsUpdate = true;
}

/** Expanding scan rings at every intersection (detection mode). */
export function ScanRings({ net }: { net: Network }) {
  const center = buildCity(net).center;
  const group = useRef<THREE.Group>(null);
  const rings = useMemo(
    () =>
      net.lights.map((l, i) => ({
        pos: toWorld(center, l.pos[0], l.pos[1], 0.08),
        mat: new THREE.MeshBasicMaterial({ color: "#00c2ff", transparent: true, depthWrite: false, toneMapped: false }),
        phase: i * 0.37,
      })),
    [net, center],
  );
  const geo = useMemo(() => new THREE.RingGeometry(0.94, 1, 64).rotateX(-Math.PI / 2), []);
  useFrame(({ clock }) => {
    group.current?.children.forEach((m, i) => {
      const k = ((clock.elapsedTime / 2.4 + rings[i].phase) % 1 + 1) % 1;
      m.scale.setScalar(4 + k * 46);
      rings[i].mat.opacity = 0.55 * (1 - k);
    });
  });
  return (
    <group ref={group}>
      {rings.map((r, i) => (
        <mesh key={i} geometry={geo} material={r.mat} position={r.pos} />
      ))}
    </group>
  );
}

/* ---------- traffic lights ---------- */

export function Signals({ net, sim }: { net: Network; sim: Sim }) {
  const center = buildCity(net).center;
  const signals = useMemo(
    () =>
      net.lights.flatMap((l) =>
        l.signals.map((s) => {
          const h = (s.angle * Math.PI) / 180; // math angle of the lane's last segment
          const dx = Math.cos(h);
          const dy = Math.sin(h);
          return {
            light: l.id,
            links: s.links,
            // pole on the right of the lane, just behind the stop line
            pole: toWorld(center, s.pos[0] + dy * 2.3 - dx * 0.8, s.pos[1] - dx * 2.3 - dy * 0.8),
            bar: toWorld(center, s.pos[0] - dx * 0.4, s.pos[1] - dy * 0.4, 0.07),
            rot: h + Math.PI / 2, // box x axis across the lane
          };
        }),
      ),
    [net, center],
  );
  const crossings = useMemo(
    () =>
      net.lights.flatMap((l) =>
        l.crossings.map((c) => {
          const [a, b] = [c.shape[0], c.shape[c.shape.length - 1]];
          const len = Math.hypot(b[0] - a[0], b[1] - a[1]);
          return {
            light: l.id,
            link: c.link,
            pos: toWorld(center, (a[0] + b[0]) / 2, (a[1] + b[1]) / 2, 0.08),
            rot: Math.atan2(b[1] - a[1], b[0] - a[0]), // plane x axis along the crossing
            len,
            width: c.width,
          };
        }),
      ),
    [net, center],
  );
  const poles = useRef<THREE.InstancedMesh>(null);
  const lamps = useRef<THREE.InstancedMesh>(null);
  const bars = useRef<THREE.InstancedMesh>(null);
  const glows = useRef<THREE.InstancedMesh>(null);

  const ready = useRef(false); // static transforms are written on the first frame, once the meshes exist

  useFrame(() => {
    if (!poles.current || !lamps.current || !bars.current || !glows.current) return;
    if (!ready.current) {
      signals.forEach((s, i) => {
        dummy.position.set(...s.pole);
        dummy.rotation.set(0, 0, 0);
        dummy.scale.setScalar(1);
        dummy.updateMatrix();
        poles.current!.setMatrixAt(i, dummy.matrix);
        dummy.position.set(s.pole[0], 4.35, s.pole[2]);
        dummy.updateMatrix();
        lamps.current!.setMatrixAt(i, dummy.matrix);
        dummy.position.set(...s.bar);
        dummy.rotation.set(0, s.rot, 0);
        dummy.scale.set(3.1, 0.06, 0.55);
        dummy.updateMatrix();
        bars.current!.setMatrixAt(i, dummy.matrix);
      });
      crossings.forEach((c, i) => {
        dummy.position.set(...c.pos);
        dummy.rotation.set(0, c.rot, 0);
        dummy.scale.set(c.len, 1, c.width + 0.4);
        dummy.updateMatrix();
        glows.current!.setMatrixAt(i, dummy.matrix);
      });
      for (const m of [poles.current, lamps.current, bars.current, glows.current]) m.instanceMatrix.needsUpdate = true;
      ready.current = true;
    }
    const states = frameStore.lights(sim);
    signals.forEach((s, i) => {
      const c = lampColor(states[s.light], s.links);
      lamps.current!.setColorAt(i, c);
      bars.current!.setColorAt(i, c);
    });
    crossings.forEach((c, i) => {
      const ch = states[c.light]?.[c.link];
      glows.current!.setColorAt(i, ch === "G" || ch === "g" ? CROSS_GREEN : CROSS_RED);
    });
    for (const m of [lamps.current, bars.current, glows.current]) if (m.instanceColor) m.instanceColor.needsUpdate = true;
  });

  return (
    <group>
      <instancedMesh ref={poles} args={[GEO.pole, MAT.pole, signals.length]} frustumCulled={false} />
      <instancedMesh ref={lamps} args={[GEO.lamp, MAT.lamp, signals.length]} frustumCulled={false} />
      <instancedMesh ref={bars} args={[GEO.unitBox, MAT.stopBar, signals.length]} frustumCulled={false} />
      <instancedMesh ref={glows} args={[GEO.unitPlane, MAT.crossingGlow, Math.max(1, crossings.length)]} frustumCulled={false} />
    </group>
  );
}

