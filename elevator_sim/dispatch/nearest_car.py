"""Nearest-Car dispatch (PLAN §7/§8) — the classic ~1970s heuristic (NCH).

Assign each request to the car with the highest "Figure of Suitability" (FS) —
a simple score that rewards cars that are close AND already heading the right way.
With N = number of floors and d = |car_floor - pickup_floor|:

    * car moving TOWARD the pickup, SAME direction as the rider wants:  FS = (N+2) - d
    * car moving TOWARD the pickup, OPPOSITE direction:                 FS = (N+1) - d
    * car moving AWAY from the pickup:                                  FS = 1
    * idle car (free to go straight there):                            FS = (N+2) - d

Highest FS wins (ties -> lowest car id). Intuition: subtracting d makes closer
cars score higher; the +2 / +1 / 1 tiers rank "will pass it going the right way"
above "will pass it going the wrong way" above "heading away". Unlike the
cost-function it has NO tunable weights — the formula is fixed.

It considers position + direction (so it's far better than round-robin) but is
myopic: it ignores car load and the car's committed route (a close car with a
long queue still looks good). That's what the cost-function's `load`/`eta` terms
add on top.
"""

from __future__ import annotations

from elevator_sim.dispatch.base import DispatchPolicy
from elevator_sim.dispatch.cost_function import committed_loads
from elevator_sim.models import Direction


def _figure_of_suitability(car, source: int, req_dir: Direction, n_floors: int) -> int:
    cur = car.current_floor
    d = abs(cur - source)

    # Idle car: free to drive straight to the pickup -> top tier.
    if car.direction == Direction.IDLE:
        return (n_floors + 2) - d

    # Is the car currently heading TOWARD the pickup floor?
    toward = (
        (car.direction == Direction.UP and cur <= source)
        or (car.direction == Direction.DOWN and cur >= source)
    )
    if not toward:
        return 1                                   # heading away -> worst tier

    if car.direction == req_dir:
        return (n_floors + 2) - d                  # toward + same way -> best
    return (n_floors + 1) - d                       # toward + wrong way -> middle


class NearestCar(DispatchPolicy):
    def __init__(self, n_floors: int):
        self.n_floors = n_floors

    def dispatch(self, pending, world) -> dict[str, int]:
        cars = world.elevators
        committed = committed_loads(world)   # true backlog per car
        assignments: dict[str, int] = {}
        for p in pending:
            # Pick MAX FS; among equal-FS cars prefer the LEAST committed, then
            # lowest id. The committed tie-break matters in up-peak, where all
            # cars sit at the lobby with identical FS — without it every rider
            # dogpiles the lowest-id car. (max() over descending keys: highest
            # FS, then -committed = least committed, then -id = lowest id.)
            best = max(
                cars,
                key=lambda e: (
                    _figure_of_suitability(e, p.source, p.direction, self.n_floors),
                    -committed[e.id],
                    -e.id,
                ),
            )
            assignments[p.id] = best.id
            committed[best.id] += 1          # spread a same-tick burst
        return assignments
