import { useEffect, useMemo, useState } from "react";
import { BarElement, CategoryScale, Chart as ChartJS, LinearScale, Tooltip, type ChartOptions } from "chart.js";
import { Bar } from "react-chartjs-2";
import type { EvalRow, Network, Tick } from "../types";
import { useTween } from "../hooks/useTween";

ChartJS.register(BarElement, CategoryScale, LinearScale, Tooltip);

const VARIANTS: { id: string; label: string }[] = [
  { id: "fixed_program", label: "Program fix" },
  { id: "actuated", label: "Cu senzori" },
  { id: "max_pressure", label: "Max-pressure" },
  { id: "ppo", label: "AI (PPO)" },
];
// assumptions for the impact estimate, shown on the page
const IDLE_L_PER_H = 0.9;
const CO2_KG_PER_L = 2.31;
const FIXED = { major: 57, minor: 27, yellow: 3 };
const TIMELINE_S = 180;

function Stat({ label, value, unit, caption, delay }: { label: string; value: number | null; unit: string; caption: string; delay: number }) {
  const v = useTween(value, 900);
  return (
    <div className="glass rise flex min-w-0 flex-col gap-1 rounded-3xl px-5 py-4" style={{ animationDelay: `${delay}ms` }}>
      <div className="label truncate">{label}</div>
      <div className="flex items-baseline gap-1 leading-none">
        <span className="text-[42px] font-semibold tracking-tight text-ai tabular-nums">
          {v === null ? "–" : v >= 100 ? Math.round(v).toLocaleString("ro-RO") : v.toFixed(1)}
        </span>
        <span className="text-[16px] font-medium text-muted-foreground">{unit}</span>
      </div>
      <div className="truncate text-[12px] text-muted-foreground">{caption}</div>
    </div>
  );
}

