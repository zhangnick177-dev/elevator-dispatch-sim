"""Correctness tests (PLAN §10-A) — tiny deterministic cases with known outcomes.

Run every case against ALL dispatch policies (+ both motions) so each policy is
verified on the deterministic scenarios. Plain asserts — runnable with pytest
(`python -m pytest tests/`) OR directly (`python tests/test_correctness.py`).
"""

from __future__ import annotations

import sys
import warnings
from pathlib import Path

# allow running directly from the repo root
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from elevator_sim.config import CostWeights, SystemConfig
from elevator_sim.dispatch.cost_function import CostFunction
from elevator_sim.dispatch.hungarian import HungarianDispatch
from elevator_sim.dispatch.nearest_car import NearestCar
from elevator_sim.dispatch.round_robin import RoundRobin
from elevator_sim.dispatch.zone_based import ZoneBased
from elevator_sim.engine import World, run_sim
from elevator_sim.io.trace_loader import load_trace
from elevator_sim.models import Direction, Elevator, ElevatorState, Passenger, PassengerState, Request
from elevator_sim.motion.fcfs import FcfsMotion
from elevator_sim.motion.look import LookMotion


def _dispatch_factories(cfg: SystemConfig):
    """Fresh builders (round-robin is stateful -> new instance per run)."""
    w = CostWeights()
    return {
        "round_robin": lambda: RoundRobin(cfg.n_elevators),
        "nearest_car": lambda: NearestCar(cfg.n_floors),
        "zone_based": lambda: ZoneBased(cfg.n_elevators, cfg.n_floors, 3),
        "cost_function": lambda: CostFunction(w),
        "hungarian": lambda: HungarianDispatch(w),
    }


def _assert_delivered_and_consistent(res, cfg):
    """Every passenger delivered, timing monotone/consistent, capacity respected."""
    for p in res.passengers:
        assert p.state == PassengerState.DELIVERED, f"{p.id} not delivered"
        assert p.submit_tick <= p.pickup_tick <= p.dropoff_tick, f"{p.id} time order"
        assert p.wait_time == p.pickup_tick - p.submit_tick
        assert p.travel_time == p.dropoff_tick - p.pickup_tick
        assert p.total_time == p.wait_time + p.travel_time
        assert 1 <= p.source <= cfg.n_floors and 1 <= p.dest <= cfg.n_floors


# --------------------------------------------------------------------------
# Case 0 — every policy delivers a small mixed trace consistently
# --------------------------------------------------------------------------
def test_all_policies_deliver_consistently():
    cfg = SystemConfig(n_elevators=3, n_floors=12, capacity=3, dwell=1)
    trace = [
        Request("p1", 0, 1, 9), Request("p2", 0, 1, 4), Request("p3", 1, 10, 2),
        Request("p4", 2, 5, 12), Request("p5", 3, 8, 1), Request("p6", 3, 2, 11),
    ]
    for motion_cls in (LookMotion, FcfsMotion):
        for name, make in _dispatch_factories(cfg).items():
            with warnings.catch_warnings():
                warnings.simplefilter("error")  # a safety warning = failure here
                res = run_sim(trace, cfg, motion_cls(), make())
            _assert_delivered_and_consistent(res, cfg)


# --------------------------------------------------------------------------
# Case 1 — two same-direction passengers pool in one elevator (sweep order)
# --------------------------------------------------------------------------
def test_same_direction_pooling():
    cfg = SystemConfig(n_elevators=1, n_floors=12, capacity=10, dwell=0)
    trace = [Request("a", 0, 1, 5), Request("b", 0, 1, 9)]  # both up from lobby
    res = run_sim(trace, cfg, LookMotion(), RoundRobin(1))
    _assert_delivered_and_consistent(res, cfg)
    a = next(p for p in res.passengers if p.id == "a")
    b = next(p for p in res.passengers if p.id == "b")
    assert a.assigned_elevator == b.assigned_elevator == 0      # same car (pooled)
    assert a.pickup_tick == b.pickup_tick == 0                  # both board at lobby
    assert a.dropoff_tick < b.dropoff_tick                      # LOOK serves 5 before 9


