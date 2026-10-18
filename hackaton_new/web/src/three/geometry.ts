import * as THREE from "three";
import { mergeGeometries } from "three/examples/jsm/utils/BufferGeometryUtils.js";
import type { Network, XY } from "../types";

/**
 * Static city geometry, built once per network and shared by every 3D view.
 * Everything is built in SUMO's XY plane (metres, centred on the network) and laid flat with
 * rotateX(-PI/2): SUMO (x, y) -> three (x, 0, -y). Heights are three's +y.
 */

export interface CityGeometry {
  center: XY;
  size: number;
  ground: THREE.BufferGeometry;
  roads: THREE.BufferGeometry;
  sidewalks: THREE.BufferGeometry;
  markings: THREE.BufferGeometry;
  centerLines: THREE.BufferGeometry;
  zebras: THREE.BufferGeometry;
  buildings: THREE.BufferGeometry;
  buildingEdges: THREE.BufferGeometry;
}

const Y_ROAD = 0.02;
const Y_SIDEWALK = 0.14;
const Y_MARK = 0.05;

type P = [number, number];

function ribbon(points: P[], width: number, y: number): THREE.BufferGeometry | null {
  if (points.length < 2) return null;
  const half = width / 2;
  const pos: number[] = [];
  const idx: number[] = [];
  for (let i = 0; i < points.length; i++) {
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(points.length - 1, i + 1)];
    let dx = next[0] - prev[0];
    let dy = next[1] - prev[1];
    const len = Math.hypot(dx, dy) || 1;
    dx /= len;
    dy /= len;
    const [x, z] = points[i];
    pos.push(x - dy * half, z + dx * half, y, x + dy * half, z - dx * half, y);
    if (i > 0) {
      const a = (i - 1) * 2;
      idx.push(a, a + 1, a + 2, a + 1, a + 3, a + 2);
    }
  }
  const g = new THREE.BufferGeometry();
  g.setAttribute("position", new THREE.Float32BufferAttribute(pos, 3));
  g.setIndex(idx);
  return g;
}

function polygon(points: P[], y: number): THREE.BufferGeometry | null {
  if (points.length < 3) return null;
  const shape = new THREE.Shape(points.map(([x, z]) => new THREE.Vector2(x, z)));
  const g = new THREE.ShapeGeometry(shape);
  g.translate(0, 0, y);
  return g;
}

/** Splits a polyline into dash segments (on/off lengths in metres). */
function dashes(points: P[], on: number, off: number): P[][] {
  const out: P[][] = [];
  let cur: P[] = [];
  let drawing = true;
  let left = on;
  for (let i = 1; i < points.length; i++) {
    let [ax, ay] = points[i - 1];
    const [bx, by] = points[i];
    let seg = Math.hypot(bx - ax, by - ay);
    const ux = (bx - ax) / (seg || 1);
    const uy = (by - ay) / (seg || 1);
    while (seg > 1e-6) {
      const step = Math.min(seg, left);
      const nx = ax + ux * step;
      const ny = ay + uy * step;
      if (drawing) {
        if (!cur.length) cur.push([ax, ay]);
        cur.push([nx, ny]);
      }
      ax = nx;
      ay = ny;
      seg -= step;
      left -= step;
      if (left <= 1e-6) {
        if (drawing && cur.length) out.push(cur);
        cur = [];
        drawing = !drawing;
        left = drawing ? on : off;
      }
    }
  }
  if (drawing && cur.length > 1) out.push(cur);
  return out;
}

/** Polyline shifted sideways by d metres (positive = left of the travel direction). */
function offset(points: P[], d: number): P[] {
  return points.map((p, i) => {
    const prev = points[Math.max(0, i - 1)];
    const next = points[Math.min(points.length - 1, i + 1)];
    const dx = next[0] - prev[0];
    const dy = next[1] - prev[1];
    const len = Math.hypot(dx, dy) || 1;
    return [p[0] - (dy / len) * d, p[1] + (dx / len) * d];
  });
}

function merge(list: (THREE.BufferGeometry | null)[]): THREE.BufferGeometry {
  const parts = list.filter((g): g is THREE.BufferGeometry => !!g).map((g) => (g.index ? g.toNonIndexed() : g));
  for (const p of parts) for (const k of Object.keys(p.attributes)) if (k !== "position") p.deleteAttribute(k);
  const g = parts.length ? mergeGeometries(parts) ?? new THREE.BufferGeometry() : new THREE.BufferGeometry();
  g.rotateX(-Math.PI / 2);
  g.computeVertexNormals();
  return g;
}

