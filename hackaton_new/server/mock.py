"""Fake telemetry for frontend development without SUMO (PLAN.md §10).

MockEngine has the same surface as SimEngine: a thread that reads commands from a queue
and calls publish(msg_dict) for every tick / event. The hub fills in `esp` and `vision`.
"""
import math
import queue
import random
import threading
import time

from server.schemas import Event, IntersectionState, SimMetrics

# approaches per junction, used by both the mock and the dashboard schematic
APPROACHES = {"A": ["V", "E", "S"], "B": ["V", "E", "N", "S"], "C": ["N", "E"], "D": ["E", "S", "V"], "E": ["N", "E", "S", "V"]}
RUSH_EFFECT_S = 240


class MockEngine(threading.Thread):
    def __init__(self, cfg: dict, publish, controller: str):
        super().__init__(daemon=True, name="MockEngine")
        self.cfg = cfg
        self.publish = publish
        self.controller = controller
        self.commands: queue.Queue = queue.Queue()
        self.stopping = False
        self.rng = random.Random(cfg["sumo"]["seed"])
        self.labels = cfg["tls"]["phase_labels"]
        self._reset_state()

    # --- public API (any thread) ---
    def submit(self, cmd: str, **kw) -> None:
        self.commands.put((cmd, kw))

    def stop(self) -> None:
        self.stopping = True

    # --- engine thread ---
    def _reset_state(self) -> None:
        self.t = 0.0
        self.rush_until = -1.0
        self.rush_started = -1.0
        self.rush_size = 0
        self.fix_trip = self.ai_trip = None
        self.tls = {
            tl: {"phase": 0, "in_phase": 0.0, "dur": self.rng.uniform(15, 40), "yellow": 0.0}
            for tl in self.cfg["tls"]["ids"]
        }

    def _event(self, kind: str, msg: str, level: str = "info") -> None:
        self.publish(Event(sim_time=self.t, kind=kind, level=level, msg=msg).model_dump())

    def _apply_commands(self) -> None:
        while True:
            try:
                cmd, kw = self.commands.get_nowait()
            except queue.Empty:
                return
            if cmd == "rush":
                n = kw.get("vehicles") or self.cfg["rush_hour"]["vehicles"]
                self.rush_started, self.rush_size = self.t, n
                self.rush_until = self.t + RUSH_EFFECT_S
                self._event("rush_hour", f"Rush Hour: +{n} vehicule pe bulevard")
            elif cmd == "reset":
                self._reset_state()
                self._event("reset", "Simulările au fost repornite")
            elif cmd == "controller":
                self.controller = kw["name"]
                self._event("controller_changed", f"Controler AI: {self.controller}")
            elif cmd == "spawn":
                pass  # twin mode: nothing to show in the mock

    def _demand(self) -> float:
        """Base load 0..1 following the normal / peak / normal profile of routes.rou.xml."""
        ep = self.cfg["sim"]["episode_s"]
        x = (self.t % ep) / ep
        return 0.45 + 0.4 * math.exp(-((x - 0.5) ** 2) / 0.02)

    def _rush_boost(self) -> float:
        if self.t > self.rush_until:
            return 0.0
        age = self.t - self.rush_started
        return (self.rush_size / 200) * math.sin(math.pi * age / RUSH_EFFECT_S) ** 0.7

    def _metrics(self, load: float, factor: float) -> SimMetrics:
        n = self.rng.gauss
        wait = max(1.0, (12 + 55 * load ** 2) * factor + n(0, 1.5))
        return SimMetrics(
            avg_wait_s=round(wait, 1),
            queue_veh=max(0, int((8 + 70 * load ** 2) * factor + n(0, 2))),
            throughput_vph=round(1400 + 1800 * min(load, 1.0) * (1.04 if factor < 1 else 1.0) + n(0, 30)),
            trip_wait_s=0.0,
        )

    def _intersections(self, dt: float, load: float) -> list[dict]:
        out = []
        for tl, s in self.tls.items():
            if s["yellow"] > 0:
                s["yellow"] -= dt
                if s["yellow"] <= 0:
                    s["phase"] = (s["phase"] + 1) % len(self.labels[tl])
                    s["in_phase"], s["dur"] = 0.0, self.rng.uniform(10, 40)
            else:
                s["in_phase"] += dt
                if s["in_phase"] >= s["dur"]:
                    s["yellow"] = self.cfg["tls"]["yellow_s"]
            state = "yellow" if s["yellow"] > 0 else "green"
            queues = {a: max(0, int(self.rng.gauss(6 * load + (4 if a == "V" else 0), 2))) for a in APPROACHES[tl]}
            hold = tl == "B" and self.t <= self.rush_until and self.rng.random() < 0.15
            if hold:
                self._event("spillback_hold", "B saturat: A reține fluxul spre B", "warn")
            out.append(IntersectionState(
                id=tl, green_phase=s["phase"], phase_label=self.labels[tl][s["phase"]], state=state,
                time_in_phase_s=round(s["in_phase"]), queues=queues, hold=hold,
            ).model_dump())
        return out

    def run(self) -> None:
        dt = 1.0  # one tick per simulated second, like SimEngine
        interval = 1.0 / self.cfg["sim"]["speed"]
        rush_was_active = False
        while not self.stopping:
            started = time.monotonic()
            self._apply_commands()
            self.t += dt
            load = self._demand() + self._rush_boost()
            fix = self._metrics(load, 1.0)
            ai = self._metrics(load, 0.55 if self.controller == "ppo" else 0.62)
            # trip wait = slow-moving average of the current wait (what exiting vehicles carried)
            self.fix_trip = fix.avg_wait_s if self.fix_trip is None else 0.9 * self.fix_trip + 0.1 * fix.avg_wait_s
            self.ai_trip = ai.avg_wait_s if self.ai_trip is None else 0.9 * self.ai_trip + 0.1 * ai.avg_wait_s
            fix.trip_wait_s, ai.trip_wait_s = round(self.fix_trip, 1), round(self.ai_trip, 1)
            rush_active = self.t <= self.rush_until
            if rush_was_active and not rush_active:
                self._event("rush_end", "Rush Hour s-a încheiat: toate vehiculele au ieșit")
            rush_was_active = rush_active
            improvement = None
            if self.t >= 120:
                improvement = round((ai.trip_wait_s - fix.trip_wait_s) / fix.trip_wait_s * 100, 1)
            self.publish({
                "type": "tick",
                "sim_time": self.t,
                "controller": self.controller,
                "rush_active": rush_active,
                "fix": fix.model_dump(),
                "ai": ai.model_dump(),
                "improvement_pct": improvement,
                "intersections": self._intersections(dt, load),
            })
            time.sleep(max(0.0, interval - (time.monotonic() - started)))