function EvalCard({ rows }: { rows: EvalRow[] }) {
  const get = (v: string, sc: string) => rows.find((r) => r.variant === v && r.scenario === sc);
  const shown = VARIANTS.filter((v) => get(v.id, "normal"));
  const data = {
    labels: shown.map((v) => v.label),
    datasets: [
      { label: "Trafic normal", data: shown.map((v) => get(v.id, "normal")?.mean_wait_s ?? 0), backgroundColor: shown.map((v) => (v.id === "ppo" ? "#1f9d55" : v.id === "fixed_program" ? "#d93a30" : "#9aa3b2")), borderRadius: 8 },
      { label: "Cu Rush Hour", data: shown.map((v) => get(v.id, "rush")?.mean_wait_s ?? 0), backgroundColor: shown.map((v) => (v.id === "ppo" ? "rgba(31,157,85,0.45)" : v.id === "fixed_program" ? "rgba(217,58,48,0.45)" : "rgba(154,163,178,0.45)")), borderRadius: 8 },
    ],
  };
  const options: ChartOptions<"bar"> = {
    responsive: true,
    maintainAspectRatio: false,
    animation: { duration: 900, easing: "easeOutQuart" },
    plugins: {
      legend: { display: false },
      tooltip: { callbacks: { label: (i) => ` ${i.dataset.label}: ${Number(i.parsed.y).toFixed(1)} s` } },
    },
    scales: {
      x: { grid: { display: false }, border: { display: false }, ticks: { color: "#1c1c1e", font: { size: 13, weight: 600 } } },
      y: { beginAtZero: true, border: { display: false }, grid: { color: "rgba(0,0,0,0.05)" }, ticks: { color: "#8a8a8f", callback: (v) => `${v} s` } },
    },
  };
  const ppoN = get("ppo", "normal");
  const ppoR = get("ppo", "rush");
  return (
    <section className="glass rise flex min-h-0 min-w-0 flex-col rounded-3xl px-5 py-4" style={{ animationDelay: "200ms" }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="leading-tight">
          <h2 className="text-[16px] font-semibold tracking-tight">Evaluare pe 5 seed-uri × 1 oră simulată</h2>
          <div className="text-[12px] text-muted-foreground">așteptare medie / vehicul, aceleași mașini pentru fiecare variantă</div>
        </div>
        <div className="flex gap-3 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#9aa3b2]" />normal</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-[#9aa3b2]/45" />Rush Hour</span>
        </div>
      </div>
      {rows.length === 0 ? (
        <div className="mt-3 flex flex-1 items-center justify-center rounded-2xl border border-dashed border-border text-[14px] text-muted-foreground">
          Rulați python -m ai.evaluate
        </div>
      ) : (
        <>
          <div className="relative mt-3 min-h-[160px] flex-1">
            <Bar data={data} options={options} />
          </div>
          <table className="mt-3 w-full text-[13px] tabular-nums">
            <thead>
              <tr className="text-left text-muted-foreground">
                <th className="py-1 font-medium">Variantă</th>
                <th className="py-1 text-right font-medium">Normal</th>
                <th className="py-1 text-right font-medium">vs fix</th>
                <th className="py-1 text-right font-medium">Rush Hour</th>
                <th className="py-1 text-right font-medium">vs fix</th>
              </tr>
            </thead>
            <tbody>
              {shown.map((v) => {
                const n = get(v.id, "normal")!;
                const r = get(v.id, "rush");
                const pct = (x: number | null | undefined) =>
                  x === null || x === undefined || v.id === "fixed_program" ? "—" : `${x > 0 ? "+" : "−"}${Math.abs(Math.round(x))}%`;
                const tone = (x: number | null | undefined) => (x === null || x === undefined || v.id === "fixed_program" ? "" : x < 0 ? "text-ai font-semibold" : "text-fix font-semibold");
                return (
                  <tr key={v.id} className={`border-t border-border ${v.id === "ppo" ? "bg-ai/5" : ""}`}>
                    <td className="py-1.5 font-medium">{v.label}</td>
                    <td className="py-1.5 text-right">{n.mean_wait_s.toFixed(1)} ± {n.mean_wait_s_sd.toFixed(1)} s</td>
                    <td className={`py-1.5 text-right ${tone(n.vs_fixed_program_pct)}`}>{pct(n.vs_fixed_program_pct)}</td>
                    <td className="py-1.5 text-right">{r ? `${r.mean_wait_s.toFixed(1)} ± ${r.mean_wait_s_sd.toFixed(1)} s` : "—"}</td>
                    <td className={`py-1.5 text-right ${tone(r?.vs_fixed_program_pct)}`}>{pct(r?.vs_fixed_program_pct)}</td>
                  </tr>
                );
              })}
            </tbody>
          </table>
          {ppoN && ppoR && (
            <div className="mt-2 text-[13px] text-muted-foreground">
              Cifra pentru pitch: AI-ul reduce așteptarea cu <b className="text-ai">{Math.abs(Math.round(ppoN.vs_fixed_program_pct ?? 0))}%</b> în
              trafic normal și cu <b className="text-ai">{Math.abs(Math.round(ppoR.vs_fixed_program_pct ?? 0))}%</b> la Rush Hour.
            </div>
          )}
        </>
      )}
    </section>
  );
}

const PHASE_COLOR = ["#0a84ff", "#8e7cf0", "#14b8a6", "#f472b6"];

function fixedPhaseAt(t: number): { phase: number; yellow: boolean } {
  const c = FIXED.major + FIXED.yellow + FIXED.minor + FIXED.yellow;
  const x = ((t % c) + c) % c;
  if (x < FIXED.major) return { phase: 0, yellow: false };
  if (x < FIXED.major + FIXED.yellow) return { phase: 0, yellow: true };
  if (x < FIXED.major + FIXED.yellow + FIXED.minor) return { phase: 1, yellow: false };
  return { phase: 1, yellow: true };
}

function Row({ segments, t0 }: { segments: { t: number; phase: number; yellow: boolean }[]; t0: number }) {
  return (
    <svg viewBox={`0 0 ${TIMELINE_S} 10`} preserveAspectRatio="none" className="h-4 w-full overflow-hidden rounded-md">
      {segments.map((s, i) => {
        const next = segments[i + 1]?.t ?? t0 + TIMELINE_S;
        return <rect key={i} x={s.t - t0} y={0} width={Math.max(0, next - s.t)} height={10} fill={s.yellow ? "#ff9500" : PHASE_COLOR[s.phase]} />;
      })}
    </svg>
  );
}

function Timeline({ ticks, net }: { ticks: Tick[]; net: Network | null }) {
  const last = ticks.at(-1)?.sim_time ?? 0;
  const t0 = Math.max(0, last - TIMELINE_S);
  const recent = useMemo(() => ticks.filter((t) => t.sim_time >= t0), [ticks, t0]);
  const ids = net?.lights.map((l) => l.id) ?? [];
  const compress = <T extends { phase: number; yellow: boolean }>(xs: (T & { t: number })[]) =>
    xs.filter((x, i) => i === 0 || x.phase !== xs[i - 1].phase || x.yellow !== xs[i - 1].yellow);
  const fixed = compress(Array.from({ length: Math.ceil(TIMELINE_S) }, (_, k) => ({ t: t0 + k, ...fixedPhaseAt(t0 + k) })));
  return (
    <section className="glass rise flex min-w-0 flex-col rounded-3xl px-5 py-4" style={{ animationDelay: "260ms" }}>
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="leading-tight">
          <h2 className="text-[16px] font-semibold tracking-tight">Cronologia fazelor, ultimele 3 minute</h2>
          <div className="text-[12px] text-muted-foreground">programul fix bate același ritm; AI-ul lungește și scurtează verdele după cozi</div>
        </div>
        <div className="flex flex-wrap gap-3 text-[12px] text-muted-foreground">
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: PHASE_COLOR[0] }} />faza principală</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm" style={{ background: PHASE_COLOR[1] }} />faza secundară</span>
          <span className="inline-flex items-center gap-1.5"><span className="h-2.5 w-2.5 rounded-sm bg-rush-fill" />galben</span>
        </div>
      </div>
      <div className="mt-3 grid grid-cols-[86px_1fr] items-center gap-x-3 gap-y-2 text-[13px]">
        <span className="font-medium text-fix">Clasic</span>
        <Row segments={fixed} t0={t0} />
        {ids.map((id) => {
          const segs = compress(
            recent.map((t) => {
              const s = t.intersections.find((i) => i.id === id);
              return { t: t.sim_time, phase: s?.green_phase ?? 0, yellow: s?.state === "yellow" };
            }),
          );
          return (
            <div key={id} className="contents">
              <span className="font-medium text-ai">AI · {id}</span>
              <Row segments={segs} t0={t0} />
            </div>
          );
        })}
      </div>
    </section>
  );
}

