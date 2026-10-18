"""Evaluate every variant on fixed seeds, normal traffic and Rush Hour (PLAN.md §8).

    python -m ai.evaluate --seeds 1 --controllers max_pressure          # smoke
    python -m ai.evaluate                                               # all variants, 5 seeds
    python -m ai.evaluate --routes sumo/routes_calibrated.rou.xml       # camera-calibrated demand

Variants: fixed_program (the network's static program), actuated (netconvert actuated program),
max_pressure, ppo, ppo+guard. Metrics come from SUMO tripinfo (unfinished vehicles included, so a
controller cannot look good by stranding cars). Writes results/eval.csv and results/eval.png.
"""
import argparse
import csv
import os
import statistics
import tempfile
import xml.etree.ElementTree as ET
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

os.environ.setdefault("LIBSUMO_AS_TRACI", "1")  # one SUMO per worker process, much faster than sockets

SEEDS = [11, 22, 33, 44, 55]
VARIANTS = ["fixed_program", "actuated", "max_pressure", "ppo", "ppo+guard"]
EXTRA_VARIANTS = ["fixed", "max_pressure+guard"]  # on request only; "fixed" = FixedController, a plumbing check
SCENARIOS = ["normal", "rush"]
RUSH_AT_S = 900


def run_one(cfg: dict, variant: str, scenario: str, seed: int, routes: str | None, model: str | None) -> dict:
    from ai.env_factory import make_demo_env
    from controllers import make_controller
    from controllers.spillback_guard import SpillbackGuard

    fixed_ts = variant in ("fixed_program", "actuated")
    run_cfg = cfg
    if variant == "actuated":
        run_cfg = {**cfg, "sumo": {**cfg["sumo"], "net": cfg["sumo"]["net_actuated"]}}
    fd, tripinfo = tempfile.mkstemp(suffix=".xml", prefix="tripinfo_")
    os.close(fd)
    extra = f"--tripinfo-output {tripinfo} --tripinfo-output.write-unfinished"
    env = make_demo_env(run_cfg, seed=seed, routes=routes, extra_cmd=extra)
    env.fixed_ts = fixed_ts
    obs = env.reset()
    controller = guard = None
    if not fixed_ts:
        name = variant.removesuffix("+guard")
        controller = make_controller(name, cfg, model)
        controller.reset(env)
        if variant.endswith("+guard"):
            guard = SpillbackGuard(cfg)
            guard.reset(env)
    in_lanes = sorted({l for ts in env.ts_ids for l in env.sumo.trafficlight.getControlledLanes(ts)})
    rh = cfg["rush_hour"]
    injected, max_queue, holds = 0, 0, 0
    done = False
    while not done:
        t = env.sim_step
        if scenario == "rush" and RUSH_AT_S <= t < RUSH_AT_S + rh["spread_s"] and injected < rh["vehicles"]:
            per_tick = -(-rh["vehicles"] * cfg["rl"]["delta_time"] // rh["spread_s"])
            for _ in range(min(per_tick, rh["vehicles"] - injected)):
                route = rh["routes"][injected % len(rh["routes"])]
                env.sumo.vehicle.add(f"rush_{injected}", route, typeID="car", depart="now", departLane="best")
                injected += 1
        if fixed_ts:
            obs, _, dones, _ = env.step(None)
        else:
            actions = controller.act(obs, env)
            if guard:
                actions = guard.filter(actions, env)
                holds += sum(guard.holds.values())
            obs, _, dones, _ = env.step(actions)
        done = dones["__all__"]
        max_queue = max(max_queue, sum(env.sumo.lane.getLastStepHaltingNumber(l) for l in in_lanes))
    env.close()

    waits, durations, arrived = [], [], 0
    for trip in ET.parse(tripinfo).getroot().iter("tripinfo"):
        waits.append(float(trip.get("waitingTime")))
        durations.append(float(trip.get("duration")))
        arrived += float(trip.get("arrival", "-1")) >= 0
    os.remove(tripinfo)
    hours = cfg["sim"]["episode_s"] / 3600
    return {
        "variant": variant, "scenario": scenario, "seed": seed,
        "mean_wait_s": round(statistics.fmean(waits), 2),
        "mean_duration_s": round(statistics.fmean(durations), 2),
        "arrived_per_h": round(arrived / hours, 1),
        "max_queue": max_queue,
        "vehicles": len(waits),
        "holds": holds,
    }


def summarize(rows: list[dict]) -> list[dict]:
    out = []
    for scenario in SCENARIOS:
        for variant in VARIANTS + EXTRA_VARIANTS:
            rs = [r for r in rows if r["variant"] == variant and r["scenario"] == scenario]
            if not rs:
                continue
            s = {"variant": variant, "scenario": scenario, "n": len(rs)}
            for k in ("mean_wait_s", "mean_duration_s", "arrived_per_h", "max_queue"):
                vals = [r[k] for r in rs]
                s[k] = statistics.fmean(vals)
                s[k + "_sd"] = statistics.stdev(vals) if len(vals) > 1 else 0.0
            out.append(s)
    for s in out:
        for base in ("fixed_program", "actuated"):
            ref = next((b for b in out if b["variant"] == base and b["scenario"] == s["scenario"]), None)
            s[f"vs_{base}_pct"] = (s["mean_wait_s"] - ref["mean_wait_s"]) / ref["mean_wait_s"] * 100 if ref else None
    return out


def plot(summary: list[dict], path: Path) -> None:
    import matplotlib

    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    fig, axes = plt.subplots(1, len(SCENARIOS), figsize=(11, 4.2), sharey=True)
    for ax, scenario in zip(axes, SCENARIOS):
        rs = [s for s in summary if s["scenario"] == scenario]
        names = [s["variant"] for s in rs]
        colors = ["#EF4444" if n == "fixed_program" else "#94A3B8" if n == "actuated" else "#22C55E" for n in names]
        ax.bar(names, [s["mean_wait_s"] for s in rs], yerr=[s["mean_wait_s_sd"] for s in rs], color=colors, capsize=4)
        ax.set_title("Trafic normal" if scenario == "normal" else "Cu Rush Hour")
        ax.tick_params(axis="x", rotation=20)
        ax.grid(axis="y", alpha=0.3)
    axes[0].set_ylabel("Așteptare medie / vehicul (s)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)


def main():
    from ai.env_factory import load_config

    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--seeds", type=int, default=len(SEEDS), help="how many of the fixed seeds")
    p.add_argument("--controllers", nargs="*", default=VARIANTS, help=f"subset of {VARIANTS + EXTRA_VARIANTS}")
    p.add_argument("--scenarios", nargs="*", default=SCENARIOS)
    p.add_argument("--routes", default=None)
    p.add_argument("--model", default=None, help="default: rl.model_path")
    p.add_argument("--workers", type=int, default=os.cpu_count())
    p.add_argument("--out", default="results/eval")
    a = p.parse_args()
    cfg = load_config(a.config)
    variants = [v for v in VARIANTS + EXTRA_VARIANTS if v in a.controllers]
    if not {"fixed_program", "actuated"} & set(variants):
        variants = ["fixed_program", *variants]  # always keep the baseline for the percentage
    jobs = [(cfg, v, sc, seed, a.routes, a.model) for sc in a.scenarios for v in variants for seed in SEEDS[: a.seeds]]
    print(f"{len(jobs)} runs on {a.workers} workers…", flush=True)
    with ProcessPoolExecutor(max_workers=a.workers) as pool:
        rows = list(pool.map(run_one, *zip(*jobs)))

    Path(a.out).parent.mkdir(parents=True, exist_ok=True)
    with open(f"{a.out}.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    summary = summarize(rows)
    with open(f"{a.out}_summary.csv", "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=list(summary[0]))
        w.writeheader()
        w.writerows(summary)
    plot(summary, Path(f"{a.out}.png"))

    print(f"\n{'scenario':8} {'variant':14} {'wait s':>14} {'trip s':>8} {'veh/h':>7} {'maxQ':>6} {'vs fix':>7} {'vs act':>7}")
    for s in summary:
        vf = f"{s['vs_fixed_program_pct']:+.0f}%" if s["vs_fixed_program_pct"] is not None else "-"
        va = f"{s['vs_actuated_pct']:+.0f}%" if s["vs_actuated_pct"] is not None else "-"
        print(f"{s['scenario']:8} {s['variant']:14} {s['mean_wait_s']:7.1f} ±{s['mean_wait_s_sd']:5.1f} "
              f"{s['mean_duration_s']:8.1f} {s['arrived_per_h']:7.0f} {s['max_queue']:6.0f} {vf:>7} {va:>7}")
    print(f"\nOK: {a.out}.csv, {a.out}_summary.csv, {a.out}.png")


if __name__ == "__main__":
    main()
