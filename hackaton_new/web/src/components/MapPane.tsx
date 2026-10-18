import type { SimMetrics } from "../types";
import { useTween } from "../hooks/useTween";

/** Glass card around a 3D view: title chip + live figures on top, the 3D viewport fills the rest. */
export function MapPane({ title, tone, metrics, children, right, delay = 0 }: {
  title: string;
  tone: "fix" | "ai" | "neutral";
  metrics?: SimMetrics;
  children: React.ReactNode;
  right?: React.ReactNode;
  delay?: number;
}) {
  const wait = useTween(metrics?.avg_wait_s);
  const queue = useTween(metrics?.queue_veh);
  const chip = tone === "fix" ? "bg-fix text-white" : tone === "ai" ? "bg-ai text-white" : "bg-white/80 text-foreground ring-1 ring-border";
  return (
    <section className="glass rise flex min-h-0 min-w-0 flex-col overflow-hidden rounded-3xl p-2" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-center gap-2 px-2 pb-2 pt-1">
        <span className={`rounded-full px-3 py-1 text-[13px] font-semibold ${chip}`}>{title}</span>
        {metrics && (
          <span className="flex items-baseline gap-3 text-[13px] text-muted-foreground tabular-nums">
            <span>
              așteptare <b className="text-[15px] font-semibold text-foreground">{wait === null ? "–" : Math.round(wait)} s</b>
            </span>
            <span>
              la coadă <b className="text-[15px] font-semibold text-foreground">{queue === null ? "–" : Math.round(queue)}</b>
            </span>
          </span>
        )}
        <div className="ml-auto flex items-center gap-1.5">{right}</div>
      </div>
      <div className="relative min-h-0 flex-1 overflow-hidden rounded-2xl bg-[#eaf0f7]">{children}</div>
    </section>
  );
}
