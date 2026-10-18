import type { IntersectionState } from "../types";

type Dir = "N" | "S" | "E" | "V";

// Which approaches each green phase opens (from sumo/src/piata_unirii.tll.xml).
const OPEN: Record<string, Dir[][]> = {
  A: [["V", "E"], ["S"]],
  B: [["V", "E"], ["N", "S"]],
};
const ARM_NAMES: Record<string, Partial<Record<Dir, string>>> = {
  A: { V: "Arcu", E: "Cuza Vodă", S: "Șt. cel Mare" },
  B: { V: "Cuza Vodă", E: "Cuza Vodă", N: "Brătianu", S: "Brătianu" },
};
const SUBTITLES: Record<string, string> = { A: "în cadrul camerei", B: "Cuza Vodă × Brătianu" };

const W = 280;
const H = 190;
const CX = W / 2;
const CY = H / 2;
const ROAD = 42;
const STOP = ROAD / 2 + 5; // stop line distance from the centre
const CAR_L = 10;
const CAR_W = 6.5;
const CAR_GAP = 3.5;
const LAMP = { green: "#1f9d55", yellow: "#ff9500", red: "#d93a30" };

// unit vector from the centre outwards along each arm (screen coordinates, y down)
const VEC: Record<Dir, [number, number]> = { N: [0, -1], S: [0, 1], E: [1, 0], V: [-1, 0] };

function Arm({ dir, queue, lamp, name }: { dir: Dir; queue: number; lamp: string; name?: string }) {
  const [ux, uy] = VEC[dir];
  // vehicles drive towards the centre (-u); right-hand traffic: their lane is on the right of that heading
  const [rx, ry] = [uy, -ux];
  const horizontal = ux !== 0;
  const len = horizontal ? CX : CY;
  const at = (along: number, side: number): [number, number] => [CX + ux * along + rx * side, CY + uy * along + ry * side];

  const road = horizontal
    ? { x: ux > 0 ? CX : 0, y: CY - ROAD / 2, width: CX, height: ROAD }
    : { x: CX - ROAD / 2, y: uy > 0 ? CY : 0, width: ROAD, height: CY };
  const [d1x, d1y] = at(STOP, 0);
  const [d2x, d2y] = at(len, 0);
  const [s1x, s1y] = at(STOP, 1);
  const [s2x, s2y] = at(STOP, ROAD / 2 - 2);

  const firstCar = STOP + 16;
  const room = Math.floor((len - firstCar - 34) / (CAR_L + CAR_GAP));
  const cars = Math.min(queue, Math.max(room, 0));
  const [hx, hy] = at(STOP + 7, ROAD / 4); // lamp just behind the stop line, in the incoming lane
  const [bx, by] = at(len - 17, ROAD / 4); // queue count at the arm's far end, same lane
  // street name outside the road, beside the outgoing lane, kept inside the viewBox
  const [nx, ny] = horizontal ? [ux < 0 ? 4 : W - 4, CY - ry * (ROAD / 2 + 10)] : at(len - 12, -(ROAD / 2 + 6));
  const anchor = horizontal ? (ux < 0 ? "start" : "end") : rx > 0 ? "end" : "start";

  return (
    <g>
      <rect {...road} fill="#dde2ea" />
      <line x1={d1x} y1={d1y} x2={d2x} y2={d2y} stroke="#ffffff" strokeWidth={1.5} strokeDasharray="6 6" />
      <line x1={s1x} y1={s1y} x2={s2x} y2={s2y} stroke="#ffffff" strokeWidth={3} />
      {Array.from({ length: cars }, (_, k) => {
        const [cx, cy] = at(firstCar + CAR_L / 2 + k * (CAR_L + CAR_GAP), ROAD / 4);
        const w = horizontal ? CAR_L : CAR_W;
        const h = horizontal ? CAR_W : CAR_L;
        return <rect key={k} x={cx - w / 2} y={cy - h / 2} width={w} height={h} rx={2} fill="#3a3f4b" opacity={0.85 - k * 0.04} />;
      })}
      {/* signal head */}
      <circle cx={hx} cy={hy} r={9} fill={lamp} opacity={0.2} />
      <circle cx={hx} cy={hy} r={6.5} fill="#1c1c1e" />
      <circle cx={hx} cy={hy} r={4.5} fill={lamp} />
      {/* queue count */}
      <g>
        <rect x={bx - 15} y={by - 10} width={30} height={20} rx={10} fill="#ffffff" stroke={queue > 0 ? lamp : "#c9ced8"} strokeWidth={1.5} />
        <text x={bx} y={by + 0.5} fill="#1c1c1e" fontSize={14} fontWeight={600} textAnchor="middle" dominantBaseline="middle">
          {queue}
        </text>
      </g>
      {name && (
        <text
          x={nx}
          y={ny}
          fill="#8a8a8f"
          fontSize={12.5}
          fontWeight={500}
          textAnchor={anchor}
          dominantBaseline="middle"
        >
          {name}
        </text>
      )}
    </g>
  );
}

