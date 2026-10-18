import { useEffect, useMemo, useRef } from "react";
import { createPortal } from "react-dom";
import { useFrame, useThree } from "@react-three/fiber";
import { MapControls, PerspectiveCamera, View } from "@react-three/drei";
import * as THREE from "three";
import type { MapControls as MapControlsImpl } from "three-stdlib";
import type { IntersectionState, Network } from "../types";
import { buildCity, toWorld } from "./geometry";
import type { Sim } from "./frameStore";
import { ScanRings, Signals, StaticCity, Traffic } from "./Scene";

/** Shared camera pose: views in the same group follow whichever one the user is moving. */
export class CameraSync {
  pos = new THREE.Vector3();
  target = new THREE.Vector3();
  rev = 0;
  owner = "";
}

export type Focus = "all" | "camera" | string; // "camera" = the WebcamRomania viewpoint over A

export const OVERLAY_ID = "overlay3d";

function shot(net: Network, focus: Focus): { pos: THREE.Vector3; target: THREE.Vector3 } {
  const city = buildCity(net);
  const lights = net.lights.map((l) => toWorld(city.center, l.pos[0], l.pos[1]));
  if (focus === "all") {
    // frame the signalised junctions, not the whole neighbourhood
    const xs = lights.map((p) => p[0]);
    const zs = lights.map((p) => p[2]);
    const cx = (Math.min(...xs) + Math.max(...xs)) / 2;
    const cz = (Math.min(...zs) + Math.max(...zs)) / 2;
    const span = Math.max(Math.max(...xs) - Math.min(...xs), Math.max(...zs) - Math.min(...zs));
    const d = span * 1.05;
    return { pos: new THREE.Vector3(cx - d * 0.1, d * 0.78, cz + d * 0.62), target: new THREE.Vector3(cx, 0, cz) };
  }
  const id = focus === "camera" ? "A" : focus;
  const i = Math.max(0, net.lights.findIndex((l) => l.id === id));
  const [x, , z] = lights[i];
  if (focus === "camera") {
    // Grand Hotel Traian, west of the square, looking along the boulevard
    return { pos: new THREE.Vector3(x - 95, 34, z - 32), target: new THREE.Vector3(x + 40, 0, z + 12) };
  }
  return { pos: new THREE.Vector3(x - 55, 85, z + 80), target: new THREE.Vector3(x, 0, z) };
}

function CameraRig({ net, focus, sync, id, cameraOut }: {
  net: Network; focus: Focus; sync?: CameraSync; id: string; cameraOut: React.MutableRefObject<THREE.Camera | null>;
}) {
  const controls = useRef<MapControlsImpl>(null);
  const camera = useThree((s) => s.camera);
  const flight = useRef<{ pos: THREE.Vector3; target: THREE.Vector3 } | null>(null);
  const userActive = useRef(false);
  const lastRev = useRef(0); // rev 0 = nobody has moved the group yet: nothing to copy
  const releaseTimer = useRef<number>();

  useEffect(() => {
    flight.current = shot(net, focus);
  }, [net, focus]);

  useEffect(() => {
    const c = controls.current;
    if (!c) return;
    const start = () => {
      userActive.current = true;
      flight.current = null; // the user takes over
      window.clearTimeout(releaseTimer.current);
    };
    const end = () => {
      releaseTimer.current = window.setTimeout(() => (userActive.current = false), 900); // damping still moves
    };
    const change = () => {
      if (sync && userActive.current) {
        sync.pos.copy(camera.position);
        sync.target.copy(c.target);
        sync.rev++;
        sync.owner = id;
        lastRev.current = sync.rev;
      }
    };
    c.addEventListener("start", start);
    c.addEventListener("end", end);
    c.addEventListener("change", change);
    return () => {
      c.removeEventListener("start", start);
      c.removeEventListener("end", end);
      c.removeEventListener("change", change);
    };
  }, [camera, sync, id]);

  useFrame((_, dt) => {
    cameraOut.current = camera;
    const c = controls.current;
    if (!c) return;
    if (flight.current) {
      const k = 1 - Math.exp(-dt * 3.2); // critically damped glide, frame-rate independent
      camera.position.lerp(flight.current.pos, k);
      c.target.lerp(flight.current.target, k);
      c.update();
      if (camera.position.distanceTo(flight.current.pos) < 0.3 && c.target.distanceTo(flight.current.target) < 0.3) {
        flight.current = null;
      }
    } else if (sync && sync.rev > lastRev.current && sync.owner !== id && !userActive.current) {
      camera.position.copy(sync.pos);
      c.target.copy(sync.target);
      c.update();
      lastRev.current = sync.rev;
    }
  });

  return (
    <MapControls
      ref={controls}
      makeDefault
      enableDamping
      dampingFactor={0.08}
      maxPolarAngle={Math.PI * 0.46}
      minDistance={25}
      maxDistance={2200}
      screenSpacePanning={false}
    />
  );
}

