"""Reproduce the demo/smoke runs (PLAN §10-B).

Runs the 6 schedulers x 3 traffic patterns = 18 single runs on the office-building
defaults (16 cars, 25 floors, cap 10, dwell 2, lambda=3, seed 42). One trace is
generated per pattern (seed 42) and all 6 schedulers run on it (mini-CRN, so the
within-pattern comparison is apples-to-apples). Each run writes its outputs to
    outputs/demo/{pattern}__{motion}_{dispatch}/
and a summary comparison table is written to outputs/demo/comparison.csv.

Usage:  python run_demo.py
"""

from __future__ import annotations

import csv
import warnings
from pathlib import Path

from elevator_sim.config import CostWeights, SystemConfig
from elevator_sim.dispatch.aging import Aged
from elevator_sim.dispatch.cost_function import CostFunction
from elevator_sim.dispatch.hungarian import HungarianDispatch
from elevator_sim.dispatch.nearest_car import NearestCar
from elevator_sim.dispatch.round_robin import RoundRobin
from elevator_sim.dispatch.zone_based import ZoneBased
from elevator_sim.engine import run_sim
from elevator_sim.io.generator import generate
from elevator_sim.io.writers import CsvWriter, format_console_table
from elevator_sim.metrics import compute
from elevator_sim.motion.fcfs import FcfsMotion
from elevator_sim.motion.look import LookMotion
from elevator_sim.plots import plot_distributions

CFG = SystemConfig()          # office-building defaults
WEIGHTS = CostWeights()
AGE_WEIGHT = 0.1
LAM, DURATION, SEED = 3, 900, 42
PATTERNS = ("up_peak", "down_peak", "uniform")

# 6 scheduler configs: 5 dispatch policies on LOOK + the FCFS-motion baseline.
SCHEDULERS = [
    ("look", "round_robin"),
    ("look", "nearest_car"),
    ("look", "zone_based"),
    ("look", "cost_function"),
    ("look", "hungarian"),
    ("fcfs", "round_robin"),   # motion baseline (shows the FCFS->LOOK gap)
]


def _make_dispatch(name):
    if name == "round_robin":
        return RoundRobin(CFG.n_elevators)
    if name == "nearest_car":
        return NearestCar(CFG.n_floors)
    if name == "zone_based":
        return ZoneBased(CFG.n_elevators, CFG.n_floors, 3)
    if name == "cost_function":
        return CostFunction(WEIGHTS)
    if name == "hungarian":
        return HungarianDispatch(WEIGHTS)
    raise ValueError(name)


def main() -> None:
    rows = []
    for pattern in PATTERNS:
        # one trace per pattern; all schedulers run on it (mini-CRN)
        trace = generate(pattern, LAM, CFG.n_floors, DURATION, seed=SEED)
        for motion_name, dispatch_name in SCHEDULERS:
            motion = LookMotion() if motion_name == "look" else FcfsMotion()
            dispatch = Aged(_make_dispatch(dispatch_name), AGE_WEIGHT)  # aging on (no-op here)

            with warnings.catch_warnings():
                warnings.simplefilter("ignore")
                res = run_sim(trace, CFG, motion, dispatch)

            sched = f"{motion_name}+{dispatch_name}"
            m = compute(res, run_meta={"scheduler": sched,
                                       "workload": {"pattern": pattern, "lambda": LAM, "seed": SEED}})
            outdir = Path("outputs/demo") / f"{pattern}__{motion_name}_{dispatch_name}"
            CsvWriter().write(res, m, outdir)
            plot_distributions(m.per_passenger, outdir / "distributions.png",
                               title=f"{sched}, {pattern} lambda={LAM}")

            s = m.summary
            rows.append({
                "pattern": pattern, "scheduler": sched,
                "delivered": s["run"]["n_delivered"], "n_ticks": s["run"]["n_ticks"],
                "wait_avg": s["wait"]["avg"], "wait_p95": s["wait"]["p95"], "wait_max": s["wait"]["max"],
                "travel_avg": s["travel"]["avg"],
                "total_avg": s["total"]["avg"], "total_max": s["total"]["max"],
                "rho": s["efficiency"]["utilization_rho"], "throughput": s["efficiency"]["throughput"],
                "passengers_per_stop": s["pooling"]["passengers_per_stop"],
                "distance_per_passenger": s["pooling"]["distance_per_passenger"],
            })
            print(f"  {pattern:10} {sched:20} avgW={s['wait']['avg']:>6}  rho={s['efficiency']['utilization_rho']}")

    # write the illustrative comparison table (single-seed; the rigorous grid is Phase 2)
    comp = Path("outputs/demo/comparison.csv")
    with comp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    print(f"\n18 runs written to outputs/demo/  (+ comparison.csv)")


if __name__ == "__main__":
    main()
