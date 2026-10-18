"""Runs the AI simulation and the classic (fixed program) simulation in lockstep (PLAN.md §9).

Only this thread touches TraCI. The API talks to it through submit() (a queue) and reads latest_state().
The controller decides every rl.delta_time seconds, but both simulations advance and publish one simulated
second at a time, paced to sim.speed, so the dashboard moves smoothly instead of jumping every few seconds.
"""
import math
import os
import queue
import sys
import threading
import time
from pathlib import Path

import sumolib

from ai.env_factory import make_demo_env  # sets SUMO_HOME, patches sumo-rl
import traci  # noqa: E402  (after env_factory: needs SUMO_HOME)

from controllers import make_controller
from controllers.spillback_guard import SpillbackGuard
from server.metrics import SimMetrics, approaches_of, improvement_pct
from server.schemas import Event

SPAWN_ROUTES = {"blv_dir1": "blv_dir1", "blv_dir2": "blv_dir2", "lateral": "lat_in", "lat_in": "lat_in"}


def gui_available() -> bool:
    """sumo-gui needs an X server on macOS (XQuartz); on Windows it must ship with the SUMO install."""
    if sys.platform == "win32":
        return (Path(os.environ.get("SUMO_HOME", "")) / "bin" / "sumo-gui.exe").exists()
    if sys.platform == "darwin":
        return Path("/opt/X11").exists() or bool(os.environ.get("DISPLAY"))
    if sys.platform.startswith("linux"):
        return bool(os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY"))
    return True


class SimEngine(threading.Thread):
    def __init__(self, cfg: dict, publish, controller: str):
        super().__init__(daemon=True, name="SimEngine")
        self.cfg = cfg
        self.publish = publish
        self.controller_name = controller
        self.commands: queue.Queue = queue.Queue()
        self.stopping = False
        self._state_lock = threading.Lock()
        self._state: dict | None = None
        self.labels = cfg["tls"]["phase_labels"]
        gui_cfg = cfg["sim"].get("gui", "auto")
        self.use_gui = gui_available() if gui_cfg == "auto" else bool(gui_cfg)
        self.net = sumolib.net.readNet(cfg["sumo"]["net"])
        self.ai_env = None
        self.fix = None

    # --- public API (any thread) ---
    def submit(self, cmd: str, **kw) -> None:
        self.commands.put((cmd, kw))

    def stop(self) -> None:
        self.stopping = True

    def latest_state(self) -> dict | None:
        """Main intersection state for the SerialBridge."""
        with self._state_lock:
            return self._state

    # --- engine thread ---
    def _event(self, kind: str, msg: str, level: str = "info") -> None:
        t = self.ai_env.sim_step if self.ai_env and self.ai_env.sumo else 0.0
        self.publish(Event(sim_time=t, kind=kind, level=level, msg=msg).model_dump())

    def _start(self) -> None:
        cfg = self.cfg
        seed = cfg["sumo"]["seed"]
        extra = ""
        if self.use_gui:
            delay = int(1000 / cfg["sim"]["speed"])
            extra = f"--gui-settings-file {cfg['sumo']['gui_settings']} --delay {delay}"
        self.ai_env = make_demo_env(cfg, use_gui=self.use_gui, seed=seed, extra_cmd=extra)
        self.obs = self.ai_env.reset()
        fix_cmd = [
            sumolib.checkBinary("sumo"), "-n", cfg["sumo"]["net"], "-r", cfg["sumo"]["routes"],
            "--seed", str(seed), "--time-to-teleport", str(cfg["sumo"]["time_to_teleport"]),
            "--waiting-time-memory", str(self.ai_env.waiting_time_memory),  # same as sumo-rl's AI sim
            "--no-step-log", "--no-warnings",
        ]
        label = f"fix_{time.monotonic_ns()}"
        traci.start(fix_cmd, label=label)
        self.fix = traci.getConnection(label)

        tls = cfg["tls"]["ids"]
        self.lane_approach: dict[str, str] = {}
        self.in_lanes: dict[str, list[str]] = {}
        for ts in tls:
            dirs = approaches_of(self.net, ts)
            lanes = [l for l in dict.fromkeys(self.fix.trafficlight.getControlledLanes(ts)) if not l.startswith(":")]
            self.in_lanes[ts] = [l for l in lanes if l.rsplit("_", 1)[0] in dirs]
            self.lane_approach.update({l: dirs[l.rsplit("_", 1)[0]] for l in self.in_lanes[ts]})
        all_in = [l for ts in tls for l in self.in_lanes[ts]]
        self.ids: dict[str, int] = {}
        self.m_ai = SimMetrics(self.ai_env.sumo, all_in, self.ids)
        self.m_fix = SimMetrics(self.fix, all_in, self.ids)
        # advance the classic sim and publish after every simulated second of the AI sim
        original_step = self.ai_env._sumo_step

        def step_one_second():
            original_step()
            self._second()

        self.ai_env._sumo_step = step_one_second
        self.deadline = time.monotonic()
        self._set_controller(self.controller_name, announce=False)
        self.guard = SpillbackGuard(cfg)
        self.guard.reset(self.ai_env)
        self.rush_pending = 0
        self.rush_ids: set[str] = set()
        self.rush_k = 0
        self.spawn_k = 0
        self.held = {ts: False for ts in tls}

    def _close(self) -> None:
        for close in (lambda: self.ai_env.close(), lambda: self.fix.close()):
            try:
                close()
            except Exception:
                pass

    def _set_controller(self, name: str, announce: bool = True) -> None:
        try:
            controller = make_controller(name, self.cfg)
        except Exception as e:  # e.g. PPO model not trained yet
            if announce:
                self._event("controller_changed", f"Controlerul {name} nu poate porni: {e}", "error")
                return
            print(f"[SimEngine] controller {name} failed ({e}), falling back to max_pressure", flush=True)
            name, controller = "max_pressure", make_controller("max_pressure", self.cfg)
        controller.reset(self.ai_env)
        self.controller, self.controller_name = controller, name
        if announce:
            self._event("controller_changed", f"Controler AI: {name}")

    def _add_both(self, vid: str, route: str) -> None:
        for conn in (self.ai_env.sumo, self.fix):
            conn.vehicle.add(vid, route, typeID="car", depart="now", departLane="best")

    def _apply_commands(self) -> None:
        while True:
            try:
                cmd, kw = self.commands.get_nowait()
            except queue.Empty:
                return
            if cmd == "rush":
                n = kw.get("vehicles") or self.cfg["rush_hour"]["vehicles"]
                self.rush_pending += n
                self._event("rush_hour", f"Rush Hour: +{n} vehicule pe bulevard")
            elif cmd == "reset":
                self._close()
                self._start()
                self._event("reset", "Simulările au fost repornite")
            elif cmd == "controller":
                self._set_controller(kw["name"])
            elif cmd == "spawn":
                route = SPAWN_ROUTES.get(kw["approach"])
                if route:
                    self._add_both(f"real_{self.spawn_k}", route)
                    self.spawn_k += 1

    def _inject_rush(self) -> None:
        """Spread pending Rush Hour vehicles over rush_hour.spread_s, same ids in both sims (called every second)."""
        if self.rush_pending <= 0:
            return
        rh = self.cfg["rush_hour"]
        per_second = max(1, math.ceil(rh["vehicles"] / rh["spread_s"]))
        for _ in range(min(per_second, self.rush_pending)):
            vid = f"rush_{self.rush_k}"
            self._add_both(vid, rh["routes"][self.rush_k % len(rh["routes"])])
            self.rush_ids.add(vid)
            self.rush_k += 1
            self.rush_pending -= 1

    def _rush_active(self) -> bool:
        """Rush Hour lasts until every rush vehicle (running or waiting to enter) has left both sims."""
        if not self.rush_ids and self.rush_pending == 0:
            return False
        alive: set[str] = set()
        for conn in (self.ai_env.sumo, self.fix):
            alive |= set(conn.vehicle.getIDList()) | set(conn.simulation.getPendingVehicles())
        self.rush_ids &= alive
        if self.rush_pending == 0 and not self.rush_ids:
            self._event("rush_end", "Rush Hour s-a încheiat: toate vehiculele au ieșit")
            return False
        return True

    def _intersections(self) -> list[dict]:
        out = []
        halted = self.m_ai.halted_by_lane()
        for ts_id, ts in self.ai_env.traffic_signals.items():
            queues: dict[str, int] = {}
            for l in self.in_lanes[ts_id]:
                a = self.lane_approach[l]
                queues[a] = queues.get(a, 0) + halted.get(l, 0)
            hold = self.guard.holds.get(ts_id, False)
            if hold and not self.held[ts_id]:
                self._event("spillback_hold", f"{ts_id} reține fluxul: banda spre intersecția vecină e plină", "warn")
            self.held[ts_id] = hold
            labels = self.labels.get(ts_id, [])
            green_s = ts.time_since_last_phase_change - (0 if ts.is_yellow else ts.yellow_time)
            out.append({
                "id": ts_id,
                "green_phase": ts.green_phase,
                "phase_label": labels[ts.green_phase] if ts.green_phase < len(labels) else str(ts.green_phase),
                "state": "yellow" if ts.is_yellow else "green",
                "time_in_phase_s": max(0, green_s),
                "queues": queues,
                "hold": hold,
            })
        return out

    def _second(self) -> None:
        """One simulated second: catch the classic sim up, read both, publish tick + frame, keep real-time pace."""
        self.fix.simulationStep()
        self._inject_rush()
        self.m_ai.step()
        self.m_fix.step()
        t = self.ai_env.sim_step
        ai_m = self.m_ai.metrics(t)
        fix_m = self.m_fix.metrics(t)
        intersections = self._intersections()
        tick = {
            "type": "tick",
            "sim_time": t,
            "controller": self.controller_name,
            "rush_active": self._rush_active(),
            "fix": fix_m,
            "ai": ai_m,
            "improvement_pct": improvement_pct(t, self.m_fix, self.m_ai, fix_m, ai_m),
            "intersections": intersections,
        }
        main = next(i for i in intersections if i["id"] == self.cfg["tls"]["main"])
        with self._state_lock:
            self._state = {
                "phase": main["green_phase"],
                "queue": sum(main["queues"].values()),
                "wait": ai_m["avg_wait_s"],
                "controller": self.controller_name,
            }
        tls = self.cfg["tls"]["ids"]
        self.publish(tick)
        self.publish({"type": "frame", "sim_time": t, "fix": self.m_fix.frame(tls), "ai": self.m_ai.frame(tls)})
        # pace on an absolute schedule so small delays do not accumulate into stutter
        self.deadline += 1.0 / self.cfg["sim"]["speed"]
        lag = self.deadline - time.monotonic()
        if lag > 0:
            time.sleep(lag)
        elif lag < -1.0:
            self.deadline = time.monotonic()

    def run(self) -> None:
        try:
            self._start()
        except Exception as e:
            print(f"[SimEngine] start failed: {e}", flush=True)
            raise
        while not self.stopping:
            try:
                self._apply_commands()
                actions = self.controller.act(self.obs, self.ai_env)
                actions = self.guard.filter(actions, self.ai_env)
                self.obs, _, dones, _ = self.ai_env.step(actions)  # runs delta_time x _second()
                if dones["__all__"]:  # end of the scenario: start over
                    self._close()
                    self._start()
                    self._event("reset", "Scenariul s-a terminat, simulările repornesc")
            except traci.exceptions.FatalTraCIError as e:
                # sumo-gui closed by hand or SUMO crashed: restart both
                print(f"[SimEngine] TraCI error ({e}), restarting", flush=True)
                self._close()
                self._start()
                self._event("reset", "Simularea a fost repornită după o eroare", "warn")
        self._close()
