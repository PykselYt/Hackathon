import { useState } from "react";
import type { Network, SimEvent, Tick } from "../types";
import { KpiCards } from "../components/KpiCards";
import { WaitChart } from "../components/WaitChart";
import { MapPane } from "../components/MapPane";
import { CameraPanel } from "../components/CameraPanel";
import { EventLog } from "../components/EventLog";
import { EspMirror } from "../components/EspMirror";
import { MapView, type Focus } from "../three/MapView";

/** The numbers view: KPIs and chart on the left, AI network map, camera, board and events on the right. */
export function PanelPage({ net, ticks, events, streamPort, detection, controls }: {
  net: Network | null; ticks: Tick[]; events: SimEvent[]; streamPort: number; detection: boolean; controls: React.ReactNode;
}) {
  const tick = ticks.at(-1);
  const [focus, setFocus] = useState<Focus>("all");
  return (
    <main className="grid min-h-0 flex-1 grid-rows-[minmax(0,1fr)_auto] gap-3 px-3 pb-3 wide:grid-cols-[1.1fr_1fr] wide:grid-rows-1">
      <div className="flex min-h-0 flex-col gap-3">
        <KpiCards tick={tick} />
        <WaitChart ticks={ticks} delay={180} />
        {controls}
      </div>
      <div className="grid min-h-0 grid-rows-[minmax(260px,1.15fr)_minmax(0,1fr)] gap-3">
        <MapPane
          title="Rețeaua, AI"
          tone="neutral"
          delay={240}
          right={
            focus !== "all" && (
              <button onClick={() => setFocus("all")} className="rounded-full bg-white/80 px-2.5 py-1 text-[12px] font-medium ring-1 ring-border hover:bg-white">
                Toată rețeaua
              </button>
            )
          }
        >
          {net && (
            <MapView net={net} sim="ai" focus={focus} detection={detection} labels={tick?.intersections} onPick={setFocus} className="absolute inset-0" />
          )}
        </MapPane>
        <section className="grid min-h-0 grid-cols-2 gap-3">
          <CameraPanel vision={tick?.vision} streamPort={streamPort} delay={300} />
          <div className="glass rise flex min-h-0 min-w-0 flex-col gap-3 rounded-3xl px-4 py-3" style={{ animationDelay: "360ms" }}>
            <EspMirror tick={tick} />
            <div className="h-px shrink-0 bg-border" />
            <EventLog events={events} />
          </div>
        </section>
      </div>
    </main>
  );
}
