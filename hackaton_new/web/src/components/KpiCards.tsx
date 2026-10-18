import type { Tick } from "../types";
import { useTween } from "../hooks/useTween";

function Card({ label, caption, children, delay, hero, compact }: {
  label: string; caption: string; children: React.ReactNode; delay: number; hero?: boolean; compact?: boolean;
}) {
  return (
    <div
      className={`glass rise relative flex min-w-0 flex-col justify-between overflow-hidden rounded-3xl ${
        compact ? "gap-0.5 px-4 py-2.5" : "gap-1 px-5 py-4"
      } ${hero ? "bg-gradient-to-br from-ai/12 to-transparent" : ""}`}
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="label truncate">{label}</div>
      <div className="flex items-baseline leading-none tracking-tight">{children}</div>
      {!compact && <div className="truncate text-[13px] text-muted-foreground">{caption}</div>}
    </div>
  );
}

const Unit = ({ children }: { children: React.ReactNode }) => (
  <span className="ml-1 text-[0.42em] font-medium text-muted-foreground">{children}</span>
);
const Sep = ({ children }: { children: React.ReactNode }) => (
  <span className="mx-[0.25em] self-center text-[0.45em] font-normal text-muted-foreground/70">{children}</span>
);
const n = (v: number | null) => (v === null ? "–" : Math.round(v).toString());

export function KpiCards({ tick, compact = false }: { tick?: Tick; compact?: boolean }) {
  const pct = useTween(tick?.improvement_pct ?? null);
  const fixWait = useTween(tick?.fix.trip_wait_s);
  const aiWait = useTween(tick?.ai.trip_wait_s);
  const fixQ = useTween(tick?.fix.queue_veh);
  const aiQ = useTween(tick?.ai.queue_veh);
  const big = compact ? "text-[44px]" : "text-[72px]";
  const mid = compact ? "text-[34px]" : "text-[48px]";
  return (
    <section className="grid shrink-0 grid-cols-[1.25fr_1fr_1fr] gap-3">
      <Card label="Reducerea așteptării" caption="vs semaforul clasic" delay={0} hero={pct !== null && pct <= 0} compact={compact}>
        {pct !== null ? (
          <span className={`${big} font-semibold tabular-nums ${pct <= 0 ? "text-ai" : "text-fix"}`}>
            {pct <= 0 ? "−" : "+"}
            {Math.abs(Math.round(pct))}
            <span className="text-[0.6em]">%</span>
          </span>
        ) : (
          <span className={`${compact ? "py-1 text-[20px]" : "py-4 text-[26px]"} font-medium text-muted-foreground`}>se calculează…</span>
        )}
      </Card>
      <Card label="Așteptare / vehicul" caption="clasic → AI" delay={60} compact={compact}>
        <span className={`${mid} font-semibold tabular-nums`}>
          <span className="text-fix">{n(fixWait)}</span>
          <Unit>s</Unit>
          <Sep>→</Sep>
          <span className="text-ai">{n(aiWait)}</span>
          <Unit>s</Unit>
        </span>
      </Card>
      <Card label="La coadă acum" caption="vehicule, clasic vs AI" delay={120} compact={compact}>
        <span className={`${mid} font-semibold tabular-nums`}>
          <span className="text-fix">{n(fixQ)}</span>
          <Sep>vs</Sep>
          <span className="text-ai">{n(aiQ)}</span>
        </span>
      </Card>
    </section>
  );
}
