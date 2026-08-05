"""Discrete-time simulation engine (PLAN §6).

A pure-Python "state-stepper": a `while` loop that nudges the world forward one
tick at a time. There is no numerical math, no differential-equation solver, and
no simulation framework (deliberately not SimPy) — just plain Python mutating
objects. The queueing theory (ρ, the cliff) is how we *interpret* the output; it
is never computed here.

HOW A PASSENGER FLOWS THROUGH THE SYSTEM
    Each passenger lives in exactly one of three "buckets" at a time, and moves
    strictly forward:

        unassigned  --dispatch-->  waiting  --board-->  onboard  --alight-->  done
      (arrived, no      (assigned to a car,   (inside a car,      (delivered;
       car yet)          waiting at source)    in transit)         dropoff set)

      * world.unassigned : list of Passengers with no elevator yet.
      * world.waiting    : assigned to a car, standing at their source floor.
      * elevator.onboard : physically inside that car.
      * "done"           : dropoff_tick is set; they just stay in all_passengers.

    all_passengers holds every passenger for the whole run (for metrics later).

THE TICK LOOP (per tick t)
    1. Log positions (Convention A: floor at the START of t, before the move,
       so row 0 is the initial state and row t = "where cars are at time t").
    2. Admit: turn requests with submit_tick == t into Passengers (-> unassigned).
    3. Dispatch: ask the policy which car each unassigned passenger gets
       (-> waiting). Assignment is irrevocable.
    4. Service the current floor of every car: alight arrivals, then board
       waiting passengers up to capacity. This happens BEFORE moving so a car
       already sitting on a passenger's floor picks them up instead of driving
       away first.
    5. Move: each car steps one floor toward its next target (chosen by the
       motion policy), unless it's dwelling (doors open).
    6. Advance t and check termination (drained), with two safety nets.

PEEK-AHEAD
    "Don't peek ahead" constrains the *scheduler's decisions*, not the engine's
    bookkeeping. The engine knows the whole trace (so it can compute last_arrival
    to know when to stop), but the scheduler in step 3 only ever sees passengers
    that have already been admitted (submit_tick <= t).
"""

from __future__ import annotations

import warnings
from collections import defaultdict
from dataclasses import dataclass, field

from elevator_sim.config import SystemConfig
from elevator_sim.models import Elevator, ElevatorState, Passenger, Request


@dataclass
class World:
    """The engine's mutable state for one run. Policies receive this each tick and
    read from it (they should treat it as read-only); the engine owns all writes."""

    elevators: list[Elevator]
    n_floors: int
    t: int = 0
    unassigned: list[Passenger] = field(default_factory=list)   # arrived, no car yet
    waiting: list[Passenger] = field(default_factory=list)       # assigned, not boarded
    all_passengers: list[Passenger] = field(default_factory=list)


@dataclass
class RunResult:
    """Everything a run produces: the passengers (for metrics) and the per-tick
    positions log, plus run metadata and a few efficiency counters that can't be
    reconstructed from positions alone (dwell time, stops)."""

    passengers: list[Passenger]
    positions_log: list[list[int]]   # each row: [tick, floor_e0, floor_e1, ...]
    n_ticks: int
    n_elevators: int
    config: SystemConfig
    total_distance: int = 0   # sum of |floor moves| across all cars (total work)
    stops_made: int = 0       # total door-open service events across all cars
    busy_ticks: int = 0       # car-ticks spent moving or dwelling (for ρ)


