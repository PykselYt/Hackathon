import type { ControllerName } from "../types";

const CONTROLLERS: { name: ControllerName; label: string }[] = [
  { name: "ppo", label: "PPO" },
  { name: "max_pressure", label: "Max-pressure" },
  { name: "fixed", label: "Fix" },
];

interface Props {
  heartbeatOff: boolean;
  controller?: string;
  onRush: () => void;
  onToggleHeartbeat: () => void;
  onReset: () => void;
  onController: (name: ControllerName) => void;
  delay?: number;
}

const Kbd = ({ k, light }: { k: string; light?: boolean }) => (
  <kbd className={`rounded-md px-1.5 py-0.5 text-[11px] font-semibold ${light ? "bg-white/25 text-white" : "bg-black/[0.06] text-muted-foreground"}`}>
    {k}
  </kbd>
);

function Bolt() {
  return (
    <svg viewBox="0 0 24 24" className="h-[18px] w-[18px]" fill="currentColor" aria-hidden>
      <path d="M13 2 4 14h6l-1 8 9-12h-6l1-8z" />
    </svg>
  );
}

/** Pitch controls in one horizontal bar under the chart. */
export function ControlPanel({ heartbeatOff, controller, onRush, onToggleHeartbeat, onReset, onController, delay = 0 }: Props) {
  return (
    <section className="glass rise flex shrink-0 items-center gap-2 rounded-3xl p-2" style={{ animationDelay: `${delay}ms` }}>
      <button
        onClick={onRush}
        className="flex h-11 shrink-0 items-center gap-2 rounded-2xl bg-rush-fill px-4 text-[16px] font-semibold whitespace-nowrap text-white shadow-card transition-all duration-200 hover:brightness-105 active:scale-[0.97]"
      >
        <Bolt /> Rush Hour <Kbd k="R" light />
      </button>
      <button
        role="switch"
        aria-checked={heartbeatOff}
        onClick={onToggleHeartbeat}
        className={`flex h-11 min-w-0 flex-1 items-center gap-2.5 rounded-2xl px-3 text-left transition-colors duration-200 ${
          heartbeatOff ? "bg-fix/10 ring-1 ring-fix/40" : "bg-white/60 ring-1 ring-border hover:bg-white/80"
        }`}
      >
        <span className={`relative h-6 w-10 shrink-0 rounded-full transition-colors duration-200 ${heartbeatOff ? "bg-fix" : "bg-black/15"}`}>
          <span
            className={`absolute top-0.5 h-5 w-5 rounded-full bg-white shadow transition-all duration-200 ${heartbeatOff ? "left-[18px]" : "left-0.5"}`}
          />
        </span>
        <span className="min-w-0 flex-1 truncate text-[14px] font-semibold">
          {heartbeatOff ? <span className="text-fix">Server căzut (simulat)</span> : "Simulează căderea serverului"}
        </span>
        <Kbd k="F" />
      </button>
      <div className="flex shrink-0 rounded-full bg-black/[0.05] p-0.5" title="Controlerul simulării AI">
        {CONTROLLERS.map((c) => (
          <button
            key={c.name}
            onClick={() => onController(c.name)}
            className={`rounded-full px-2.5 py-1.5 text-[12px] whitespace-nowrap transition-colors ${
              controller === c.name ? "bg-white font-semibold text-foreground shadow-card" : "text-muted-foreground hover:text-foreground"
            }`}
          >
            {c.label}
          </button>
        ))}
      </div>
      <button
        onClick={onReset}
        title="Repornește ambele simulări"
        className="flex h-11 shrink-0 items-center gap-1.5 rounded-2xl px-3 text-[13px] text-muted-foreground hover:bg-white/70 hover:text-foreground"
      >
        Reset <Kbd k="X" />
      </button>
    </section>
  );
}
