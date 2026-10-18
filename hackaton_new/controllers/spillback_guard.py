from controllers.base import green_links


class SpillbackGuard:
    """Wraps any controller: refuses to switch to a phase that feeds an out-lane occupied above the threshold,
    unless the current phase feeds a saturated lane too. Visible A<->B coordination ("REȚINE FLUXUL")."""

    def __init__(self, cfg: dict):
        self.threshold = cfg["spillback"]["occupancy_threshold"] * 100  # SUMO occupancy is in %
        self.enabled = cfg["spillback"]["enabled"]
        self.links: dict[str, list[list[tuple[str, str]]]] = {}
        self.holds: dict[str, bool] = {}

    def reset(self, env) -> None:
        self.links = {ts: green_links(env, ts) for ts in env.ts_ids}
        self.holds = {ts: False for ts in env.ts_ids}

    def filter(self, actions: dict[str, int], env) -> dict[str, int]:
        if not self.links:
            self.reset(env)
        self.holds = {ts: False for ts in env.ts_ids}
        if not self.enabled:
            return actions
        occ: dict[str, float] = {}

        def saturated(phase_pairs) -> bool:
            for _, out_lane in phase_pairs:
                if out_lane not in occ:
                    occ[out_lane] = env.sumo.lane.getLastStepOccupancy(out_lane)
                if occ[out_lane] > self.threshold:
                    return True
            return False

        out = dict(actions)
        for ts_id, phase in actions.items():
            ts = env.traffic_signals[ts_id]
            current = ts.green_phase
            if phase == current or ts.is_yellow:
                continue
            phases = self.links[ts_id]
            if saturated(phases[phase]) and not saturated(phases[current]):
                out[ts_id] = current
                self.holds[ts_id] = True
        return out
