"""Train one PPO policy shared by all traffic lights (PLAN.md §7).

    python -m ai.train --steps 5000                  # quick check: runs and saves a model
    python -m ai.train --steps 200000 --envs 4       # full training (watch: tensorboard --logdir results/tb)
    python -m ai.train --steps 100000 --resume ai/models/ppo_traffic.zip

Faster without the TraCI socket: LIBSUMO_AS_TRACI=1 (training only; needs --envs == --cpus, one SUMO per process).
"""
import argparse
import os
from pathlib import Path

import supersuit as ss
from stable_baselines3 import PPO
from stable_baselines3.common.callbacks import CheckpointCallback
from stable_baselines3.common.vec_env import VecMonitor, VecNormalize

from ai.env_factory import load_config, make_parallel_env


def make_vec_env(cfg: dict, num_envs: int, num_cpus: int, routes: str | None = None):
    env = make_parallel_env(cfg, seed="random", routes=routes)
    env = ss.pad_observations_v0(env)
    env = ss.pad_action_space_v0(env)
    env = ss.pettingzoo_env_to_vec_env_v1(env)
    env = ss.concat_vec_envs_v1(env, num_envs, num_cpus=num_cpus, base_class="stable_baselines3")
    # lights see very different reward scales (C ~ -0.4 / step, B ~ -18 / step): normalise rewards only,
    # observations stay raw so the demo needs no extra statistics
    return VecNormalize(VecMonitor(env), norm_obs=False, norm_reward=True, gamma=0.99)


def main():
    p = argparse.ArgumentParser()
    p.add_argument("--config", default="config.yaml")
    p.add_argument("--steps", type=int, default=200_000)
    p.add_argument("--envs", type=int, default=4, help="parallel SUMO episodes")
    p.add_argument("--cpus", type=int, default=None, help="worker processes (default: --envs)")
    p.add_argument("--routes", default=None, help="override sumo.routes (e.g. routes calibrated from the camera)")
    p.add_argument("--resume", default=None)
    p.add_argument("--out", default=None, help="default: rl.model_path")
    a = p.parse_args()
    cfg = load_config(a.config)
    cpus = a.cpus if a.cpus is not None else a.envs
    if os.environ.get("LIBSUMO_AS_TRACI") and cpus < a.envs:
        raise SystemExit("LIBSUMO_AS_TRACI allows one SUMO per process: use --cpus equal to --envs")

    env = make_vec_env(cfg, a.envs, cpus, a.routes)
    if a.resume:
        model = PPO.load(a.resume, env=env, tensorboard_log="results/tb")
    else:
        model = PPO(
            "MlpPolicy", env,
            learning_rate=3e-4, n_steps=512, batch_size=256, n_epochs=10,
            gamma=0.99, gae_lambda=0.95, clip_range=0.2, ent_coef=0.01,
            tensorboard_log="results/tb", verbose=1, device="cpu",
        )
    # save_freq counts vec-env steps; each one is envs x agents transitions
    per_call = a.envs * len(cfg["tls"]["ids"])
    ckpt = CheckpointCallback(save_freq=max(1, 10_000 // per_call), save_path="ai/models/checkpoints", name_prefix="ppo")
    model.learn(total_timesteps=a.steps, callback=ckpt, reset_num_timesteps=not a.resume)
    out = a.out or cfg["rl"]["model_path"]
    Path(out).parent.mkdir(parents=True, exist_ok=True)
    model.save(out)
    env.close()
    print(f"OK: {out}")


if __name__ == "__main__":
    main()
