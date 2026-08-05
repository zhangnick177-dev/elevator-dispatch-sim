"""LOOK motion policy (PLAN §7/§8).

WHAT "MOTION" MEANS
    Motion answers: for ONE car, given the floors it must visit, which floor does
    it head toward next? It does NOT decide *which* car serves a request (that's
    dispatch). The engine calls `next_target()` once per car per tick, then steps
    that car one floor toward the returned target.

WHAT LOOK DOES  (a.k.a. "the elevator algorithm")
    Sweep in one direction, stopping at every target on the way; when there's
    nothing left ahead, reverse and sweep back; when there are no targets at all,
    go idle. Picture a real elevator: it keeps going up serving floors 3, 7, 12,
    then turns around and comes back down serving 10, 5 — it does NOT bounce back
    and forth to the nearest button press (that's FCFS "thrashing", the baseline
    we compare against).

WHY LOOK IS GOOD ENOUGH
    * Starvation-free: a sweep is guaranteed to reach every floor eventually, so
      no target is ignored forever.
    * Efficient: batches nearby stops into one pass instead of criss-crossing.
    * Near the practical ceiling for a single car's *online* motion — the leverage
      is on dispatch (which car), not motion, so we fix motion at LOOK.

TARGETS
    `elevator.targets` is a set[int] of floors this car must visit — the engine
    rebuilds it fresh each tick as {sources of assigned-waiting passengers} ∪
    {destinations of onboard passengers}. We find the next stop with a simple
    min/max filter (no heap needed at this scale, PLAN §8).

THE `target == current_floor` EDGE CASE
    The engine services the current floor (board/alight) BEFORE asking motion for
    a target. So after servicing, the only way `current_floor` is still in
    `targets` is a FULL car that couldn't board a waiting pickup there. In that
    case LOOK must NOT "stop" at the current floor (it can't help them now); it
    looks strictly above/below and continues its sweep, and the pickup is served
    on a later pass once the car has room. We implement this by only ever
    considering floors strictly `> cur` or strictly `< cur`.
"""

from __future__ import annotations

from elevator_sim.models import Direction
from elevator_sim.motion.base import MotionPolicy


class LookMotion(MotionPolicy):
    def next_target(self, elevator, world) -> int | None:
        cur = elevator.current_floor
        targets = elevator.targets

        # No work -> park the car. IDLE means "no committed direction"; the next
        # time it gets a target it will choose a fresh direction below.
        if not targets:
            elevator.direction = Direction.IDLE
            return None

        # Split targets into those strictly above and strictly below us, and take
        # the CLOSEST on each side. (Strictly above/below deliberately excludes
        # `cur` — see the edge-case note in the module docstring.)
        above = [f for f in targets if f > cur]
        below = [f for f in targets if f < cur]
        nearest_up = min(above) if above else None      # closest floor above
        nearest_down = max(below) if below else None    # closest floor below

        direction = elevator.direction

        # ---- Currently sweeping UP: keep going up until nothing is left above,
        #      then reverse. This is what makes it a smooth sweep rather than a
        #      nearest-button chase. ----
        if direction == Direction.UP:
            if nearest_up is not None:
                return nearest_up                      # continue up to next stop
            if nearest_down is not None:
                elevator.direction = Direction.DOWN    # nothing above -> reverse
                return nearest_down
            elevator.direction = Direction.IDLE        # nothing either way
            return None

        # ---- Currently sweeping DOWN: mirror image of the UP case. ----
        if direction == Direction.DOWN:
            if nearest_down is not None:
                return nearest_down                    # continue down to next stop
            if nearest_up is not None:
                elevator.direction = Direction.UP      # nothing below -> reverse
                return nearest_up
            elevator.direction = Direction.IDLE
            return None

        # ---- Currently IDLE (just got its first target, or reversed to nothing
        #      last time): pick a fresh direction toward the NEAREST target
        #      overall; ties go up (arbitrary but deterministic). ----
        if nearest_up is None and nearest_down is None:
            elevator.direction = Direction.IDLE        # shouldn't happen (targets
            return None                                # non-empty), but safe.
        if nearest_down is None:                       # only targets above
            elevator.direction = Direction.UP
            return nearest_up
        if nearest_up is None:                         # only targets below
            elevator.direction = Direction.DOWN
            return nearest_down
        # targets on both sides: go toward whichever is closer (tie -> up).
        if (nearest_up - cur) <= (cur - nearest_down):
            elevator.direction = Direction.UP
            return nearest_up
        elevator.direction = Direction.DOWN
        return nearest_down
