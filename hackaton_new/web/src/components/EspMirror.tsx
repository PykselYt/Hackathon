import type { Tick } from "../types";

const LAMP_ON: Record<string, string> = { r: "#ff3b30", y: "#ff9f0a", g: "#30d158" };

function Head({ lit, blink, label }: { lit: "r" | "y" | "g" | null; blink?: boolean; label: string }) {
  return (
    <div className="flex flex-col items-center gap-1">
      <div className="flex flex-col gap-1 rounded-xl bg-[#1c1f26] p-1.5 shadow-card">
        {(["r", "y", "g"] as const).map((c) => {
          const on = lit === c;
          return (
            <span
              key={c}
              className={`h-4 w-4 rounded-full transition-all duration-300 ${on && blink ? "pulse-red" : ""}`}
              style={{ background: on ? LAMP_ON[c] : "#3a3f4b", boxShadow: on ? `0 0 10px ${LAMP_ON[c]}` : "none" }}
            />
          );
        })}
      </div>
      <span className="max-w-[84px] truncate text-[11px] text-muted-foreground">{label}</span>
    </div>
  );
}

/** What the physical ESP32 light on the table should be showing for junction A. */
export function EspMirror({ tick, mainId = "A" }: { tick?: Tick; mainId?: string }) {
  const esp = tick?.esp;
  const a = tick?.intersections.find((i) => i.id === mainId);
  const avarie = esp?.mode === "AVARIE";
  const off = !esp || esp.mode === "NECONECTAT";
  const lamp = (phase: number): "r" | "y" | "g" | null => {
    if (off) return null;
    if (avarie) return "y";
    if (!a) return "r";
    if (a.green_phase !== phase) return "r";
    return a.state === "yellow" ? "y" : a.state === "all_red" ? "r" : "g";
  };
  return (
    <div className="flex items-center gap-3">
      <Head lit={lamp(0)} blink={avarie} label="Bulevard" />
      <Head lit={lamp(1)} blink={avarie} label="Ștefan cel Mare" />
      <div className="min-w-0 leading-tight">
        <div className="text-[14px] font-semibold">Semaforul fizic</div>
        <div className={`text-[13px] ${avarie ? "font-semibold text-fix" : "text-muted-foreground"}`}>
          {off ? "ESP32 neconectat" : avarie ? "Mod avarie, timpi ficși" : esp?.online ? "Urmează AI-ul" : "Fără ACK"}
        </div>
        {esp?.last_ack_ms !== null && esp?.last_ack_ms !== undefined && (
          <div className="text-[12px] tabular-nums text-muted-foreground">ultimul ACK acum {esp.last_ack_ms} ms</div>
        )}
      </div>
    </div>
  );
}