const cache = new WeakMap<Network, CityGeometry>();

export function buildCity(net: Network): CityGeometry {
  const hit = cache.get(net);
  if (hit) return hit;
  const [x0, y0, x1, y1] = net.bounds;
  const center: XY = [(x0 + x1) / 2, (y0 + y1) / 2];
  const c = (p: XY): P => [p[0] - center[0], p[1] - center[1]];
  const size = Math.max(x1 - x0, y1 - y0);

  const roads: (THREE.BufferGeometry | null)[] = [];
  const sidewalks: (THREE.BufferGeometry | null)[] = [];
  const marks: (THREE.BufferGeometry | null)[] = [];
  const centers: (THREE.BufferGeometry | null)[] = [];
  const zebras: (THREE.BufferGeometry | null)[] = [];

  // highest road lane index per edge = lane next to the opposite direction
  const maxLane = new Map<string, number>();
  for (const l of net.lanes) {
    if (l.kind !== "road") continue;
    const edge = l.id.slice(0, l.id.lastIndexOf("_"));
    const i = Number(l.id.slice(l.id.lastIndexOf("_") + 1));
    maxLane.set(edge, Math.max(maxLane.get(edge) ?? -1, i));
  }

  for (const l of net.lanes) {
    const pts = l.shape.map(c);
    if (l.kind === "road") {
      roads.push(ribbon(pts, l.width + 0.05, Y_ROAD));
      const edge = l.id.slice(0, l.id.lastIndexOf("_"));
      const i = Number(l.id.slice(l.id.lastIndexOf("_") + 1));
      const border = offset(pts, l.width / 2);
      if (i === maxLane.get(edge)) centers.push(ribbon(border, 0.18, Y_MARK));
      else for (const d of dashes(border, 3, 6)) marks.push(ribbon(d, 0.14, Y_MARK));
    } else if (l.kind === "sidewalk") {
      sidewalks.push(ribbon(pts, l.width, Y_SIDEWALK));
    } else if (l.kind === "walkingarea") {
      sidewalks.push(polygon(pts, Y_SIDEWALK));
    } else if (l.kind === "crossing") {
      for (const d of dashes(pts, 0.55, 0.55)) zebras.push(ribbon(d, l.width * 0.9, Y_MARK));
    }
  }
  for (const j of net.junctions) roads.push(polygon(j.shape.map(c), Y_ROAD));

  const buildingParts: THREE.BufferGeometry[] = [];
  const edgeParts: THREE.BufferGeometry[] = [];
  for (const b of net.buildings) {
    const pts = b.shape.map(c);
    if (pts.length < 3) continue;
    const shape = new THREE.Shape(pts.map(([x, z]) => new THREE.Vector2(x, z)));
    const g = new THREE.ExtrudeGeometry(shape, { depth: b.height, bevelEnabled: false });
    buildingParts.push(g.index ? g.toNonIndexed() : g);
    const e = new THREE.EdgesGeometry(g, 30);
    edgeParts.push(e);
  }
  const buildings = buildingParts.length ? mergeGeometries(buildingParts.map((g) => {
    for (const k of Object.keys(g.attributes)) if (k !== "position" && k !== "normal") g.deleteAttribute(k);
    return g;
  })) ?? new THREE.BufferGeometry() : new THREE.BufferGeometry();
  buildings.rotateX(-Math.PI / 2);
  buildings.computeVertexNormals();
  const buildingEdges = edgeParts.length ? mergeGeometries(edgeParts) ?? new THREE.BufferGeometry() : new THREE.BufferGeometry();
  buildingEdges.rotateX(-Math.PI / 2);

  const ground = new THREE.PlaneGeometry(size * 4, size * 4);
  ground.rotateX(-Math.PI / 2);

  const city: CityGeometry = {
    center,
    size,
    ground,
    roads: merge(roads),
    sidewalks: merge(sidewalks),
    markings: merge(marks),
    centerLines: merge(centers),
    zebras: merge(zebras),
    buildings,
    buildingEdges,
  };
  cache.set(net, city);
  return city;
}

/** SUMO coordinates -> three world position. */
export function toWorld(center: XY, x: number, y: number, h = 0): [number, number, number] {
  return [x - center[0], h, -(y - center[1])];
}
