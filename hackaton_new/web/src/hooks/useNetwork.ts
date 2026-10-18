import { useEffect, useState } from "react";
import type { Network } from "../types";

let cached: Promise<Network> | null = null;

/** Static network geometry (GET /api/network), fetched once for the whole app. */
export function useNetwork(): Network | null {
  const [net, setNet] = useState<Network | null>(null);
  useEffect(() => {
    cached ??= fetch("/api/network").then((r) => {
      if (!r.ok) throw new Error(`network: ${r.status}`);
      return r.json();
    });
    let alive = true;
    cached.then((n) => alive && setNet(n)).catch(() => (cached = null));
    return () => {
      alive = false;
    };
  }, []);
  return net;
}
