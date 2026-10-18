import type { EventKind, SimEvent } from "../types";
import { simClock } from "../format";

const TAG: Record<EventKind, string> = {
  rush_hour: "RUSH", rush_end: "RUSH", spillback_hold: "COORDONARE",
  esp_online: "ESP32", esp_offline: "ESP32", heartbeat_paused: "SERVER", heartbeat_resumed: "SERVER",
  controller_changed: "AI", reset: "SISTEM", vision_online: "CAMERĂ", vision_offline: "CAMERĂ",
};
const LEVEL: Record<string, { dot: string; tag: string }> = {
  info: { dot: "bg-ai", tag: "bg-muted text-muted-foreground" },
  warn: { dot: "bg-rush-fill", tag: "bg-rush-fill/12 text-rush" },
  error: { dot: "bg-fix", tag: "bg-fix/10 text-fix" },
};

export function EventLog({ events }: { events: SimEvent[] }) {
  return (
    <div className="flex min-h-0 flex-1 flex-col">
      <h2 className="text-[16px] font-semibold tracking-tight">Jurnal evenimente</h2>
      {events.length === 0 ? (
        <div className="mt-2 flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border text-center text-[14px] text-muted-foreground">
          Apăsați Rush Hour sau simulați căderea serverului
        </div>
      ) : (
        <ol className="relative mt-2 min-h-0 flex-1 space-y-2 overflow-hidden">
          {events.map((e, i) => {
            const lv = LEVEL[e.level] ?? LEVEL.info;
            return (
              <li key={`${e.sim_time}-${e.kind}-${i}`} className={`flex items-start gap-2.5 ${i === 0 ? "rise" : ""}`}>
                <span className={`mt-[7px] h-2 w-2 shrink-0 rounded-full ${lv.dot}`} />
                <div className="min-w-0 flex-1 leading-snug">
                  <div className="flex items-center gap-2">
                    <span className={`rounded-md px-1.5 py-px text-[10px] font-semibold tracking-wide ${lv.tag}`}>{TAG[e.kind] ?? "INFO"}</span>
                    <span className="text-[12px] tabular-nums text-muted-foreground">{simClock(e.sim_time)}</span>
                  </div>
                  <div className="text-[14px]">{e.msg}</div>
                </div>
              </li>
            );
          })}
        </ol>
      )}
    </div>
  );
}
