from typing import Protocol

import numpy as np


class Controller(Protocol):
    """All controllers drive a sumo_rl.SumoEnvironment (dict-style) the same way."""

    name: str

    def reset(self, env) -> None: ...

    def act(self, observations: dict[str, np.ndarray], env) -> dict[str, int]:
        """Takes the per-light observations, returns the desired green phase per light."""
        ...


def green_links(env, ts_id: str) -> list[list[tuple[str, str]]]:
    """For each green phase of a light: the distinct (in_lane, out_lane) pairs it opens."""
    ts = env.traffic_signals[ts_id]
    links = env.sumo.trafficlight.getControlledLinks(ts_id)
    out = []
    for i in range(ts.num_green_phases):
        state = ts.all_phases[i].state
        pairs = {(l[0][0], l[0][1]) for idx, l in enumerate(links) if l and state[idx] in "Gg"}
        out.append(sorted(pairs))
    return out
