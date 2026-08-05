"""Core data models — the *nouns* of the simulation.

Design (PLAN §3):
  * `Request`   — the raw input row, immutable (one per CSV line).
  * `Passenger` — wraps a Request and adds the mutable lifecycle stamps.
  * `Elevator`  — a car's runtime state.
  * enums       — `Direction`, `ElevatorState`, `PassengerState`.

These are pure data (plus tiny helpers). All simulation *behaviour* lives in
the engine and the policies; these types never advance time themselves.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum


class Direction(Enum):
    UP = 1
    DOWN = -1
    IDLE = 0


class ElevatorState(Enum):
    IDLE = "idle"
    MOVING = "moving"
    DWELLING = "dwelling"  # doors open, serving a floor


class PassengerState(Enum):
    WAITING = "waiting"      # request submitted, not yet boarded
    ONBOARD = "onboard"      # picked up, in transit
    DELIVERED = "delivered"  # dropped off at destination


@dataclass(frozen=True)
class Request:
    """The raw input row — immutable. Maps 1:1 to a CSV line `time,id,source,dest`.

    `submit_tick` is the CSV `time` column (renamed for clarity: the tick the
    button was pressed).
    """

    id: str
    submit_tick: int
    source: int
    dest: int

    @property
    def direction(self) -> Direction:
        """Which way this request travels (derived, not stored)."""
        return Direction.UP if self.dest > self.source else Direction.DOWN

    @property
    def distance(self) -> int:
        """Trip length in floors (derived)."""
        return abs(self.dest - self.source)


@dataclass
class Passenger:
    """A request's lifecycle. Wraps an immutable `Request` (single source of
    truth for id/source/dest) and adds the mutable stamps set during the run.

    Per the model each passenger takes exactly one elevator once, so
    `assigned_elevator` is a single value and the lifecycle is linear:
    WAITING -> ONBOARD -> DELIVERED.
    """

    request: Request
    assigned_elevator: int | None = None
    pickup_tick: int | None = None
    dropoff_tick: int | None = None

    # --- convenience delegation to the wrapped request ---
    @property
    def id(self) -> str:
        return self.request.id

    @property
    def source(self) -> int:
        return self.request.source

    @property
    def dest(self) -> int:
        return self.request.dest

    @property
    def submit_tick(self) -> int:
        return self.request.submit_tick

    @property
    def direction(self) -> Direction:
        return self.request.direction

    # --- derived timing metrics (None until the stamp exists) ---
    @property
    def wait_time(self) -> int | None:
        if self.pickup_tick is None:
            return None
        return self.pickup_tick - self.submit_tick

    @property
    def travel_time(self) -> int | None:
        if self.pickup_tick is None or self.dropoff_tick is None:
            return None
        return self.dropoff_tick - self.pickup_tick

    @property
    def total_time(self) -> int | None:
        if self.dropoff_tick is None:
            return None
        return self.dropoff_tick - self.submit_tick

    @property
    def state(self) -> PassengerState:
        if self.dropoff_tick is not None:
            return PassengerState.DELIVERED
        if self.pickup_tick is not None:
            return PassengerState.ONBOARD
        return PassengerState.WAITING


@dataclass
class Elevator:
    """A car's runtime state. `targets` is a set of floor ints (LOOK picks the
    next stop via a min/max filter — no heap needed at this scale, PLAN §8).
    """

    id: int
    current_floor: int
    capacity: int
    direction: Direction = Direction.IDLE
    state: ElevatorState = ElevatorState.IDLE
    onboard: list[Passenger] = field(default_factory=list)
    targets: set[int] = field(default_factory=set)
    dwell_remaining: int = 0

    def is_full(self) -> bool:
        return len(self.onboard) >= self.capacity

    @property
    def free_slots(self) -> int:
        return self.capacity - len(self.onboard)