const METHOD: { title: string; text: string }[] = [
  { title: "Aceleași mașini", text: "Ambele simulări primesc exact același trafic (același seed SUMO): diferența vine doar din semafoare." },
  { title: "Rețeaua", text: "5 intersecții reale din jurul Pieței Unirii, din OpenStreetMap, cu treceri de pietoni, autobuze și pietoni." },
  { title: "Comparația", text: "Program fix (90 s, 57/27), semafor cu senzori (actuated), max-pressure și AI-ul antrenat (PPO)." },
  { title: "Antrenarea", text: "O politică PPO comună pentru toate semafoarele, antrenată pe trafic variabil cu valuri de tip Rush Hour." },
  { title: "Siguranța", text: "AI-ul doar recomandă: galbenul, roșul general, verdele minim/maxim și avaria rămân pe placa locală." },
  { title: "Camera", text: "Debitele din simulare se calibrează din camera WebcamRomania; se transmit doar cifre, nu imagini." },
];

function Method() {
  return (
    <section className="glass rise flex min-h-0 min-w-0 flex-col rounded-3xl px-5 py-4" style={{ animationDelay: "320ms" }}>
      <h2 className="text-[16px] font-semibold tracking-tight">Cum am măsurat</h2>
      <div className="mt-3 grid min-h-0 flex-1 auto-rows-min grid-cols-2 gap-x-5 gap-y-3 overflow-hidden">
        {METHOD.map((m) => (
          <div key={m.title} className="min-w-0">
            <div className="text-[13px] font-semibold">{m.title}</div>
            <div className="text-[13px] leading-snug text-muted-foreground">{m.text}</div>
          </div>
        ))}
      </div>
    </section>
  );
}

export function ResultsPage({ ticks, savedVehSeconds, net }: { ticks: Tick[]; savedVehSeconds: number; net: Network | null }) {
  const [rows, setRows] = useState<EvalRow[]>([]);
  useEffect(() => {
    fetch("/api/results").then((r) => r.json()).then((d) => setRows(d.rows ?? [])).catch(() => {});
  }, []);
  const tick = ticks.at(-1);
  const hours = Math.max(0, savedVehSeconds) / 3600;
  const fuel = hours * IDLE_L_PER_H;
  const throughputGain = tick ? tick.ai.throughput_vph - tick.fix.throughput_vph : null;
  return (
    <main className="grid min-h-0 flex-1 grid-rows-[auto_minmax(0,1fr)] gap-3 px-3 pb-3">
      <section className="grid grid-cols-2 gap-3 wide:grid-cols-4">
        <Stat label="Staționare evitată" value={hours} unit="vehicul-ore" caption="de la pornirea simulării, AI vs clasic" delay={0} />
        <Stat label="Combustibil economisit" value={fuel} unit="litri" caption={`estimare: ${IDLE_L_PER_H} L/h la ralanti`} delay={60} />
        <Stat label="CO₂ evitat" value={fuel * CO2_KG_PER_L} unit="kg" caption={`${CO2_KG_PER_L} kg CO₂ / litru benzină`} delay={120} />
        <Stat label="Debit în plus" value={throughputGain} unit="veh/h" caption="vehicule ieșite din rețea, AI − clasic" delay={180} />
      </section>
      <section className="grid min-h-0 gap-3 wide:grid-cols-[1.1fr_1fr]">
        <EvalCard rows={rows} />
        <div className="flex min-h-0 flex-col gap-3">
          <Timeline ticks={ticks} net={net} />
          <Method />
        </div>
      </section>
    </main>
  );
}
