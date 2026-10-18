import type { ControllerName } from "./types";

async function post(path: string, body?: unknown): Promise<void> {
  const res = await fetch(path, {
    method: "POST",
    headers: { "Content-Type": "application/json" },
    body: body === undefined ? undefined : JSON.stringify(body),
  });
  if (!res.ok) throw new Error(`${path}: ${res.status}`);
}

export const rush = (vehicles?: number) => post("/api/rush", vehicles ? { vehicles } : {});
export const reset = () => post("/api/reset");
export const setController = (name: ControllerName) => post("/api/controller", { name });
export const setHeartbeat = (enabled: boolean) => post("/api/heartbeat", { enabled });
