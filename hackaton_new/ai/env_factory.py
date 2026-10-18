"""Builds the sumo-rl environments from config.yaml, identically for training, evaluation and the demo.

    python -m ai.env_factory --smoke     # one episode with random actions, prints obs sizes and rewards
"""
import argparse
import os
import time

import numpy as np
import yaml

if "SUMO_HOME" not in os.environ:
    import sumo

    os.environ["SUMO_HOME"] = sumo.SUMO_HOME

import sumo_rl  # noqa: E402
import sumo_rl.environment.env as _sumo_rl_env  # noqa: E402
from pettingzoo.utils import AgentSelector  # noqa: E402
from sumo_rl.environment.traffic_signal import TrafficSignal  # noqa: E402

# Compatibility of sumo-rl 1.4.5 with pettingzoo 1.27 / supersuit 3.11:
# - it calls pettingzoo's old `agent_selector` class, which is now a module
# - supersuit reads `render_mode` from the PettingZoo env, which never sets it
_sumo_rl_env.agent_selector = AgentSelector
_sumo_rl_env.SumoEnvironmentPZ.render_mode = None

from ai.observation import NeighborObservation  # noqa: E402
from ai.reward import traffic_reward  # noqa: E402


def _patch_max_green() -> None:
    """sumo-rl accepts max_green but never enforces it: force a switch before green exceeds max_green."""
    if getattr(TrafficSignal, "_max_green_patched", False):
        return
    original = TrafficSignal.set_next_phase

    def set_next_phase(self, new_phase):
        new_phase = int(new_phase)
        green_s = self.time_since_last_phase_change - self.yellow_time
        if new_phase == self.green_phase and not self.is_yellow and green_s + self.delta_time > self.max_green:
            new_phase = (self.green_phase + 1) % self.num_green_phases
        original(self, new_phase)

    TrafficSignal.set_next_phase = set_next_phase
    TrafficSignal._max_green_patched = True


_patch_max_green()


def load_config(path: str = "config.yaml") -> dict:
    with open(path, encoding="utf-8") as f:
        return yaml.safe_load(f)


def env_kwargs(cfg: dict, *, use_gui: bool = False, seed="random", routes: str | None = None,
               extra_cmd: str = "") -> dict:
    """Parameters shared by training and the demo; only gui / seed / routes may differ."""
    return dict(
        net_file=cfg["sumo"]["net"],
        route_file=routes or cfg["sumo"]["routes"],
        use_gui=use_gui,
        num_seconds=cfg["sim"]["episode_s"],
        delta_time=cfg["rl"]["delta_time"],
        yellow_time=cfg["tls"]["yellow_s"],
        min_green=cfg["tls"]["min_green_s"],
        max_green=cfg["tls"]["max_green_s"],
        time_to_teleport=cfg["sumo"]["time_to_teleport"],
        reward_fn=traffic_reward,
        observation_class=NeighborObservation,
        sumo_seed=seed,
        sumo_warnings=False,
        add_per_agent_info=False,
        additional_sumo_cmd=f"--no-step-log {extra_cmd}".strip(),
    )


def make_parallel_env(cfg: dict, **kw):
    """PettingZoo parallel env, one agent per traffic light (training)."""
    return sumo_rl.parallel_env(**env_kwargs(cfg, **kw))


def make_demo_env(cfg: dict, **kw) -> sumo_rl.SumoEnvironment:
    """Dict-style SumoEnvironment (evaluation, SimEngine): same observation code as training."""
    return sumo_rl.SumoEnvironment(**env_kwargs(cfg, **kw))


def obs_size(env) -> int:
    """Largest observation size across agents; supersuit pads every agent to this size during training."""
    spaces = env.observation_spaces if isinstance(env.observation_spaces, dict) else None
    if spaces is None:
        spaces = {ts: env.observation_spaces(ts) for ts in env.ts_ids}
    return max(s.shape[0] for s in spaces.values())


def pad_obs(obs: np.ndarray, size: int) -> np.ndarray:
    """Zero-pad at the end, exactly like supersuit.pad_observations_v0."""
    return np.pad(obs, (0, size - obs.shape[0])) if obs.shape[0] < size else obs


def smoke(cfg: dict, seconds: int) -> None:
    cfg = {**cfg, "sim": {**cfg["sim"], "episode_s": seconds}}
    env = make_parallel_env(cfg, seed=cfg["sumo"]["seed"])
    obs, _ = env.reset(seed=cfg["sumo"]["seed"])
    print("agents:", env.agents)
    for a in env.agents:
        print(f"  {a}: obs {env.observation_space(a).shape}, actions {env.action_space(a).n}, lanes in/out "
              f"{len(env.unwrapped.env.traffic_signals[a].lanes)}/{len(env.unwrapped.env.traffic_signals[a].out_lanes)}")
    totals = {a: 0.0 for a in env.agents}
    longest_green = {a: 0 for a in env.agents}
    steps, started = 0, time.time()
    while env.agents:
        actions = {a: env.action_space(a).sample() for a in env.agents}
        obs, rewards, terms, truncs, infos = env.step(actions)
        for a, r in rewards.items():
            totals[a] += r
            ts = env.unwrapped.env.traffic_signals[a]
            longest_green[a] = max(longest_green[a], ts.time_since_last_phase_change - ts.yellow_time)
        for a, o in obs.items():
            assert np.all(np.isfinite(o)) and o.min() >= 0 and o.max() <= 1, (a, o)
        steps += 1
    env.close()
    print(f"steps: {steps} ({seconds} s simulated) in {time.time() - started:.1f} s")
    print("total reward:", {a: round(v, 1) for a, v in totals.items()})
    print("longest green seen (s):", longest_green, "max_green:", cfg["tls"]["max_green_s"])


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--smoke", action="store_true")
    p.add_argument("--seconds", type=int, default=None, help="smoke episode length (default: sim.episode_s)")
    a = p.parse_args()
    cfg = load_config(a.config)
    if a.smoke:
        smoke(cfg, a.seconds or cfg["sim"]["episode_s"])


if __name__ == "__main__":
    main()
