import type { Network } from "../types";
import type { Focus } from "../three/MapView";

/** Camera presets (overview, the webcam's viewpoint, each junction) + the lidar-style detection toggle. */
export function FocusBar({ net, focus, onFocus, detection, onDetection }: {
  net: Network | null; focus: Focus; onFocus: (f: Focus) => void; detection: boolean; onDetection: (v: boolean) => void;
}) {
  const items: { id: Focus; label: string }[] = [
    { id: "all", label: "Toată rețeaua" },
    { id: "camera", label: "Vedere cameră" },
    ...(net?.lights ?? []).map((l) => ({ id: l.id, label: l.id })),
  ];
  return (
    <div className="flex flex-wrap items-center gap-2">
      <div className="glass flex rounded-full p-1">
        {items.map((it) => (
          <button
            key={it.id}
            onClick={() => onFocus(it.id)}
            className={`rounded-full px-3 py-1 text-[13px] font-medium whitespace-nowrap transition-all duration-300 ${
              focus === it.id ? "bg-[#0b1c3e] text-white shadow-card" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {it.label}
          </button>
        ))}
      </div>
      <button
        role="switch"
        aria-checked={detection}
        onClick={() => onDetection(!detection)}
        className={`glass flex items-center gap-2 rounded-full px-3 py-1.5 text-[13px] font-medium transition-colors ${
          detection ? "text-[#0077b6]" : "text-muted-foreground"
        }`}
        title="Tasta D"
      >
        <span className={`relative h-4 w-7 rounded-full transition-colors ${detection ? "bg-[#00c2ff]" : "bg-black/15"}`}>
          <span className={`absolute top-0.5 h-3 w-3 rounded-full bg-white shadow transition-all ${detection ? "left-[14px]" : "left-0.5"}`} />
        </span>
        Detecție (lidar)
      </button>
      <div className="ml-auto hidden items-center gap-3 text-[12px] text-muted-foreground wide:flex">
        <Legend color="#f6f7f9" ring label="mașină" />
        <Legend color="#ff8a80" label="oprită" />
        <Legend color="#0a84ff" label="autobuz" />
        <Legend color="#ff9500" label="pieton" />
        <Legend color="#34c759" label="trecere verde" />
      </div>
    </div>
  );
}

function Legend({ color, label, ring }: { color: string; label: string; ring?: boolean }) {
  return (
    <span className="inline-flex items-center gap-1.5">
      <span className={`h-2.5 w-2.5 rounded-sm ${ring ? "ring-1 ring-black/20" : ""}`} style={{ background: color }} />
      {label}
    </span>
  );
}