const STATE_DOT: Record<string, string> = { green: "#1f9d55", yellow: "#ff9500", all_red: "#d93a30" };
const tmp = new THREE.Vector3();

/**
 * Intersection badges, drawn in a DOM layer above the WebGL canvas. Positions are projected from the
 * view's camera every animation frame and hidden when they leave the view's rectangle.
 */
function LabelsOverlay({ net, intersections, onPick, cameraRef, viewRef }: {
  net: Network;
  intersections: IntersectionState[];
  onPick?: (id: string) => void;
  cameraRef: React.MutableRefObject<THREE.Camera | null>;
  viewRef: React.MutableRefObject<HTMLElement | null>;
}) {
  const refs = useRef<(HTMLButtonElement | null)[]>([]);
  const points = useMemo(() => {
    const c = buildCity(net).center;
    return net.lights.map((l) => toWorld(c, l.pos[0], l.pos[1], 14));
  }, [net]);
  useEffect(() => {
    let raf = 0;
    const loop = () => {
      const cam = cameraRef.current;
      const view = viewRef.current;
      if (cam && view) {
        const r = view.getBoundingClientRect();
        points.forEach((p, i) => {
          const el = refs.current[i];
          if (!el) return;
          tmp.set(p[0], p[1], p[2]).project(cam);
          const x = r.left + ((tmp.x + 1) / 2) * r.width;
          const y = r.top + ((1 - tmp.y) / 2) * r.height;
          const inside = tmp.z < 1 && x > r.left + 30 && x < r.right - 30 && y > r.top + 14 && y < r.bottom - 14;
          el.style.transform = `translate(${x}px, ${y}px) translate(-50%, -50%)`;
          el.style.opacity = inside ? "1" : "0";
          el.style.pointerEvents = inside ? "auto" : "none";
        });
      }
      raf = requestAnimationFrame(loop);
    };
    raf = requestAnimationFrame(loop);
    return () => cancelAnimationFrame(raf);
  }, [points, cameraRef, viewRef]);
  const host = document.getElementById(OVERLAY_ID);
  if (!host) return null;
  return createPortal(
    <>
      {net.lights.map((l, i) => {
        const s = intersections.find((x) => x.id === l.id);
        const q = s ? Object.values(s.queues).reduce((a, b) => a + b, 0) : 0;
        return (
          <button
            key={l.id}
            ref={(el) => (refs.current[i] = el)}
            onClick={() => onPick?.(l.id)}
            style={{ opacity: 0 }}
            className="absolute left-0 top-0 flex items-center gap-1.5 whitespace-nowrap rounded-full bg-white/92 px-2 py-1 text-[12px] font-semibold text-foreground shadow-pop ring-1 ring-black/5 backdrop-blur transition-opacity duration-300 hover:bg-white"
          >
            <span className="grid h-5 w-5 place-items-center rounded-full bg-[#0b1c3e] text-[11px] text-white">{l.id}</span>
            {s && <span className="h-2 w-2 rounded-full transition-colors duration-300" style={{ background: STATE_DOT[s.state] }} />}
            <span className="font-medium text-muted-foreground">{s?.phase_label ?? l.labels[0]}</span>
            <span className="tabular-nums">{q}</span>
          </button>
        );
      })}
    </>,
    host,
  );
}

interface Props {
  net: Network;
  sim: Sim;
  focus: Focus;
  detection?: boolean;
  labels?: IntersectionState[];
  onPick?: (id: string) => void;
  sync?: CameraSync;
  className?: string;
}

/** One 3D viewport; any number of them share the app's single WebGL canvas (see Stage). */
export function MapView({ net, sim, focus, detection = false, labels, onPick, sync, className }: Props) {
  const id = useMemo(() => Math.random().toString(36).slice(2), []);
  const start = useMemo(() => shot(net, focus), [net]); // eslint-disable-line react-hooks/exhaustive-deps
  const cameraRef = useRef<THREE.Camera | null>(null);
  const viewRef = useRef<HTMLElement | null>(null);
  return (
    <>
      <View className={className} ref={viewRef as React.Ref<HTMLElement>}>
        <color attach="background" args={["#e9eef5"]} />
        <fog attach="fog" args={["#e9eef5", 900, 2600]} />
        <PerspectiveCamera makeDefault fov={38} near={1} far={6000} position={start.pos} />
        <CameraRig net={net} focus={focus} sync={sync} id={id} cameraOut={cameraRef} />
        <hemisphereLight args={["#ffffff", "#c2cad6", 1.2]} />
        <directionalLight position={[-300, 600, 250]} intensity={1.55} />
        <directionalLight position={[400, 300, -300]} intensity={0.35} />
        <StaticCity net={net} />
        <Signals net={net} sim={sim} />
        <Traffic net={net} sim={sim} detection={detection} />
        {detection && <ScanRings net={net} />}
      </View>
      {labels && <LabelsOverlay net={net} intersections={labels} onPick={onPick} cameraRef={cameraRef} viewRef={viewRef} />}
    </>
  );
}
