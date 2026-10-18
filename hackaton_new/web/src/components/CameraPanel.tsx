import { useEffect, useState } from "react";

const STREAM_RETRY_MS = 10_000;
import type { VisionStatus } from "../types";
import zones from "../../../vision/zones.json";

const ZONE_STYLE: Record<string, { fill: string; label: string }> = {
  blv_dir1: { fill: "#1f9d55", label: "Bulevard spre B" },
  blv_dir2: { fill: "#0a84ff", label: "Bulevard spre cameră" },
  lateral: { fill: "#ff9500", label: "Strada laterală" },
};

// zones.json is normalised to the full camera frame; the schematic shows the detector crop
const [cx0, cy0, cx1, cy1] = zones.crop;
const [refW, refH] = zones.reference_frame;
const VB_W = 100 * ((cx1 - cx0) * refW) / ((cy1 - cy0) * refH);
const VB_H = 100;
const px = ([x, y]: number[]) => [((x - cx0) / (cx1 - cx0)) * VB_W, ((y - cy0) / (cy1 - cy0)) * VB_H];
const points = (poly: number[][]) => poly.map((p) => px(p).join(",")).join(" ");
const centroid = (poly: number[][]) => {
  const ps = poly.map(px);
  return [ps.reduce((a, p) => a + p[0], 0) / ps.length, ps.reduce((a, p) => a + p[1], 0) / ps.length];
};

function ZoneSchematic({ queues }: { queues: Record<string, number> }) {
  const road = [zones.lanes[1].polygon[0], zones.lanes[0].polygon[1], zones.lanes[0].polygon[2], zones.lanes[1].polygon[3]];
  const [sa, sb] = [px(zones.stop_line.a), px(zones.stop_line.b)];
  return (
    <svg viewBox={`0 0 ${VB_W.toFixed(1)} ${VB_H}`} className="h-full w-full" preserveAspectRatio="xMidYMid meet">
      <defs>
        <pattern id="hatch" width="3" height="3" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
          <line x1="0" y1="0" x2="0" y2="3" stroke="#c7ccd6" strokeWidth="1" />
        </pattern>
      </defs>
      {zones.exclude.map((z) => (
        <polygon key={z.id} points={points(z.polygon)} fill="url(#hatch)" opacity={0.9} />
      ))}
      <polygon points={points(road)} fill="#dde2ea" />
      {zones.lanes.map((z) => (
        <polygon
          key={z.id}
          points={points(z.polygon)}
          fill={ZONE_STYLE[z.id]?.fill ?? "#8a8a8f"}
          fillOpacity={0.22}
          stroke={ZONE_STYLE[z.id]?.fill ?? "#8a8a8f"}
          strokeWidth={0.6}
          strokeLinejoin="round"
        />
      ))}
      <line x1={sa[0]} y1={sa[1]} x2={sb[0]} y2={sb[1]} stroke="#ffffff" strokeWidth={1.4} />
      {zones.lanes.map((z) => {
        const q = queues[z.id];
        if (q === undefined) return null;
        const [x, y] = centroid(z.polygon);
        return (
          <g key={z.id}>
            <rect x={x - 6} y={y - 4} width={12} height={8} rx={4} fill="#ffffff" stroke={ZONE_STYLE[z.id]?.fill} strokeWidth={0.6} />
            <text x={x} y={y + 0.3} fontSize={5} fontWeight={600} fill="#1c1c1e" textAnchor="middle" dominantBaseline="middle">
              {q}
            </text>
          </g>
        );
      })}
    </svg>
  );
}

export function CameraPanel({ vision, streamPort, delay = 0 }: { vision?: VisionStatus; streamPort: number; delay?: number }) {
  const [streamOk, setStreamOk] = useState(true);
  // the vision module may start after the page: retry the MJPEG stream periodically
  useEffect(() => {
    if (streamOk) return;
    const t = window.setTimeout(() => setStreamOk(true), STREAM_RETRY_MS);
    return () => window.clearTimeout(t);
  }, [streamOk]);
  const online = !!vision?.online;
  const live = vision?.source === "screen" || vision?.source === "stream";
  const queues = vision?.queues ?? {};
  return (
    <section className="glass rise flex min-h-0 min-w-0 flex-col overflow-hidden rounded-3xl px-4 py-3" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 leading-tight">
          <h2 className="truncate text-[16px] font-semibold tracking-tight">Camera Piața Unirii</h2>
          <div className="truncate text-[12px] text-muted-foreground">Sursa: WebcamRomania.ro</div>
        </div>
        <span
          className={`inline-flex shrink-0 items-center gap-1.5 rounded-full px-2.5 py-1 text-[12px] font-semibold ${
            !online ? "bg-muted text-muted-foreground" : live ? "bg-fix/10 text-fix" : "bg-brand/10 text-brand-ink"
          }`}
        >
          {online && live && <span className="pulse-red h-1.5 w-1.5 rounded-full bg-current" />}
          {!online ? "OFF" : live ? "LIVE" : "CLIP"}
        </span>
      </div>
      <div className="relative mt-2 min-h-[150px] flex-1 wide:min-h-[110px] overflow-hidden rounded-2xl bg-white/50 ring-1 ring-border">
        {online && streamOk ? (
          <img
            src={`http://${location.hostname}:${streamPort}/stream`}
            alt="Cadrul camerei cu detecții"
            className="h-full w-full object-cover"
            onError={() => setStreamOk(false)}
          />
        ) : (
          <div className="absolute inset-0 p-1.5">
            <ZoneSchematic queues={queues} />
          </div>
        )}
        {!online && (
          <div className="absolute inset-x-0 bottom-0 bg-white/80 px-3 py-1.5 text-center text-[12px] text-muted-foreground backdrop-blur">
            Camera nu trimite date
          </div>
        )}
      </div>
      <div className="mt-2 flex flex-wrap gap-1.5">
        {Object.entries(ZONE_STYLE)
          .filter(([id]) => queues[id] !== undefined)
          .map(([id, z]) => (
            <span key={id} className="inline-flex items-center gap-1.5 rounded-full bg-white/70 px-2.5 py-1 text-[13px] ring-1 ring-border">
              <span className="h-2 w-2 rounded-full" style={{ background: z.fill }} />
              <span className="text-muted-foreground">{z.label}</span>
              <b className="font-semibold tabular-nums">{queues[id]}</b>
            </span>
          ))}
        {online && vision!.avg_stop_s !== null && (
          <span className="inline-flex items-center gap-1.5 rounded-full bg-white/70 px-2.5 py-1 text-[13px] ring-1 ring-border">
            <span className="text-muted-foreground">Oprire medie</span>
            <b className="font-semibold tabular-nums">{Math.round(vision!.avg_stop_s)} s</b>
          </span>
        )}
      </div>
    </section>
  );
}