# --------------------------------------------------------------------------
# Case 2 — opposite directions handled without deadlock
# --------------------------------------------------------------------------
def test_opposite_directions_no_deadlock():
    cfg = SystemConfig(n_elevators=1, n_floors=12, capacity=10, dwell=0)
    trace = [Request("up", 0, 1, 9), Request("down", 0, 9, 1)]
    res = run_sim(trace, cfg, LookMotion(), RoundRobin(1))
    _assert_delivered_and_consistent(res, cfg)  # both delivered, no hang


# --------------------------------------------------------------------------
# Case 3 — capacity overflow: excess passenger waits, served next pass, no loss
# --------------------------------------------------------------------------
def test_capacity_overflow():
    cfg = SystemConfig(n_elevators=1, n_floors=12, capacity=1, dwell=0)  # only 1 seat
    trace = [Request("first", 0, 1, 5), Request("second", 0, 1, 9)]
    res = run_sim(trace, cfg, LookMotion(), RoundRobin(1))
    _assert_delivered_and_consistent(res, cfg)          # both delivered (no loss)
    waits = {p.id: p.wait_time for p in res.passengers}
    # exactly one boards immediately (wait 0); the other waits for the return pass
    assert min(waits.values()) == 0
    assert max(waits.values()) > 0


# --------------------------------------------------------------------------
# Case 4 — loader edge cases: source==dest and out-of-range are skipped
# --------------------------------------------------------------------------
def test_loader_skips_bad_rows(tmp_path=None):
    d = Path(tmp_path) if tmp_path else Path("outputs/_test_tmp")
    d.mkdir(parents=True, exist_ok=True)
    f = d / "bad.csv"
    f.write_text(
        "time,id,source,dest\n"
        "0,ok1,1,5\n"
        "0,bad_same,3,3\n"        # source == dest -> skip
        "1,bad_range,1,99\n"      # dest out of [1,10] -> skip
        "2,ok2,7,2\n"
    )
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        reqs = load_trace(f, n_floors=10)
    ids = {r.id for r in reqs}
    assert ids == {"ok1", "ok2"}, f"expected only valid rows, got {ids}"


# --------------------------------------------------------------------------
# Policy-specific behaviour
# --------------------------------------------------------------------------
def _world(elevators):
    return World(elevators=elevators, n_floors=25)


def test_round_robin_rotates():
    cfg = SystemConfig(n_elevators=3)
    elevs = [Elevator(id=i, current_floor=1, capacity=10) for i in range(3)]
    pending = [Passenger(Request(f"p{i}", 0, 1, 5)) for i in range(3)]
    rr = RoundRobin(3)
    got = rr.dispatch(pending, _world(elevs))
    assert [got[p.id] for p in pending] == [0, 1, 2]        # strict rotation


def test_nearest_car_picks_closest():
    # two idle cars: one at the lobby, one at floor 20; a pickup at floor 3
    elevs = [
        Elevator(id=0, current_floor=1, capacity=10, direction=Direction.IDLE, state=ElevatorState.IDLE),
        Elevator(id=1, current_floor=20, capacity=10, direction=Direction.IDLE, state=ElevatorState.IDLE),
    ]
    p = Passenger(Request("p", 0, 3, 8))                    # source floor 3, going up
    nc = NearestCar(n_floors=25)
    got = nc.dispatch([p], _world(elevs))
    assert got["p"] == 0                                    # car 0 (floor 1) is closer to 3


# --------------------------------------------------------------------------
# runner (so it works without pytest too)
# --------------------------------------------------------------------------
if __name__ == "__main__":
    tests = [v for k, v in sorted(globals().items()) if k.startswith("test_") and callable(v)]
    passed = 0
    for t in tests:
        try:
            t()
            print(f"PASS  {t.__name__}")
            passed += 1
        except AssertionError as e:
            print(f"FAIL  {t.__name__}: {e}")
        except Exception as e:  # noqa: BLE001
            print(f"ERROR {t.__name__}: {type(e).__name__}: {e}")
    print(f"\n{passed}/{len(tests)} passed")
    sys.exit(0 if passed == len(tests) else 1)
