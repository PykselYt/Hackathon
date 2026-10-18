// Data contracts between modules (PLAN.md §5). Mirror of server/schemas.py — change both together.

export type PhaseState = "green" | "yellow" | "all_red";
export type EspMode = "AI" | "AVARIE" | "NECONECTAT";
export type VisionSource = "file" | "screen" | "snapshot" | "stream";
export type EventKind =
  | "rush_hour" | "rush_end" | "spillback_hold" | "esp_online" | "esp_offline"
  | "heartbeat_paused" | "heartbeat_resumed" | "controller_changed" | "reset"
  | "vision_online" | "vision_offline";
export type EventLevel = "info" | "warn" | "error";
export type ControllerName = "ppo" | "max_pressure" | "fixed";

// §5.1 WebSocket tick
export interface SimMetrics {
  avg_wait_s: number;
  queue_veh: number;
  throughput_vph: number;
  trip_wait_s: number;
}

export interface IntersectionState {
  id: string;
  green_phase: number;
  phase_label: string;
  state: PhaseState;
  time_in_phase_s: number;
  queues: Record<string, number>; // approach -> halted vehicles ("N", "S", "E", "V")
  hold: boolean;
}

export interface EspStatus {
  online: boolean;
  last_ack_ms: number | null;
  mode: EspMode;
}

export interface VisionStatus {
  online: boolean;
  source: VisionSource | null;
  queues: Record<string, number>;
  avg_stop_s: number | null;
}

export interface Tick {
  type: "tick";
  sim_time: number;
  controller: string;
  rush_active: boolean;
  fix: SimMetrics;
  ai: SimMetrics;
  improvement_pct: number | null;
  intersections: IntersectionState[];
  esp: EspStatus;
  vision: VisionStatus;
}

// §5.7 WebSocket frame: positions for the 3D map, every simulated second
export type VehicleRow = [id: number, x: number, y: number, angle: number, kind: number, speed: number];
export type PedRow = [id: number, x: number, y: number, angle: number];

export interface SimFrame {
  veh: VehicleRow[]; // kind: 0 car, 1 bus
  ped: PedRow[];
  tls: Record<string, string>; // light id -> SUMO state string, one char per link index
}

export interface Frame {
  type: "frame";
  sim_time: number;
  fix: SimFrame;
  ai: SimFrame;
}

// §5.8 GET /api/network: static geometry for the 3D map (SUMO coordinates, metres)
export type XY = [number, number];
export interface NetLane { id: string; kind: "road" | "sidewalk" | "crossing" | "walkingarea"; shape: XY[]; width: number }
export interface NetSignal { lane: string; pos: XY; angle: number; links: number[] }
export interface NetCrossing { id: string; shape: XY[]; width: number; link: number }
export interface NetApproach { dir: string; name: string; edge: string; open: boolean[] }
export interface NetLight {
  id: string;
  pos: XY;
  labels: string[];
  signals: NetSignal[];
  crossings: NetCrossing[];
  approaches: NetApproach[];
}
export interface NetJunction { id: string; shape: XY[]; tls: boolean }
export interface NetBuilding { shape: XY[]; height: number } // OSM footprint, height in metres
export interface Network {
  bounds: [number, number, number, number];
  lanes: NetLane[];
  junctions: NetJunction[];
  lights: NetLight[];
  buildings: NetBuilding[];
}

// §5.9 GET /api/results: rows of results/eval_summary.csv (ai/evaluate.py)
export interface EvalRow {
  variant: string;
  scenario: "normal" | "rush";
  n: number;
  mean_wait_s: number;
  mean_wait_s_sd: number;
  mean_duration_s: number;
  arrived_per_h: number;
  max_queue: number;
  vs_fixed_program_pct: number | null;
  vs_actuated_pct: number | null;
}

export interface History {
  type: "history";
  ticks: Tick[];
}

// §5.2 WebSocket event
export interface SimEvent {
  type: "event";
  sim_time: number;
  kind: EventKind;
  level: EventLevel;
  msg: string;
}

export type WsMessage = Tick | History | SimEvent | Frame;

// §5.3 REST bodies
export interface RushRequest { vehicles?: number }
export interface ControllerRequest { name: ControllerName }
export interface HeartbeatRequest { enabled: boolean }
export interface SpawnRequest { approach: string }