def run_sim(requests: list[Request], config: SystemConfig, motion, dispatch) -> RunResult:
    """Run one simulation to completion.

    Args:
        requests: the input trace (order doesn't matter; we bucket by tick below).
        config:   building/engine parameters (SystemConfig).
        motion:   a MotionPolicy (e.g. LOOK) — chooses each car's next stop.
        dispatch: a DispatchPolicy (e.g. RoundRobin) — chooses which car serves
                  a new request.
    """
    # --- Set up the cars: all start at the lobby (init_floor), IDLE. ---
    elevators = [
        Elevator(id=i, current_floor=config.init_floor, capacity=config.capacity)
        for i in range(config.n_elevators)
    ]
    world = World(elevators=elevators, n_floors=config.n_floors)

    # --- Bucket requests by their arrival tick so admitting each tick is O(1). ---
    # (The engine is allowed to know the whole trace; this is loop bookkeeping,
    #  not a scheduling decision — see the peek-ahead note in the module docstring.)
    by_tick: dict[int, list[Request]] = defaultdict(list)
    for r in requests:
        by_tick[r.submit_tick].append(r)
    last_arrival = max((r.submit_tick for r in requests), default=0)

    # --- Two termination safety nets (PLAN §6) ---
    # (1) Stall detector (primary): a legitimate drain can be arbitrarily long
    #     under heavy load, but a healthy sim keeps *delivering* people. Only a
    #     genuine hang (someone who can never be served) stops producing
    #     deliveries. So: if no one is delivered for `stall_limit` ticks while
    #     work remains, something is wrong -> break with a warning. stall_limit
    #     comfortably exceeds the largest gap-between-deliveries in a healthy sim
    #     (~one full round trip = ~2*n_floors, plus slack).
    stall_limit = 4 * config.n_floors + config.dwell + 20
    last_progress_t = 0  # last tick at which anyone was delivered
    # (2) Absolute hard backstop: a very generous fixed cap so the loop is
    #     guaranteed to end even in a pathological case; set high enough that a
    #     real drain (even a near-saturated λ-sweep run) never reaches it.
    max_ticks = last_arrival + 200 * config.n_floors

    # Efficiency counters (accumulated during the run for metrics.py, §9).
    total_distance = 0   # floors moved (all cars)
    stops_made = 0       # door-open service events (all cars)
    busy_ticks = 0       # car-ticks moving or dwelling

    positions_log: list[list[int]] = []
    t = 0
    while True:
        world.t = t

        # --- STEP 1: log positions BEFORE any movement this tick (Convention A).
        # Row = [tick, floor of e0, floor of e1, ...]. Row 0 = initial config.
        positions_log.append([t] + [e.current_floor for e in elevators])

        # --- STEP 2: admit everyone who pressed the button at exactly tick t.
        # A Request (immutable input) becomes a Passenger (mutable lifecycle) and
        # enters the unassigned pool.
        for r in by_tick.get(t, ()):
            p = Passenger(request=r)
            world.all_passengers.append(p)
            world.unassigned.append(p)

        # --- STEP 3: dispatch. Hand the whole unassigned pool to the policy; it
        # returns {passenger_id -> elevator_id}. We apply each assignment
        # (irrevocable) and move that passenger from `unassigned` to `waiting`.
        # A policy MAY omit a passenger (e.g. Hungarian with no free slot this
        # tick); those stay unassigned and are retried next tick.
        if world.unassigned:
            assignments = dispatch.dispatch(world.unassigned, world)
            still_unassigned: list[Passenger] = []
            for p in world.unassigned:
                eid = assignments.get(p.id)
                if eid is None:
                    still_unassigned.append(p)      # policy deferred this one
                else:
                    p.assigned_elevator = eid
                    world.waiting.append(p)
            world.unassigned = still_unassigned

        # --- STEP 4: service the current floor of each car (alight, then board),
        # BEFORE moving. Returns (delivered, stops) this tick; if anyone was
        # delivered we record progress for the stall detector.
        delivered_this_tick, stops_this_tick = _service(world, config, t)
        stops_made += stops_this_tick
        if delivered_this_tick:
            last_progress_t = t

        # --- Rebuild each car's target set FRESH from its committed passengers.
        # We derive rather than incrementally add/remove (simpler, bug-resistant):
        #   targets(car) = {source of each assigned-waiting passenger of this car}
        #                ∪ {dest of each passenger currently onboard this car}
        # A full car that couldn't board a waiting pickup keeps that source as a
        # target, so LOOK will route back to it on a later pass.
        pickups: dict[int, set[int]] = defaultdict(set)
        for p in world.waiting:
            pickups[p.assigned_elevator].add(p.source)
        for e in elevators:
            e.targets = pickups.get(e.id, set()) | {p.dest for p in e.onboard}

        # --- STEP 5: move each car one floor (dwell-aware).
        for e in elevators:
            # If the doors are open (dwelling), spend a tick here instead of
            # moving; count it down. dwell=2 -> two stationary ticks per stop.
            if e.dwell_remaining > 0:
                e.dwell_remaining -= 1
                e.state = ElevatorState.DWELLING
                busy_ticks += 1                         # dwelling counts as busy
                continue
            # Otherwise ask the motion policy where to head, and step ONE floor
            # toward it (the policy may also flip the car's sweep direction).
            target = motion.next_target(e, world)
            if target is None:
                e.state = ElevatorState.IDLE            # nothing to do (not busy)
            else:
                e.current_floor += 1 if target > e.current_floor else -1
                e.state = ElevatorState.MOVING
                total_distance += 1                     # one floor of work
                busy_ticks += 1                         # moving counts as busy

        # --- STEP 6: advance the clock and decide whether to stop.
        t += 1
        world.t = t

        # "settled" = nothing left to do anywhere: no unassigned, no one waiting
        # to board, and every car empty with doors closed.
        settled = (
            not world.unassigned
            and not world.waiting
            and all(not e.onboard and e.dwell_remaining == 0 for e in elevators)
        )
        # Normal end: no more arrivals will come AND everything is settled.
        if t > last_arrival and settled:
            break
        # Safety net (1): work remains but nobody's been delivered in too long.
        if not settled and (t - last_progress_t) > stall_limit:
            warnings.warn(
                f"stall detected at t={t}: no delivery for {stall_limit}+ ticks "
                f"while work remains (possible starvation bug).",
                RuntimeWarning,
            )
            break
        # Safety net (2): absolute hard cap (should never be reached normally).
        if t > max_ticks:
            warnings.warn(
                f"MAX_TICKS ({max_ticks} = last_arrival + 50*n_floors) exceeded — "
                f"sim did not drain.",
                RuntimeWarning,
            )
            break

    return RunResult(
        passengers=world.all_passengers,
        positions_log=positions_log,
        n_ticks=t,
        n_elevators=config.n_elevators,
        config=config,
        total_distance=total_distance,
        stops_made=stops_made,
        busy_ticks=busy_ticks,
    )


