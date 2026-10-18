"""r_t = (W_{t-1} - W_t)/100 - 0.05*Q_t - 0.5*N>90s_t - 0.5*S_t   (PLAN.md §7)."""

LONG_WAIT_S = 90
SATURATED_OCC = 85  # %, matches spillback.occupancy_threshold


def traffic_reward(ts) -> float:
    wait = sum(ts.get_accumulated_waiting_time_per_lane()) / 100.0
    prev = getattr(ts, "_prev_wait", wait)
    ts._prev_wait = wait
    queue = ts.get_total_queued()
    long_wait = sum(
        1
        for lane in ts.lanes
        for v in ts.sumo.lane.getLastStepVehicleIDs(lane)
        if ts.sumo.vehicle.getAccumulatedWaitingTime(v) > LONG_WAIT_S
    )
    saturated = sum(1 for l in ts.out_lanes if ts.sumo.lane.getLastStepOccupancy(l) > SATURATED_OCC)
    return (prev - wait) - 0.05 * queue - 0.5 * long_wait - 0.5 * saturated
