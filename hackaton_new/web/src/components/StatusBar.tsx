import type { Connection } from "../hooks/useTelemetry";
import type { Tick } from "../types";
import { simClock } from "../format";
import { Logo } from "./Logo";
import { Pill } from "./Pill";

export type Page = "live" | "panel" | "junctions" | "results";
export const PAGES: { id: Page; label: string }[] = [
  { id: "live", label: "Hartă live" },
  { id: "panel", label: "Panou" },
  { id: "junctions", label: "Intersecții" },
  { id: "results", label: "Rezultate" },
];

const CONTROLLER_LABEL: Record<string, string> = { ppo: "PPO", max_pressure: "MAX-PRESSURE", fixed: "FIX" };
const CAMERA_LABEL: Record<string, string> = { file: "CLIP", screen: "LIVE", stream: "LIVE", snapshot: "SNAPSHOT" };

export function StatusBar({ tick, connection, page, onPage }: {
  tick?: Tick; connection: Connection; page: Page; onPage: (p: Page) => void;
}) {
  const running = connection === "open" && !!tick;
  const esp = tick?.esp;
  const vision = tick?.vision;
  return (
    <header className="relative z-30 flex h-16 shrink-0 items-center gap-3 px-4">
      <Logo />
      <div className="min-w-0 leading-tight">
        <h1 className="truncate text-[19px] font-semibold tracking-tight">Semafoare AI</h1>
        <div className="truncate text-[13px] text-muted-foreground">Piața Unirii, Iași</div>
      </div>
      <nav className="glass ml-3 flex shrink-0 rounded-full p-1" aria-label="Pagini">
        {PAGES.map((p, i) => (
          <button
            key={p.id}
            onClick={() => onPage(p.id)}
            title={`Tasta ${i + 1}`}
            className={`relative rounded-full px-3.5 py-1.5 text-[13px] font-medium whitespace-nowrap transition-all duration-300 ${
              page === p.id ? "bg-white text-foreground shadow-card" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {p.label}
          </button>
        ))}
      </nav>
      <div className="ml-auto flex items-center justify-end gap-1.5">
        <Pill label="SIM" value={running ? "PORNITĂ" : "OPRITĂ"} tone={running ? "ok" : "off"} />
        <Pill label="AI" value={tick ? CONTROLLER_LABEL[tick.controller] ?? tick.controller : "—"} tone="neutral" />
        <Pill
          label="ESP32"
          value={!esp || esp.mode === "NECONECTAT" ? "—" : `${esp.online ? "ONLINE" : "OFFLINE"} · ${esp.mode}`}
          tone={esp?.online ? "ok" : esp?.mode === "AVARIE" ? "alert" : "off"}
        />
        <Pill label="CAMERĂ" value={vision?.online ? CAMERA_LABEL[vision.source ?? ""] ?? "ON" : "OFF"} tone={vision?.online ? "ok" : "off"} />
        <span className="glass ml-1 rounded-full px-3 py-1 text-[16px] font-semibold tabular-nums">
          {tick ? simClock(tick.sim_time) : "--:--"}
        </span>
      </div>
    </header>
  );
}
