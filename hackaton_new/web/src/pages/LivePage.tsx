import { useMemo, useState } from "react";
import type { Network, Tick } from "../types";
import { KpiCards } from "../components/KpiCards";
import { MapPane } from "../components/MapPane";
import { FocusBar } from "../components/FocusBar";
import { CameraSync, MapView, type Focus } from "../three/MapView";

const CONTROLLER_LABEL: Record<string, string> = { ppo: "AI · PPO", max_pressure: "AI · max-pressure", fixed: "Program fix" };

/** Classic vs AI, side by side, same cars, cameras linked. */
export function LivePage({ net, tick, detection, onDetection, controls }: {
  net: Network | null; tick?: Tick; detection: boolean; onDetection: (v: boolean) => void; controls: React.ReactNode;
}) {
  const [focus, setFocus] = useState<Focus>("all");
  const sync = useMemo(() => new CameraSync(), []);
  return (
    <div className="flex min-h-0 flex-1 flex-col gap-3 px-3 pb-3">
      <KpiCards tick={tick} compact />
      <FocusBar net={net} focus={focus} onFocus={setFocus} detection={detection} onDetection={onDetection} />
      <div className="grid min-h-0 flex-1 grid-cols-2 gap-3">
        <MapPane title="Semafor clasic" tone="fix" metrics={tick?.fix} delay={120}>
          {net && <MapView net={net} sim="fix" focus={focus} detection={detection} sync={sync} className="absolute inset-0" />}
        </MapPane>
        <MapPane title={CONTROLLER_LABEL[tick?.controller ?? "ppo"] ?? "AI"} tone="ai" metrics={tick?.ai} delay={180}>
          {net && (
            <MapView
              net={net}
              sim="ai"
              focus={focus}
              detection={detection}
              sync={sync}
              labels={tick?.intersections}
              onPick={setFocus}
              className="absolute inset-0"
            />
          )}
        </MapPane>
      </div>
      {controls}
    </div>
  );
}
