import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import { RoundedBoxGeometry } from "three/examples/jsm/geometries/RoundedBoxGeometry.js";

/**
 * Low-poly models, one geometry each with per-vertex colours so a whole fleet is a single InstancedMesh.
 * Models face -z (SUMO north) with their origin at the centre of the footprint, on the ground.
 * Instance colours multiply the vertex colours: white keeps the model as is, red tints a stopped car.
 */

export const CAR_LENGTH = 4.5;
export const BUS_LENGTH = 12;

function part(geo: THREE.BufferGeometry, color: string, x: number, y: number, z: number): THREE.BufferGeometry {
  const g = geo.index ? geo.toNonIndexed() : geo.clone();
  g.translate(x, y, z);
  const c = new THREE.Color(color);
  const n = g.attributes.position.count;
  const colors = new Float32Array(n * 3);
  for (let i = 0; i < n; i++) colors.set([c.r, c.g, c.b], i * 3);
  g.setAttribute("color", new THREE.BufferAttribute(colors, 3));
  for (const k of Object.keys(g.attributes)) if (!["position", "normal", "color"].includes(k)) g.deleteAttribute(k);
  return g;
}

function wheels(w: number, l: number, r: number, color: string): THREE.BufferGeometry[] {
  const wheel = new THREE.CylinderGeometry(r, r, 0.28, 12);
  wheel.rotateZ(Math.PI / 2);
  const out: THREE.BufferGeometry[] = [];
  for (const sx of [-1, 1]) for (const sz of [-1, 1]) out.push(part(wheel, color, (sx * w) / 2, r, (sz * l) / 2));
  return out;
}

export function carGeometry(): THREE.BufferGeometry {
  const body = new RoundedBoxGeometry(1.82, 0.72, CAR_LENGTH, 2, 0.22);
  const cabin = new RoundedBoxGeometry(1.5, 0.52, 2.0, 2, 0.2);
  const lamp = new THREE.BoxGeometry(0.42, 0.14, 0.06);
  const g = mergeGeometries([
    part(body, "#f6f7f9", 0, 0.62, 0),
    part(cabin, "#5b6a7a", 0, 1.2, 0.3),
    ...wheels(1.62, CAR_LENGTH * 0.62, 0.33, "#1c1f26"),
    part(lamp, "#ff3b30", -0.6, 0.78, CAR_LENGTH / 2),
    part(lamp, "#ff3b30", 0.6, 0.78, CAR_LENGTH / 2),
    part(lamp, "#fff6d5", -0.6, 0.72, -CAR_LENGTH / 2),
    part(lamp, "#fff6d5", 0.6, 0.72, -CAR_LENGTH / 2),
  ]);
  return g!;
}

export function busGeometry(): THREE.BufferGeometry {
  const body = new RoundedBoxGeometry(2.5, 2.7, BUS_LENGTH, 2, 0.3);
  const windows = new THREE.BoxGeometry(2.54, 0.85, BUS_LENGTH - 1.6);
  const roof = new THREE.BoxGeometry(1.6, 0.25, BUS_LENGTH * 0.45);
  const g = mergeGeometries([
    part(body, "#0a84ff", 0, 1.75, 0),
    part(windows, "#1d2a3a", 0, 2.25, 0.2),
    part(roof, "#e9eef5", 0, 3.2, 0.5),
    ...wheels(2.3, BUS_LENGTH * 0.62, 0.48, "#1c1f26"),
  ]);
  return g!;
}

export function pedestrianGeometry(): THREE.BufferGeometry {
  const body = new THREE.CapsuleGeometry(0.22, 0.75, 4, 8);
  const head = new THREE.SphereGeometry(0.16, 10, 8);
  const legs = new THREE.CapsuleGeometry(0.15, 0.55, 3, 6);
  const g = mergeGeometries([
    part(legs, "#3a4252", 0, 0.42, 0),
    part(body, "#ff9500", 0, 1.08, 0),
    part(head, "#f1c9a5", 0, 1.68, 0),
  ]);
  return g!;
}
