import { useEffect, useReducer } from "react";
import type { SimEvent, Tick, WsMessage } from "../types";
import { frameStore } from "../three/frameStore";

const MAX_TICKS = 900; // = server.history_points, one tick per simulated second
const MAX_EVENTS = 6;
const RETRY_MS = [1000, 2000, 4000];

export type Connection = "connecting" | "open" | "closed";

export interface Telemetry {
  ticks: Tick[];
  events: SimEvent[];
  connection: Connection;
  /** vehicle-seconds of standing in queue avoided by the AI since the last reset (1 tick = 1 simulated s) */
  savedVehSeconds: number;
}

const saving = (t: Tick) => t.fix.queue_veh - t.ai.queue_veh;

type Action =
  | { kind: "message"; msg: WsMessage }
  | { kind: "connection"; connection: Connection };

function reducer(state: Telemetry, action: Action): Telemetry {
  if (action.kind === "connection") return { ...state, connection: action.connection };
  const msg = action.msg;
  switch (msg.type) {
    case "history":
      // the server replays its recent events right after the history
      return {
        ...state,
        ticks: msg.ticks.slice(-MAX_TICKS),
        events: [],
        savedVehSeconds: msg.ticks.reduce((a, t) => a + saving(t), 0),
      };
    case "tick": {
      const ticks = state.ticks.length >= MAX_TICKS ? state.ticks.slice(1) : state.ticks.slice();
      const restarted = (state.ticks.at(-1)?.sim_time ?? 0) > msg.sim_time;
      ticks.push(msg);
      return { ...state, ticks, savedVehSeconds: (restarted ? 0 : state.savedVehSeconds) + saving(msg) };
    }
    case "frame":
      return state;
    case "event": {
      const events = [msg, ...state.events].slice(0, MAX_EVENTS);
      // reset clears the chart; the server clears its history too
      return msg.kind === "reset" ? { ...state, ticks: [], events, savedVehSeconds: 0 } : { ...state, events };
    }
  }
}

export function useTelemetry(): Telemetry {
  const [state, dispatch] = useReducer(reducer, { ticks: [], events: [], connection: "connecting", savedVehSeconds: 0 });

  useEffect(() => {
    let ws: WebSocket | null = null;
    let attempt = 0;
    let timer: number | undefined;
    let disposed = false;

    const connect = () => {
      const proto = location.protocol === "https:" ? "wss" : "ws";
      ws = new WebSocket(`${proto}://${location.host}/ws`);
      dispatch({ kind: "connection", connection: "connecting" });
      ws.onopen = () => {
        attempt = 0;
        dispatch({ kind: "connection", connection: "open" });
      };
      ws.onmessage = (e) => {
        const msg = JSON.parse(e.data) as WsMessage;
        // positions go straight to the 3D frame buffer, never through React state (2 Hz x hundreds of rows)
        if (msg.type === "frame") frameStore.push(msg);
        else dispatch({ kind: "message", msg });
      };
      ws.onclose = () => {
        if (disposed) return;
        dispatch({ kind: "connection", connection: "closed" });
        timer = window.setTimeout(connect, RETRY_MS[Math.min(attempt++, RETRY_MS.length - 1)]);
      };
    };
    connect();

    return () => {
      disposed = true;
      window.clearTimeout(timer);
      ws?.close();
    };
  }, []);

  return state;
}
