import numpy as np
from stable_baselines3 import PPO


class PPOController:
    """Shared PPO policy; observations zero-padded exactly as supersuit did during training."""

    name = "ppo"

    def __init__(self, cfg: dict, model_path: str | None = None):
        self.model = PPO.load(model_path or cfg["rl"]["model_path"], device="cpu")
        self.obs_size = self.model.observation_space.shape[0]
        self.n_actions = self.model.action_space.n

    def reset(self, env) -> None:
        pass

    def act(self, observations: dict[str, np.ndarray], env) -> dict[str, int]:
        ids = list(observations)
        batch = np.stack([np.pad(observations[t], (0, self.obs_size - observations[t].shape[0])) for t in ids])
        actions, _ = self.model.predict(batch, deterministic=True)
        out = {}
        for t, a in zip(ids, actions):
            n = env.traffic_signals[t].num_green_phases
            # supersuit.pad_action_space: actions beyond this light's phases are mapped back into range
            out[t] = int(a) if int(a) < n else env.traffic_signals[t].green_phase
        return out
