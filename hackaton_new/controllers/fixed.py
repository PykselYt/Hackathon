import sumolib


class FixedController:
    """Cycles the green phases with the durations of the network's static program (sumo/src/*.tll.xml)."""

    name = "fixed"

    def __init__(self, cfg: dict):
        net = sumolib.net.readNet(cfg["sumo"]["net"], withPrograms=True)
        self.durations: dict[str, list[float]] = {}
        for tls in net.getTrafficLights():
            program = next(iter(tls.getPrograms().values()))
            greens = [p.duration for p in program.getPhases() if "y" not in p.state and set(p.state) - set("rs")]
            self.durations[tls.getID()] = greens

    def reset(self, env) -> None:
        pass

    def act(self, observations, env) -> dict[str, int]:
        actions = {}
        for ts_id, ts in env.traffic_signals.items():
            phase = ts.green_phase
            green_s = ts.time_since_last_phase_change - ts.yellow_time
            if not ts.is_yellow and green_s + env.delta_time > self.durations[ts_id][phase]:
                phase = (phase + 1) % ts.num_green_phases
            actions[ts_id] = phase
        return actions
