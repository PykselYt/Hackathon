import type { Frame, PedRow, SimFrame, VehicleRow } from "../types";

/**
 * Buffer of recent frames + a smoothed display clock, read every animation frame by the 3D views.
 * Frames arrive twice a second; the views render slightly in the past (DELAY_S simulated seconds) and
 * interpolate between the two frames around the display time, so motion stays continuous even when a
 * packet is late.
 */
const MAX_FRAMES = 8;
const DELAY_S = 1.2; // simulated seconds the picture lags behind the newest frame
const CLOCK_SMOOTHING = 0.08;

export type Sim = "fix" | "ai";

interface Indexed {
  t: number;
  veh: Map<number, VehicleRow>;
  ped: Map<number, PedRow>;
  tls: Record<string, string>;
}

export interface Sampled {
  x: number;
  y: number;
  angle: number;
  kind: number;
  speed: number;
  age: number; // simulated seconds since the object first appeared (for fade-in)
}

function index(sim: SimFrame, t: number): Indexed {
  return {
    t,
    veh: new Map(sim.veh.map((r) => [r[0], r])),
    ped: new Map(sim.ped.map((r) => [r[0], r])),
    tls: sim.tls,
  };
}

const lerp = (a: number, b: number, k: number) => a + (b - a) * k;
const lerpAngle = (a: number, b: number, k: number) => {
  const d = ((b - a + 540) % 360) - 180;
  return a + d * k;
};

class FrameStore {
  private frames: Record<Sim, Indexed[]> = { fix: [], ai: [] };
  private firstSeen = new Map<number, number>();
  private offset: number | null = null; // sim_time - wallSeconds * speed
  speed = 2;
  version = 0;

  push(f: Frame) {
    const last = this.frames.ai.at(-1);
    if (last && f.sim_time < last.t) this.clear(); // simulation was reset
    for (const sim of ["fix", "ai"] as Sim[]) {
      const buf = this.frames[sim];
      buf.push(index(f[sim], f.sim_time));
      if (buf.length > MAX_FRAMES) buf.shift();
    }
    for (const r of f.ai.veh) if (!this.firstSeen.has(r[0])) this.firstSeen.set(r[0], f.sim_time);
    for (const r of f.fix.veh) if (!this.firstSeen.has(r[0])) this.firstSeen.set(r[0], f.sim_time);
    const wall = performance.now() / 1000;
    const target = f.sim_time - wall * this.speed;
    // the clock follows the newest frame but ignores network jitter
    this.offset = this.offset === null ? target : this.offset + (target - this.offset) * CLOCK_SMOOTHING;
    if (Math.abs(target - this.offset) > 3) this.offset = target;
    this.version++;
  }

  clear() {
    this.frames = { fix: [], ai: [] };
    this.firstSeen.clear();
    this.offset = null;
  }

  /** Simulated time currently on screen. */
  displayTime(): number | null {
    if (this.offset === null) return null;
    const newest = this.frames.ai.at(-1)?.t ?? 0;
    const t = (performance.now() / 1000) * this.speed + this.offset - DELAY_S;
    return Math.min(t, newest);
  }

  private around(sim: Sim, t: number): [Indexed, Indexed, number] | null {
    const buf = this.frames[sim];
    if (!buf.length) return null;
    if (t <= buf[0].t) return [buf[0], buf[0], 0];
    for (let i = buf.length - 1; i > 0; i--) {
      if (buf[i - 1].t <= t) {
        const a = buf[i - 1];
        const b = buf[i];
        const k = b.t > a.t ? Math.min(1, (t - a.t) / (b.t - a.t)) : 1;
        return [a, b, k];
      }
    }
    const last = buf[buf.length - 1];
    return [last, last, 0];
  }

  /** Interpolated vehicles of one simulation at the display time. */
  vehicles(sim: Sim, out: Map<number, Sampled>): Map<number, Sampled> {
    out.clear();
    const t = this.displayTime();
    const pair = t === null ? null : this.around(sim, t);
    if (!pair || t === null) return out;
    const [a, b, k] = pair;
    for (const [id, rb] of b.veh) {
      const ra = a.veh.get(id);
      const age = t - (this.firstSeen.get(id) ?? t);
      if (ra) {
        out.set(id, { x: lerp(ra[1], rb[1], k), y: lerp(ra[2], rb[2], k), angle: lerpAngle(ra[3], rb[3], k), kind: rb[4], speed: lerp(ra[5], rb[5], k), age });
      } else if (k > 0.05) {
        out.set(id, { x: rb[1], y: rb[2], angle: rb[3], kind: rb[4], speed: rb[5], age: 0 });
      }
    }
    return out;
  }

  pedestrians(sim: Sim, out: Map<number, Sampled>): Map<number, Sampled> {
    out.clear();
    const t = this.displayTime();
    const pair = t === null ? null : this.around(sim, t);
    if (!pair) return out;
    const [a, b, k] = pair;
    for (const [id, rb] of b.ped) {
      const ra = a.ped.get(id);
      if (ra) out.set(id, { x: lerp(ra[1], rb[1], k), y: lerp(ra[2], rb[2], k), angle: lerpAngle(ra[3], rb[3], k), kind: 2, speed: 1, age: 10 });
    }
    return out;
  }

  /** Light states of the frame closest to the display time (lights switch, they do not interpolate). */
  lights(sim: Sim): Record<string, string> {
    const t = this.displayTime();
    const pair = t === null ? null : this.around(sim, t);
    if (!pair) return {};
    const [a, b, k] = pair;
    return k < 0.5 ? a.tls : b.tls;
  }
}

export const frameStore = new FrameStore();
