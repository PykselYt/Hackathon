"""FastAPI server: REST + WebSocket + static dashboard (PLAN.md §10).

    python -m server.main --config config.yaml [--mock] [--no-serial] [--controller max_pressure]
"""
import argparse
import asyncio
import random
import time
from collections import deque
from contextlib import asynccontextmanager
from pathlib import Path

import uvicorn
import yaml
from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

from server.schemas import (
    ControllerRequest, Event, HeartbeatRequest, OkResponse, RushRequest, SpawnRequest, Tick, VisionReport,
)

ROOT = Path(__file__).resolve().parents[1]
VISION_TIMEOUT_S = 5.0
RECENT_EVENTS = 6  # replayed to a client that (re)connects, so the log survives a page refresh
WS_SEND_TIMEOUT_S = 2.0


class NoEsp:
    """--no-serial: no board, heartbeat toggle only produces events."""

    def __init__(self):
        self.enabled = True

    def set_heartbeat(self, enabled: bool) -> None:
        self.enabled = enabled

    def status(self) -> dict:
        return {"online": False, "last_ack_ms": None, "mode": "NECONECTAT"}


class Hub:
    """Owns the asyncio side: history, WebSocket clients, vision state, esp status."""

    def __init__(self, cfg: dict, mock: bool):
        self.cfg = cfg
        self.mock = mock
        self.loop: asyncio.AbstractEventLoop | None = None
        self.history: deque[dict] = deque(maxlen=cfg["server"]["history_points"])
        self.events: deque[dict] = deque(maxlen=RECENT_EVENTS)
        self.clients: set[WebSocket] = set()
        self.last_tick: dict | None = None
        self.vision: dict | None = None
        self.vision_at = 0.0
        self.vision_online = False
        self.esp = NoEsp()
        self.engine = None
        self.rng = random.Random(0)

    # --- called from any thread ---
    def publish(self, msg: dict) -> None:
        if self.loop is not None:
            self.loop.call_soon_threadsafe(self._dispatch, msg)

    def server_event(self, kind: str, msg: str, level: str = "info") -> None:
        t = self.last_tick["sim_time"] if self.last_tick else 0
        self.publish(Event(sim_time=t, kind=kind, level=level, msg=msg).model_dump())

    # --- asyncio thread ---
    def _dispatch(self, msg: dict) -> None:
        if msg["type"] == "tick":
            msg["esp"] = self.esp.status()
            msg["vision"] = self._vision_status()
            msg = Tick.model_validate(msg).model_dump()
            self.last_tick = msg
            self.history.append(msg)
        elif msg["type"] == "event":
            if msg["kind"] == "reset":
                self.history.clear()
            self.events.append(msg)
        asyncio.ensure_future(self._broadcast(msg))

    def _vision_status(self) -> dict:
        if self.mock and self.cfg["vision"]["enabled"]:
            from server.mock import mock_vision
            return mock_vision(self.rng)
        fresh = self.vision is not None and time.monotonic() - self.vision_at < VISION_TIMEOUT_S
        if fresh != self.vision_online:
            self.vision_online = fresh
            if fresh:
                self.server_event("vision_online", "Camera Piața Unirii: date primite")
            else:
                self.server_event("vision_offline", "Camera Piața Unirii: fără date de 5 s", "warn")
        if not fresh:
            return {"online": False, "source": None, "queues": {}, "avg_stop_s": None}
        v = self.vision
        return {"online": True, "source": v["source"], "queues": v["queues"], "avg_stop_s": v["avg_stop_s"]}

    async def _send(self, ws: WebSocket, msg: dict) -> bool:
        try:
            await asyncio.wait_for(ws.send_json(msg), WS_SEND_TIMEOUT_S)
            return True
        except Exception:
            return False

    async def _broadcast(self, msg: dict) -> None:
        clients = list(self.clients)
        results = await asyncio.gather(*(self._send(ws, msg) for ws in clients))
        for ws, ok in zip(clients, results):
            if not ok:
                self.clients.discard(ws)


