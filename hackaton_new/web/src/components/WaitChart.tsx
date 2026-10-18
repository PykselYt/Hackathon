import { useMemo } from "react";
import {
  Chart as ChartJS, Filler, LinearScale, LineElement, PointElement, Tooltip, type ChartOptions, type ScriptableContext,
} from "chart.js";
import annotationPlugin, { type AnnotationOptions } from "chartjs-plugin-annotation";
import { Line } from "react-chartjs-2";
import type { Tick } from "../types";
import { simClock } from "../format";

ChartJS.register(LinearScale, LineElement, PointElement, Tooltip, Filler, annotationPlugin);

const WINDOW_S = 600; // simulated seconds shown on the x axis
const MIN_SPAN_S = 120;
const FIX = "#d93a30";
const AI = "#1f9d55";
const RUSH_INK = "#c46a00";
const GRID = "rgba(0,0,0,0.05)";
const TEXT = "#8a8a8f";

function areaFill(rgb: string) {
  return (ctx: ScriptableContext<"line">) => {
    const { chartArea, ctx: c } = ctx.chart;
    if (!chartArea) return `rgba(${rgb},0.08)`;
    const g = c.createLinearGradient(0, chartArea.top, 0, chartArea.bottom);
    g.addColorStop(0, `rgba(${rgb},0.16)`);
    g.addColorStop(1, `rgba(${rgb},0)`);
    return g;
  };
}

function rushBands(ticks: Tick[]): AnnotationOptions[] {
  const bands: AnnotationOptions[] = [];
  let start: number | null = null;
  ticks.forEach((t, i) => {
    if (t.rush_active && start === null) start = t.sim_time;
    const ends = !t.rush_active || i === ticks.length - 1;
    if (start !== null && ends) {
      bands.push({
        type: "box",
        xMin: start,
        xMax: t.sim_time,
        backgroundColor: "rgba(255,149,0,0.10)",
        borderColor: "rgba(255,149,0,0.35)",
        borderWidth: 1,
        borderDash: [4, 4],
        label: {
          display: true,
          content: "Rush Hour",
          position: { x: "start", y: "start" },
          padding: { x: 6, y: 4 },
          color: RUSH_INK,
          font: { size: 13, weight: 600 },
          xAdjust: 6,
          yAdjust: 6,
        },
      });
      start = null;
    }
  });
  return bands;
}

function LegendChip({ color, label, value }: { color: string; label: string; value?: number }) {
  return (
    <span className="inline-flex items-center gap-2 rounded-full bg-white/70 px-3 py-1 ring-1 ring-border">
      <span className="h-[3px] w-5 rounded-full" style={{ background: color }} />
      <span className="text-[13px] text-muted-foreground">{label}</span>
      <b className="text-[15px] font-semibold tabular-nums" style={{ color }}>
        {value === undefined ? "–" : `${Math.round(value)} s`}
      </b>
    </span>
  );
}

export function WaitChart({ ticks, delay = 0 }: { ticks: Tick[]; delay?: number }) {
  const lastTick = ticks.at(-1);
  const last = lastTick?.sim_time ?? 0;
  const min = Math.max(0, last - WINDOW_S);
  const max = Math.max(last, min + MIN_SPAN_S);
  const visible = useMemo(() => ticks.filter((t) => t.sim_time >= min), [ticks, min]);

  const data = {
    datasets: [
      {
        label: "Semafor clasic",
        data: visible.map((t) => ({ x: t.sim_time, y: t.fix.avg_wait_s })),
        borderColor: FIX,
        backgroundColor: areaFill("217,58,48"),
        fill: "origin" as const,
      },
      {
        label: "AI",
        data: visible.map((t) => ({ x: t.sim_time, y: t.ai.avg_wait_s })),
        borderColor: AI,
        backgroundColor: areaFill("31,157,85"),
        fill: "origin" as const,
      },
    ],
  };

  const options = useMemo<ChartOptions<"line">>(
    () => ({
      responsive: true,
      maintainAspectRatio: false,
      animation: false,
      parsing: false,
      normalized: true,
      layout: { padding: { top: 4, right: 4 } },
      elements: { point: { radius: 0, hoverRadius: 4 }, line: { borderWidth: 2.5, tension: 0.3 } },
      interaction: { mode: "index", intersect: false },
      scales: {
        x: {
          type: "linear",
          min,
          max,
          border: { display: false },
          grid: { color: GRID },
          ticks: { color: TEXT, font: { size: 13 }, callback: (v) => simClock(Number(v)), maxTicksLimit: 7 },
        },
        y: {
          beginAtZero: true,
          grace: "10%",
          border: { display: false },
          grid: { color: GRID },
          ticks: { color: TEXT, font: { size: 13 }, maxTicksLimit: 6, callback: (v) => `${v} s` },
        },
      },
      plugins: {
        legend: { display: false },
        tooltip: {
          backgroundColor: "rgba(255,255,255,0.95)",
          titleColor: "#1c1c1e",
          bodyColor: "#1c1c1e",
          borderColor: "rgba(0,0,0,0.08)",
          borderWidth: 1,
          padding: 10,
          cornerRadius: 12,
          callbacks: {
            title: (items) => simClock(items[0]?.parsed.x ?? 0),
            label: (item) => ` ${item.dataset.label}: ${Math.round(item.parsed.y ?? 0)} s`,
          },
        },
        annotation: { annotations: rushBands(visible) },
      },
    }),
    [min, max, visible],
  );

  return (
    <section
      className="glass rise flex min-h-[220px] flex-1 flex-col overflow-hidden rounded-3xl px-4 pb-3 pt-3"
      style={{ animationDelay: `${delay}ms` }}
    >
      <div className="flex flex-wrap items-start justify-between gap-2">
        <div className="leading-tight">
          <h2 className="text-[16px] font-semibold tracking-tight">Așteptare medie în rețea</h2>
          <div className="text-[12px] text-muted-foreground">aceleași mașini în ambele simulări · ultimele 10 min</div>
        </div>
        <div className="flex flex-wrap gap-1.5">
          <LegendChip color={FIX} label="Semafor clasic" value={lastTick?.fix.avg_wait_s} />
          <LegendChip color={AI} label="AI" value={lastTick?.ai.avg_wait_s} />
        </div>
      </div>
      <div className="relative mt-2 min-h-0 flex-1">
        {/* updateMode "none": no animation, cheap redraws on long runs */}
        <Line data={data} options={options} updateMode="none" />
      </div>
    </section>
  );
}
