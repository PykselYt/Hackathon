from controllers.base import green_links


class MaxPressureController:
    """Picks the green phase with the largest sum of (vehicles on in-lane - vehicles on out-lane) over the links it opens."""

    name = "max_pressure"

    def __init__(self, cfg: dict | None = None):
        self.links: dict[str, list[list[tuple[str, str]]]] = {}

    def reset(self, env) -> None:
        self.links = {ts: green_links(env, ts) for ts in env.ts_ids}

    def act(self, observations, env) -> dict[str, int]:
        if not self.links:
            self.reset(env)
        lane = env.sumo.lane
        actions = {}
        for ts_id, phases in self.links.items():
            counts: dict[str, int] = {}

            def n(l: str) -> int:
                if l not in counts:
                    counts[l] = lane.getLastStepVehicleNumber(l)
                return counts[l]

            pressures = [sum(n(i) - n(o) for i, o in pairs) for pairs in phases]
            current = env.traffic_signals[ts_id].green_phase
            best = max(range(len(pressures)), key=lambda k: (pressures[k], k == current))
            actions[ts_id] = best
        return actions