def create_app(cfg: dict, mock: bool, serial: bool, controller: str) -> FastAPI:
    hub = Hub(cfg, mock)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        hub.loop = asyncio.get_running_loop()
        if mock:
            from server.mock import MockEngine, MockEsp
            hub.engine = MockEngine(cfg, hub.publish, controller)
            if serial:
                hub.esp = MockEsp(hub.server_event)
        else:
            from server.sim_engine import SimEngine
            hub.engine = SimEngine(cfg, hub.publish, controller)
            if serial:
                from server.serial_bridge import SerialBridge
                hub.esp = SerialBridge(cfg, hub.server_event, hub.engine.latest_state)
                hub.esp.start()
        hub.engine.start()
        yield
        hub.engine.stop()
        if hasattr(hub.esp, "stop"):
            hub.esp.stop()

    app = FastAPI(title="Semafoare AI", lifespan=lifespan)
    app.add_middleware(
        CORSMiddleware,
        allow_origins=["http://localhost:5173", "http://127.0.0.1:5173"],
        allow_methods=["*"],
        allow_headers=["*"],
    )

    @app.post("/api/rush", response_model=OkResponse)
    def rush(body: RushRequest | None = None):
        hub.engine.submit("rush", vehicles=body.vehicles if body else None)
        return OkResponse()

    @app.post("/api/reset", response_model=OkResponse)
    def reset():
        hub.engine.submit("reset")
        return OkResponse()

    @app.post("/api/controller", response_model=OkResponse)
    def set_controller(body: ControllerRequest):
        hub.engine.submit("controller", name=body.name)
        return OkResponse()

    @app.post("/api/heartbeat", response_model=OkResponse)
    def heartbeat(body: HeartbeatRequest):
        hub.esp.set_heartbeat(body.enabled)
        if body.enabled:
            hub.server_event("heartbeat_resumed", "Serverul trimite din nou comenzi către ESP32")
        else:
            hub.server_event("heartbeat_paused", "Cădere simulată: serverul nu mai trimite comenzi", "warn")
        return OkResponse()

    @app.get("/api/state")
    def state():
        public = {
            "location": cfg["location"],
            "tls": cfg["tls"],
            "sim": cfg["sim"],
            "rush_hour": cfg["rush_hour"],
            "vision": {"enabled": cfg["vision"]["enabled"], "stream_port": cfg["vision"]["stream_port"]},
            "mock": mock,
        }
        return {"tick": hub.last_tick, "config": public}

    @app.get("/api/results")
    def results():
        """Multi-seed evaluation (ai/evaluate.py), for the Results page."""
        import csv
        path = ROOT / "results" / "eval_summary.csv"
        if not path.exists():
            return {"rows": []}
        with path.open(encoding="utf-8") as f:
            rows = [{k: (float(v) if v not in ("", None) and k not in ("variant", "scenario") else (v or None))
                     for k, v in r.items()} for r in csv.DictReader(f)]
        return {"rows": rows}

    network_cache: dict = {}

    @app.get("/api/network")
    def network():
        if not network_cache:
            from server.network import build_network
            network_cache.update(build_network(cfg))
        return network_cache

    @app.post("/api/vision", response_model=OkResponse)
    def vision(body: VisionReport):
        hub.vision, hub.vision_at = body.model_dump(), time.monotonic()
        return OkResponse()

    @app.post("/api/spawn", response_model=OkResponse)
    def spawn(body: SpawnRequest):
        hub.engine.submit("spawn", approach=body.approach)
        return OkResponse()

    @app.websocket("/ws")
    async def ws(websocket: WebSocket):
        await websocket.accept()
        await websocket.send_json({"type": "history", "ticks": list(hub.history)})
        for event in list(hub.events):
            await websocket.send_json(event)
        hub.clients.add(websocket)
        try:
            while True:
                await websocket.receive_text()  # clients do not send; this just detects disconnects
        except WebSocketDisconnect:
            pass
        finally:
            hub.clients.discard(websocket)

    dist = ROOT / "web" / "dist"
    if dist.is_dir():
        app.mount("/", StaticFiles(directory=dist, html=True), name="web")
    return app


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--mock", action="store_true", help="fake telemetry, no SUMO")
    p.add_argument("--no-serial", action="store_true", help="no ESP32")
    p.add_argument("--controller", default=None)
    p.add_argument("--serial-port", default=None, help="override serial.port (e.g. the pty printed by scripts/fake_esp.py)")
    a = p.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    if a.serial_port:
        cfg["serial"]["port"] = a.serial_port
    app = create_app(cfg, a.mock, not a.no_serial, a.controller or cfg["controller"])
    uvicorn.run(app, host=cfg["server"]["host"], port=cfg["server"]["port"], log_level="warning")


if __name__ == "__main__":
    main()
