import { useCallback, useEffect, useRef, useState } from "react";
import { useTelemetry } from "./hooks/useTelemetry";
import { useNetwork } from "./hooks/useNetwork";
import * as api from "./api";
import type { ControllerName } from "./types";
import { PAGES, StatusBar, type Page } from "./components/StatusBar";
import { ControlPanel } from "./components/ControlPanel";
import { Stage } from "./three/Stage";
import { frameStore } from "./three/frameStore";
import { OVERLAY_ID } from "./three/MapView";
import { LivePage } from "./pages/LivePage";
import { PanelPage } from "./pages/PanelPage";
import { JunctionsPage } from "./pages/JunctionsPage";
import { ResultsPage } from "./pages/ResultsPage";

const DEFAULT_STREAM_PORT = 8001;

export default function App() {
  const { ticks, events, connection, savedVehSeconds } = useTelemetry();
  const net = useNetwork();
  const tick = ticks.at(-1);
  const [page, setPage] = useState<Page>("live");
  const [detection, setDetection] = useState(false);
  const [heartbeatOff, setHeartbeatOff] = useState(false);
  const heartbeatRef = useRef(heartbeatOff);
  heartbeatRef.current = heartbeatOff;
  const [streamPort, setStreamPort] = useState(DEFAULT_STREAM_PORT);

  useEffect(() => {
    fetch("/api/state")
      .then((r) => r.json())
      .then((s) => {
        if (s?.config?.vision?.stream_port) setStreamPort(s.config.vision.stream_port);
        if (s?.config?.sim?.speed) frameStore.speed = s.config.sim.speed;
      })
      .catch(() => {});
  }, []);

  // the server is the source of truth for the heartbeat switch (survives a page refresh)
  useEffect(() => {
    const last = events.find((e) => e.kind === "heartbeat_paused" || e.kind === "heartbeat_resumed");
    if (last) setHeartbeatOff(last.kind === "heartbeat_paused");
  }, [events]);

  const call = (p: Promise<void>) => p.catch((e) => console.error(e));
  const onRush = useCallback(() => call(api.rush()), []);
  const onReset = useCallback(() => call(api.reset()), []);
  const onToggleHeartbeat = useCallback(() => {
    const off = !heartbeatRef.current;
    setHeartbeatOff(off);
    call(api.setHeartbeat(!off));
  }, []);
  const onController = useCallback((name: ControllerName) => call(api.setController(name)), []);

  // pitch shortcuts: 1-4 pages, R Rush Hour, F server failure, X reset, D detection view
  useEffect(() => {
    const onKey = (e: KeyboardEvent) => {
      if (e.repeat || e.metaKey || e.ctrlKey || e.altKey) return;
      const tag = (e.target as HTMLElement)?.tagName;
      if (tag === "INPUT" || tag === "SELECT" || tag === "TEXTAREA") return;
      const k = e.key.toLowerCase();
      const n = Number(k);
      if (n >= 1 && n <= PAGES.length) setPage(PAGES[n - 1].id);
      else if (k === "r") onRush();
      else if (k === "f") onToggleHeartbeat();
      else if (k === "x") onReset();
      else if (k === "d") setDetection((v) => !v);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onRush, onToggleHeartbeat, onReset]);

  const controls = (
    <ControlPanel
      heartbeatOff={heartbeatOff}
      controller={tick?.controller}
      onRush={onRush}
      onToggleHeartbeat={onToggleHeartbeat}
      onReset={onReset}
      onController={onController}
      delay={240}
    />
  );
  const espDown = tick?.esp.mode === "AVARIE";

  return (
    <div className="relative flex h-full flex-col overflow-hidden">
      <StatusBar tick={tick} connection={connection} page={page} onPage={setPage} />
      {espDown && (
        <div className="drop relative z-30 mx-3 mb-2 flex shrink-0 items-center justify-center gap-2.5 rounded-2xl bg-fix px-4 py-2.5 text-[16px] font-semibold text-white shadow-pop">
          <span className="pulse-red h-2 w-2 rounded-full bg-white" />
          Semaforul de pe teren a trecut pe programul de avarie
        </div>
      )}
      {/* key: each page fades in when selected */}
      <div key={page} className="page-in flex min-h-0 flex-1 flex-col">
        {page === "live" && <LivePage net={net} tick={tick} detection={detection} onDetection={setDetection} controls={controls} />}
        {page === "panel" && (
          <PanelPage net={net} ticks={ticks} events={events} streamPort={streamPort} detection={detection} controls={controls} />
        )}
        {page === "junctions" && (
          <JunctionsPage net={net} tick={tick} detection={detection} onDetection={setDetection} streamPort={streamPort} />
        )}
        {page === "results" && <ResultsPage ticks={ticks} savedVehSeconds={savedVehSeconds} net={net} />}
      </div>
      <Stage />
      {/* DOM layer above the WebGL canvas: intersection badges of the 3D views */}
      <div id={OVERLAY_ID} className="pointer-events-none fixed inset-0 z-30 overflow-hidden" />
      {connection !== "open" && (
        <div className="absolute inset-0 z-40 flex items-center justify-center bg-white/40 backdrop-blur-sm">
          <div className="glass-strong flex items-center gap-3 rounded-3xl px-7 py-5 text-[18px] font-semibold">
            <span className="h-4 w-4 animate-spin rounded-full border-2 border-brand border-t-transparent" />
            Reconectare la server…
          </div>
        </div>
      )}
    </div>
  );
}
