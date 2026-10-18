"""Metrics computed identically for the classic and the AI simulation (PLAN.md §9)."""
import itertools
import math
from collections import deque

import sumolib

SMOOTH_S = 30          # avg_wait_s is smoothed over this many simulated seconds
THROUGHPUT_S = 300     # throughput window
HALT_SPEED = 0.1       # m/s, same as SUMO's halting threshold


DIR_ANGLE = {"E": 0.0, "N": 90.0, "V": 180.0, "S": -90.0}


def _bearing(node, edge) -> float:
    """Angle (deg) from the junction towards where an incoming edge comes from, ~25 m upstream."""
    shape = edge.getLanes()[-1].getShape()
    nx, ny = node.getCoord()
    px, py = shape[0]
    for x, y in reversed(shape[:-1]):
        px, py = x, y
        if math.hypot(x - nx, y - ny) >= 25:
            break
    return math.degrees(math.atan2(py - ny, px - nx))


def approaches_of(net: sumolib.net.Net, node_id: str) -> dict[str, str]:
    """Incoming road edge -> N / S / E / V, distinct per junction, closest to the real geometry."""
    node = net.getNode(node_id)
    edges = [e for e in node.getIncoming() if e.getFunction() == "" and e.allows("passenger")]
    bearings = {e.getID(): _bearing(node, e) for e in edges}
    best, best_cost = {}, float("inf")
    for perm in itertools.permutations(DIR_ANGLE, len(edges)):
        cost = sum(abs((bearings[e.getID()] - DIR_ANGLE[d] + 180) % 360 - 180) for e, d in zip(edges, perm))
        if cost < best_cost:
            best, best_cost = {e.getID(): d for e, d in zip(edges, perm)}, cost
    return best


V_POS, V_ANGLE, V_SPEED, V_LANE, V_TYPE, V_WAIT = 0x42, 0x43, 0x40, 0x51, 0x4F, 0x87
VEHICLE_VARS = (V_POS, V_ANGLE, V_SPEED, V_LANE, V_TYPE, V_WAIT)
PERSON_VARS = (V_POS, V_ANGLE)


class SimMetrics:
    """Tracks one simulation through TraCI subscriptions; call step() once per simulated second.

    One call per second returns position, speed, lane and waiting time of every vehicle, which feeds both the
    metrics and the 3D frame.
    """

    def __init__(self, conn, in_lanes: list[str], ids: dict[str, int]):
        self.conn = conn
        self.in_lanes = set(in_lanes)
        self.ids = ids                                   # vehicle / person name -> short int, shared by both sims
        self.vehicles: dict[str, dict] = {}
        self.persons: dict[str, dict] = {}
        self.last_wait: dict[str, float] = {}
        self.trip_waits: list[float] = []
        self.arrivals: deque[float] = deque()          # arrival times, for throughput
        self.wait_hist: deque[tuple[float, float]] = deque()

    def _id(self, name: str) -> int:
        if name not in self.ids:
            self.ids[name] = len(self.ids)
        return self.ids[name]

    def step(self) -> None:
        """Subscribe newcomers and read everything; call right after the simulation advanced one second."""
        sim, veh, per = self.conn.simulation, self.conn.vehicle, self.conn.person
        for v in sim.getDepartedIDList():
            veh.subscribe(v, VEHICLE_VARS)
        for p in sim.getDepartedPersonIDList():
            per.subscribe(p, PERSON_VARS)
        self.vehicles = veh.getAllSubscriptionResults()
        self.persons = per.getAllSubscriptionResults()

    def metrics(self, t: float) -> dict:
        present = self.vehicles
        # vehicles gone since the last second have arrived; their last known wait is their trip wait
        for gone in self.last_wait.keys() - present.keys():
            self.trip_waits.append(self.last_wait.pop(gone))
            self.arrivals.append(t)
        self.last_wait = {v: r[V_WAIT] for v, r in present.items()}
        waits = list(self.last_wait.values())
        now = sum(waits) / len(waits) if waits else 0.0
        self.wait_hist.append((t, now))
        while self.wait_hist and self.wait_hist[0][0] <= t - SMOOTH_S:
            self.wait_hist.popleft()
        while self.arrivals and self.arrivals[0] <= t - THROUGHPUT_S:
            self.arrivals.popleft()
        span = min(THROUGHPUT_S, max(t, 1.0))
        queue = sum(1 for r in present.values() if r[V_SPEED] < HALT_SPEED and r[V_LANE] in self.in_lanes)
        return {
            "avg_wait_s": round(sum(w for _, w in self.wait_hist) / len(self.wait_hist), 1),
            "queue_veh": queue,
            "throughput_vph": round(len(self.arrivals) * 3600 / span),
            "trip_wait_s": round(sum(self.trip_waits) / len(self.trip_waits), 1) if self.trip_waits else 0.0,
        }

    def halted_by_lane(self) -> dict[str, int]:
        out: dict[str, int] = {}
        for r in self.vehicles.values():
            if r[V_SPEED] < HALT_SPEED and r[V_LANE] in self.in_lanes:
                out[r[V_LANE]] = out.get(r[V_LANE], 0) + 1
        return out

    def frame(self, tls_ids: list[str]) -> dict:
        veh = [
            [self._id(v), round(r[V_POS][0], 2), round(r[V_POS][1], 2), round(r[V_ANGLE], 1),
             1 if r[V_TYPE] == "bus" else 0, round(r[V_SPEED], 1)]
            for v, r in self.vehicles.items()
        ]
        ped = [[self._id(p), round(r[V_POS][0], 2), round(r[V_POS][1], 2), round(r[V_ANGLE], 1)]
               for p, r in self.persons.items()]
        tls = {t: self.conn.trafficlight.getRedYellowGreenState(t) for t in tls_ids}
        return {"veh": veh, "ped": ped, "tls": tls}

    @property
    def arrived(self) -> int:
        return len(self.trip_waits)


def improvement_pct(t: float, fix: SimMetrics, ai: SimMetrics, fix_m: dict, ai_m: dict) -> float | None:
    """(ai - fix) / fix * 100 on trip wait; None for the first 120 s or under 30 arrived vehicles per sim."""
    if t < 120 or fix.arrived < 30 or ai.arrived < 30 or fix_m["trip_wait_s"] <= 0:
        return None
    return round((ai_m["trip_wait_s"] - fix_m["trip_wait_s"]) / fix_m["trip_wait_s"] * 100, 1)
