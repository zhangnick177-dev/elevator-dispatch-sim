"""Round-robin dispatch (PLAN §7/§8) — the naive baseline.

WHAT IT DOES
    When new passengers appear, it hands them to elevators in strict rotation:
    car 0, car 1, car 2, ..., car N-1, car 0, car 1, ...  — regardless of where
    the cars are, which way they're going, or how full they are.

WHY IT'S THE BASELINE
    It's the simplest possible "load balancer": spread the work evenly by count.
    It ignores *position*, so under up-peak it happily assigns a fresh lobby
    passenger to a car that's currently near the top of the building — that
    passenger then waits for the car to come all the way back down. That's why
    round-robin produces long waits (our M2 test: avg wait ~100 ticks) and makes
    a good "can we do better?" reference for the smarter policies.

WHY IT'S STATEFUL
    The rotation must remember where it left off *between ticks* — if tick 5
    ended on car 9, tick 6 should continue at car 10. So the cycle lives on the
    instance, and we create exactly one RoundRobin per simulation run.
"""

from __future__ import annotations

import itertools

from elevator_sim.dispatch.base import DispatchPolicy


class RoundRobin(DispatchPolicy):
    def __init__(self, n_elevators: int):
        # itertools.cycle(range(N)) is an *infinite* iterator that yields
        # 0,1,2,...,N-1,0,1,2,...  forever. Each call to next() advances it one
        # step and remembers the position — this single object IS the round-robin
        # mechanism (no manual counter / modulo needed).
        self._cycle = itertools.cycle(range(n_elevators))

    def dispatch(self, pending, world) -> dict[str, int]:
        # `pending`  : the passengers that have arrived but aren't yet assigned
        #              to any car (the engine hands us this list each tick).
        # `world`    : full engine state — unused here (round-robin ignores it;
        #              that's exactly why it's naive), but smarter policies read
        #              car positions/loads from it.
        # returns    : {passenger_id -> elevator_id}. The engine applies these
        #              assignments (they are irrevocable).
        #
        # For each pending passenger, take the next car id from the rotation.
        # Order matters for reproducibility: `pending` preserves arrival order,
        # so the mapping is deterministic given the same trace.
        return {p.id: next(self._cycle) for p in pending}