class MockEsp:
    """Pretends a board is attached: goes offline / AVARIE 2 s after the heartbeat stops."""

    def __init__(self, on_event):
        self.on_event = on_event
        self.enabled = True
        self.changed_at = time.monotonic()
        self.online = True

    def set_heartbeat(self, enabled: bool) -> None:
        self.enabled, self.changed_at = enabled, time.monotonic()

    def status(self) -> dict:
        elapsed = time.monotonic() - self.changed_at
        online = self.enabled and elapsed > 1.5 or (not self.enabled and elapsed < 2.0)
        if online != self.online:
            self.online = online
            if online:
                self.on_event("esp_online", "ESP32 conectat, revine la comanda AI", "info")
            else:
                self.on_event("esp_offline", "ESP32 offline: semaforul trece pe avarie", "error")
        return {"online": online, "last_ack_ms": 120 if online else int(elapsed * 1000), "mode": "AI" if online else "AVARIE"}


def mock_vision(rng: random.Random) -> dict:
    return {
        "online": True,
        "source": "file",
        "queues": {"blv_dir1": max(0, int(rng.gauss(7, 2))), "lateral": max(0, int(rng.gauss(3, 1)))},
        "avg_stop_s": round(max(0.0, rng.gauss(24, 3)), 1),
    }
