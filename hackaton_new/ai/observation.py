import numpy as np
from gymnasium import spaces
from sumo_rl.environment.observations import ObservationFunction


class NeighborObservation(ObservationFunction):
    """Default sumo-rl observation + occupancy of the outgoing lanes (signal that the neighbour is filling up).

    Layout: one-hot light id | one-hot green phase | min-green flag | density per in-lane | queue per in-lane |
    occupancy per out-lane. The light id comes first so it sits at the same position for every agent of the
    shared policy (padding only adds zeros at the end).
    Out-lanes are sorted: sumo-rl builds ts.out_lanes from a set, whose order changes between processes.
    """

    def __call__(self) -> np.ndarray:
        ts = self.ts
        agent = [1 if t == ts.id else 0 for t in ts.env.ts_ids]
        phase = [1 if ts.green_phase == i else 0 for i in range(ts.num_green_phases)]
        min_green = [0 if ts.time_since_last_phase_change < ts.min_green + ts.yellow_time else 1]
        density = ts.get_lanes_density()
        queue = ts.get_lanes_queue()
        out_occ = [min(1.0, ts.sumo.lane.getLastStepOccupancy(l) / 100) for l in sorted(ts.out_lanes)]
        return np.array(agent + phase + min_green + density + queue + out_occ, dtype=np.float32)

    def observation_space(self) -> spaces.Box:
        n = len(self.ts.env.ts_ids) + self.ts.num_green_phases + 1 + 2 * len(self.ts.lanes) + len(self.ts.out_lanes)
        return spaces.Box(low=0, high=1, shape=(n,), dtype=np.float32)
