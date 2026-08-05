"""Cost-function / ETA dispatch (PLAN §7/§8) — the "star" policy.

For each new request, score EVERY car by a weighted cost and assign to the
cheapest. The intelligence is entirely in `estimate_cost`; the policy itself is
just `min(cars, key=cost)`.

    cost(request, car) = w_dist * distance        # floors car -> pickup
                       + w_dir  * direction_penalty# 0 if car already going rider's way
                       + w_load * load             # how full the car is (balance)
                       + w_eta  * eta              # route-aware ticks-to-pickup

WHY FOUR TERMS
    * distance / direction_penalty are cheap LOCAL proxies (where is the car, is
      it pointed the right way).
    * eta is the fuller ROUTE-AWARE estimate — it accounts for the car's existing
      committed stops, so a physically-close car with a long queue scores worse.
    * load balances utilization (don't pile everyone onto one car).
    So the terms deliberately overlap (eta partly subsumes distance/direction);
    the weights let you lean on the cheap proxies or the accurate estimate.

GENERALISES NEAREST-CAR
    Zero the w_load and w_eta weights and this reduces to distance + direction —
    essentially nearest-car. Turn them up and it becomes route- and load-aware.

`estimate_cost` and `eta_to_floor` are module-level so the Hungarian policy can
reuse the exact same cost matrix (PLAN §8: Hungarian = the optimal-batch cousin
of this greedy policy).
"""

from __future__ import annotations

from elevator_sim.config import CostWeights
from elevator_sim.dispatch.base import DispatchPolicy
from elevator_sim.models import Direction


def eta_to_floor(car, floor: int) -> int:
    """Estimate how many floors the car will TRAVEL before reaching `floor`,
    following LOOK from its current state (a route-aware ETA proxy, in floors,
    ignoring dwell). Uses the car's committed `targets` to know its sweep extent.

      * idle / no targets      -> straight-line distance.
      * floor is ahead in the current sweep -> distance ahead.
      * floor is behind        -> go to the far end of the sweep, reverse, come
                                  back: (extent - cur) + (extent - floor).
    """
    cur = car.current_floor
    if car.direction == Direction.IDLE or not car.targets:
        return abs(cur - floor)

    if car.direction == Direction.UP:
        if floor >= cur:                       # ahead on the way up
            return floor - cur
        top = max(max(car.targets), cur)       # continue up, reverse, come down
        return (top - cur) + (top - floor)
    else:  # DOWN
        if floor <= cur:                       # ahead on the way down
            return cur - floor
        bottom = min(min(car.targets), cur)    # continue down, reverse, come up
        return (cur - bottom) + (floor - bottom)


def estimate_cost(passenger, car, committed_load: int, weights: CostWeights) -> float:
    """The weighted cost of serving `passenger` with `car`. Lower = better.

    `committed_load` = how many passengers this car is *committed* to but hasn't
    delivered yet (onboard PLUS assigned-and-waiting-to-board). This is crucial:
    using physical occupancy (`len(onboard)`) alone lets a car with a huge queue
    of not-yet-boarded riders still look "empty" and attract even more — the
    concentration bug. Committed load reflects the true backlog.
    """
    cur = car.current_floor
    source = passenger.source

    # 1. distance: floors from the car to the pickup (cheap proxy).
    distance = abs(cur - source)

    # 2. direction_penalty: 0 if the car is idle or already heading the way the
    #    passenger wants to go (so it can serve them "on the way"); else 1.
    aligned = car.direction == Direction.IDLE or car.direction == passenger.direction
    direction_penalty = 0.0 if aligned else 1.0

    # 3. load: the car's true backlog (prefer less-committed cars -> balance).
    # 4. eta: route-aware ticks-to-pickup (accounts for committed stops).
    eta = eta_to_floor(car, source)

    return (
        weights.w_dist * distance
        + weights.w_dir * direction_penalty
        + weights.w_load * committed_load
        + weights.w_eta * eta
    )


def committed_loads(world) -> dict[int, int]:
    """Per-car committed load = onboard + assigned-but-not-yet-boarded (world.waiting).
    Shared by the greedy policies so they balance against the true backlog."""
    loads = {e.id: len(e.onboard) for e in world.elevators}
    for p in world.waiting:
        loads[p.assigned_elevator] += 1
    return loads


class CostFunction(DispatchPolicy):
    def __init__(self, weights: CostWeights | None = None):
        self.weights = weights or CostWeights()

    def dispatch(self, pending, world) -> dict[str, int]:
        cars = world.elevators
        committed = committed_loads(world)   # true backlog per car (start of batch)
        assignments: dict[str, int] = {}
        for p in pending:
            # Greedy: each request takes its own cheapest car. Ties -> lowest id.
            best = min(cars, key=lambda e: (estimate_cost(p, e, committed[e.id], self.weights), e.id))
            assignments[p.id] = best.id
            committed[best.id] += 1          # update WITHIN the batch so a burst
            #                                  of same-tick arrivals spreads out
            #                                  instead of dogpiling one car.
        return assignments
