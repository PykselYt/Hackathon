import { useMemo, useState } from "react";
import type { IntersectionState, NetLight, Network, Tick } from "../types";
import { useTween } from "../hooks/useTween";
import { CameraPanel } from "../components/CameraPanel";
import { CameraSync, MapView } from "../three/MapView";

type Mode = "ai" | "fix" | "both";
const MODES: { id: Mode; label: string }[] = [
  { id: "ai", label: "AI" },
  { id: "fix", label: "Clasic" },
  { id: "both", label: "Comparație" },
];
const DIR_NAME: Record<string, string> = { N: "Nord", S: "Sud", E: "Est", V: "Vest" };
const SUBTITLE: Record<string, string> = {
  A: "Piața Unirii · camera",
  B: "Cuza Vodă × Brătianu",
  C: "Ștefan cel Mare × Brătianu",
  D: "Independenței × Brătianu",
  E: "Arcu × Gării",
};

function Tile({ net, light, s, mode, detection, delay }: {
  net: Network; light: NetLight; s?: IntersectionState; mode: Mode; detection: boolean; delay: number;
}) {
  const sync = useMemo(() => new CameraSync(), []);
  const time = useTween(s?.time_in_phase_s);
  const lamp = s?.state === "yellow" ? "bg-rush-fill" : s?.state === "all_red" ? "bg-fix" : "bg-ai";
  return (
    <section className="glass rise flex min-h-0 min-w-0 flex-col overflow-hidden rounded-3xl p-2" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-2 px-2 pb-1.5 pt-1">
        <span className="grid h-7 w-7 shrink-0 place-items-center rounded-full bg-[#0b1c3e] text-[13px] font-semibold text-white">{light.id}</span>
        <div className="min-w-0 leading-tight">
          <div className="truncate text-[14px] font-semibold">{SUBTITLE[light.id] ?? `Intersecția ${light.id}`}</div>
          <div className="flex items-center gap-1.5 text-[12px] text-muted-foreground">
            <span className={`h-2 w-2 rounded-full transition-colors duration-300 ${lamp}`} />
            <span className="truncate">AI: {s?.phase_label ?? "—"}</span>
          </div>
        </div>
        {s?.hold ? (
          <span className="ml-auto shrink-0 rounded-full bg-rush-fill px-2 py-0.5 text-[11px] font-semibold text-white">Reține fluxul</span>
        ) : (
          <span className="ml-auto shrink-0 rounded-full bg-muted px-2 py-0.5 text-[12px] tabular-nums text-muted-foreground">
            {time === null ? "—" : `${Math.round(time)} s`}
          </span>
        )}
      </div>
      {mode === "both" && (
        <div className="grid grid-cols-2 gap-1.5 px-1 pb-1 text-[11px] font-semibold">
          <span className="text-fix">Clasic</span>
          <span className="text-ai">AI</span>
        </div>
      )}
      <div className={`grid min-h-0 flex-1 gap-1.5 ${mode === "both" ? "grid-cols-2" : "grid-cols-1"}`}>
        {(mode === "both" ? (["fix", "ai"] as const) : [mode]).map((sim) => (
          <div key={sim} className="relative min-h-0 overflow-hidden rounded-2xl bg-[#eaf0f7]">
            <MapView net={net} sim={sim} focus={light.id} detection={detection} sync={mode === "both" ? sync : undefined} className="absolute inset-0" />
          </div>
        ))}
      </div>
      <div className="flex flex-wrap gap-1.5 px-1 pt-2">
        {light.approaches.map((a) => {
          const open = s ? a.open[s.green_phase] : false;
          const color = !open ? "#d93a30" : s?.state === "yellow" ? "#ff9500" : "#1f9d55";
          return (
            <span key={a.dir} className="inline-flex items-center gap-1.5 rounded-full bg-white/70 px-2 py-0.5 text-[12px] ring-1 ring-border" title={a.name}>
              <span className="h-2 w-2 rounded-full transition-colors duration-300" style={{ background: color }} />
              <span className="max-w-[110px] truncate text-muted-foreground">{DIR_NAME[a.dir] ?? a.dir} · {a.name.replace(/^(Strada|Bulevardul|Șoseaua) /, "")}</span>
              <b className="font-semibold tabular-nums">{s?.queues[a.dir] ?? 0}</b>
            </span>
          );
        })}
      </div>
    </section>
  );
}

/** Every junction at once, each with its own close-up camera. */
export function JunctionsPage({ net, tick, detection, onDetection, streamPort }: {
  net: Network | null; tick?: Tick; detection: boolean; onDetection: (v: boolean) => void; streamPort: number;
}) {
  const [mode, setMode] = useState<Mode>("ai");
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-3">
      <div className="flex items-center gap-2">
        <div className="glass flex rounded-full p-1">
          {MODES.map((m) => (
            <button
              key={m.id}
              onClick={() => setMode(m.id)}
              className={`rounded-full px-3.5 py-1 text-[13px] font-medium transition-all duration-300 ${
                mode === m.id ? "bg-[#0b1c3e] text-white shadow-card" : "text-muted-foreground hover:text-foreground"
              }`}
            >
              {m.label}
            </button>
          ))}
        </div>
        <button
          role="switch"
          aria-checked={detection}
          onClick={() => onDetection(!detection)}
          className={`glass flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium ${detection ? "text-[#0077b6]" : "text-muted-foreground"}`}
        >
          <span className={`relative h-4 w-7 rounded-full transition-colors ${detection ? "bg-[#00c2ff]" : "bg-black/15"}`}>
            <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${detection ? "left-[14px]" : "left-0.5"}`} />
          </span>
          Detecție (lidar)
        </button>
        <span className="ml-auto text-[13px] text-muted-foreground">Trageți pentru a roti, rotița pentru zoom</span>
      </div>
      <div className="grid min-h-0 flex-1 grid-cols-2 grid-rows-3 gap-3 wide:grid-cols-3 wide:grid-rows-2">
        {net?.lights.map((l, i) => (
          <Tile key={l.id} net={net} light={l} s={tick?.intersections.find((x) => x.id === l.id)} mode={mode} detection={detection} delay={i * 60} />
        ))}
        <CameraPanel vision={tick?.vision} streamPort={streamPort} delay={300} />
      </div>
    </div>
  );
}