export function IntersectionCard({ s, delay = 0 }: { s?: IntersectionState; delay?: number }) {
  const id = s?.id ?? "?";
  const open = OPEN[id]?.[s?.green_phase ?? 0] ?? [];
  const arms = (Object.keys(s?.queues ?? {}) as Dir[]).filter((d) => d in VEC);
  const lampFor = (d: Dir) =>
    s && open.includes(d) ? (s.state === "green" ? LAMP.green : s.state === "yellow" ? LAMP.yellow : LAMP.red) : LAMP.red;
  const stateLabel = s?.state === "yellow" ? "galben" : s?.state === "all_red" ? "roșu general" : "verde";
  const stateColor = s?.state === "yellow" ? "bg-rush-fill" : s?.state === "all_red" ? "bg-fix" : "bg-ai";
  return (
    <div className="glass rise relative flex min-h-0 min-w-0 flex-col rounded-3xl px-4 py-3" style={{ animationDelay: `${delay}ms` }}>
      <div className="flex items-start justify-between gap-2">
        <div className="min-w-0 leading-tight">
          <h2 className="text-[16px] font-semibold tracking-tight">Intersecția {id}</h2>
          <div className="truncate text-[12px] text-muted-foreground">{SUBTITLES[id]}</div>
        </div>
        {s?.hold ? (
          <span className="shrink-0 rounded-full bg-rush-fill px-2.5 py-1 text-[12px] font-semibold text-white shadow-card">
            Reține fluxul
          </span>
        ) : (
          <span className="shrink-0 rounded-full bg-muted px-2.5 py-1 text-[12px] font-medium tabular-nums text-muted-foreground">
            {s ? `${Math.round(s.time_in_phase_s)} s în fază` : "—"}
          </span>
        )}
      </div>
      <svg viewBox={`0 0 ${W} ${H}`} className="mx-auto my-1 h-[175px] min-h-0 w-full wide:h-auto wide:flex-1" preserveAspectRatio="xMidYMid meet">
        <rect x={CX - ROAD / 2} y={CY - ROAD / 2} width={ROAD} height={ROAD} fill="#dde2ea" />
        {arms.map((d) => (
          <Arm key={d} dir={d} queue={s!.queues[d]} lamp={lampFor(d)} name={ARM_NAMES[id]?.[d]} />
        ))}
      </svg>
      <div className="flex items-center gap-2 text-[15px]">
        <span className={`h-2.5 w-2.5 shrink-0 rounded-full ${stateColor}`} />
        <span className="truncate">
          <b className="font-semibold">{s?.phase_label ?? "—"}</b>
          <span className="text-muted-foreground"> · {stateLabel}</span>
        </span>
      </div>
    </div>
  );
}
