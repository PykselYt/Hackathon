"""Headless sanity check of the Piața Unirii network (PLAN.md §6 step 6).

    python scripts/check_net.py                  # 3600 s on the fixed program, seed from config
    python scripts/check_net.py --rush 20 40 60  # also inject N vehicles at t=900 and look for gridlock
    python scripts/check_net.py --net actuated   # same, on the actuated network

Reports teleports, max queue on the incoming lanes of A and B, mean trip wait, and
whether every vehicle left the network (no gridlock).
"""
import argparse
import os
import sys

import yaml

if "SUMO_HOME" not in os.environ:
    import sumo

    os.environ["SUMO_HOME"] = sumo.SUMO_HOME
import traci  # noqa: E402

RUSH_AT = 900


def run(cfg: dict, net: str, seed: int, rush: int = 0) -> dict:
    rh = cfg["rush_hour"]
    cmd = [
        "sumo", "-n", net, "-r", cfg["sumo"]["routes"],
        "--seed", str(seed), "--time-to-teleport", str(cfg["sumo"]["time_to_teleport"]),
        "--no-step-log", "--no-warnings", "--end", str(cfg["sim"]["episode_s"] + 1800),
    ]
    traci.start(cmd, label="check")
    conn = traci.getConnection("check")
    in_lanes = sorted({l for tl in cfg["tls"]["ids"] for l in conn.trafficlight.getControlledLanes(tl)})
    max_queue, teleports, waits, last_wait = 0, 0, [], {}
    stuck_s, injected = 0, 0
    t = 0
    while True:
        t = conn.simulation.getTime()
        if rush and RUSH_AT <= t < RUSH_AT + rh["spread_s"] and injected < rush:
            per_step = -(-rush // rh["spread_s"])
            for _ in range(min(per_step, rush - injected)):
                route = rh["routes"][injected % len(rh["routes"])]
                conn.vehicle.add(f"rush_{injected}", route, typeID="car", depart="now", departLane="best")
                injected += 1
        conn.simulationStep()
        for v in conn.vehicle.getIDList():
            last_wait[v] = conn.vehicle.getAccumulatedWaitingTime(v)
        for v in conn.simulation.getArrivedIDList():
            waits.append(last_wait.pop(v, 0.0))
        teleports += conn.simulation.getStartingTeleportNumber()
        q = sum(conn.lane.getLastStepHaltingNumber(l) for l in in_lanes)
        max_queue = max(max_queue, q)
        n = conn.vehicle.getIDCount()
        moving = sum(1 for v in conn.vehicle.getIDList() if conn.vehicle.getSpeed(v) > 0.1)
        stuck_s = stuck_s + 1 if n > 0 and moving == 0 else 0
        if stuck_s > 120:
            break
        if t >= cfg["sim"]["episode_s"] and conn.simulation.getMinExpectedNumber() == 0:
            break
    left = conn.simulation.getMinExpectedNumber()
    traci.switch("check")
    traci.close()
    return {
        "rush": rush,
        "end_s": int(t),
        "arrived": len(waits),
        "left_in_net": left,
        "teleports": teleports,
        "max_queue": max_queue,
        "mean_wait_s": round(sum(waits) / max(1, len(waits)), 1),
        "gridlock": stuck_s > 120 or left > 0,
    }


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--net", choices=["static", "actuated"], default="static")
    p.add_argument("--seed", type=int, default=None)
    p.add_argument("--rush", type=int, nargs="*", default=[])
    a = p.parse_args()
    cfg = yaml.safe_load(open(a.config, encoding="utf-8"))
    net = cfg["sumo"]["net"] if a.net == "static" else cfg["sumo"]["net_actuated"]
    seed = cfg["sumo"]["seed"] if a.seed is None else a.seed
    ok = True
    for n in [0, *a.rush]:
        r = run(cfg, net, seed, n)
        print(" ".join(f"{k}={v}" for k, v in r.items()), flush=True)
        ok &= not r["gridlock"] and r["teleports"] == 0
    sys.exit(0 if ok else 1)


if __name__ == "__main__":
    main()