def _service(world: World, config: SystemConfig, t: int) -> tuple[int, int]:
    """Service the current floor of every car: first alight passengers whose
    destination is this floor, then board waiting passengers (assigned to this
    car) standing at their source floor, up to capacity. Any car that boarded or
    alighted opens its doors (sets dwell). Returns (delivered, stops) this tick:
    `delivered` = passengers dropped off (for the stall detector), `stops` =
    number of cars that opened their doors (a door-opening = one "stop", §9).

    Ordering matters: we ALIGHT before we BOARD (people get off before others get
    on), and we service BEFORE the car moves (handled by the caller) so a car on
    a passenger's floor picks them up rather than leaving first.
    """
    # Index waiting passengers by (which car they're assigned to, their source
    # floor) so each car can find its boarders in O(1). Built once per tick.
    waiting_here: dict[tuple[int, int], list[Passenger]] = defaultdict(list)
    for p in world.waiting:
        waiting_here[(p.assigned_elevator, p.source)].append(p)

    delivered = 0
    stops = 0
    boarded_ids: set[str] = set()
    for e in world.elevators:
        serviced = False  # did anyone get on/off? -> open the doors (dwell) = a stop

        # --- ALIGHT: onboard passengers whose destination is this floor. ---
        alighting = [p for p in e.onboard if p.dest == e.current_floor]
        if alighting:
            for p in alighting:
                p.dropoff_tick = t                      # stamp delivery time
            # keep only those still travelling
            e.onboard = [p for p in e.onboard if p.dest != e.current_floor]
            delivered += len(alighting)
            serviced = True

        # --- BOARD: waiting passengers of THIS car at THIS floor, until full. ---
        # We stop at capacity; anyone left over stays in `waiting` and boards on
        # a later pass (their source remains one of this car's targets).
        for p in waiting_here.get((e.id, e.current_floor), ()):
            if e.is_full():
                break
            p.pickup_tick = t                           # stamp board time
            e.onboard.append(p)
            boarded_ids.add(p.id)
            serviced = True

        if serviced:
            stops += 1                                  # one door-opening = one stop
            # Opening the doors costs `dwell` ticks (set once; counted in move).
            if config.dwell > 0:
                e.dwell_remaining = config.dwell
                e.state = ElevatorState.DWELLING

    # Remove everyone who boarded from the global waiting list in one pass.
    if boarded_ids:
        world.waiting = [p for p in world.waiting if p.id not in boarded_ids]
    return delivered, stops
