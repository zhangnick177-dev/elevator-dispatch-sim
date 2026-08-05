"""FCFS motion policy (PLAN §7) — the naive baseline that shows LOOK's value.

Where LOOK sweeps smoothly, FCFS serves a car's stops in strict ARRIVAL ORDER of
the passengers, regardless of where they are. So the car chases the OLDEST
passenger's immediate need (their source if not yet aboard, their dest if aboard),
then the next-oldest's, etc. — which makes it bounce across the building
("thrashing"): e.g. go up to floor 24 for the oldest, then all the way down to
floor 3 for the next-oldest, then back up. This is exactly the inefficiency LOOK
avoids, so FCFS-motion is our reference for "does smart motion matter?".

Implementation: unlike LOOK (which reads the unordered `targets` set), FCFS needs
ARRIVAL ORDER, so it looks at the car's committed passengers and their
`submit_tick`. The car's "next target" is the immediate need-floor of the oldest
such passenger (skipping the current floor, which a full car may be stuck on).
"""

from __future__ import annotations

from elevator_sim.models import Direction
from elevator_sim.motion.base import MotionPolicy


class FcfsMotion(MotionPolicy):
    def next_target(self, elevator, world) -> int | None:
        cur = elevator.current_floor

        # Collect this car's commitments as (submit_tick, need_floor):
        #   * onboard passenger -> their destination (always actionable: drop off).
        #   * assigned-but-waiting passenger -> their source (a PICKUP) — actionable
        #     ONLY if the car isn't full (a full car can't board).
        #
        # The is_full() guard is essential: without it a full car chases its
        # oldest waiting *pickups* (which it can't board) and thrashes between them
        # forever, never delivering its onboard riders to free room -> deadlock.
        # A full car therefore targets only its drop-offs; once it frees a seat it
        # will consider pickups again.
        commitments: list[tuple[int, int]] = []
        for p in elevator.onboard:
            commitments.append((p.submit_tick, p.dest))
        if not elevator.is_full():
            for p in world.waiting:
                if p.assigned_elevator == elevator.id:
                    commitments.append((p.submit_tick, p.source))

        if not commitments:
            elevator.direction = Direction.IDLE
            return None

        # Serve in arrival order: oldest submit_tick first. Skip commitments whose
        # need-floor is the current floor (a full car may be unable to board a
        # waiting pickup here) so we don't get stuck standing still.
        commitments.sort(key=lambda c: c[0])
        target = next((floor for _, floor in commitments if floor != cur), None)
        if target is None:
            elevator.direction = Direction.IDLE
            return None

        # Point the car at the target (used only for state/reporting; the engine
        # steps one floor toward it).
        elevator.direction = Direction.UP if target > cur else Direction.DOWN
        return target
