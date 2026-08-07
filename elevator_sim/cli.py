"""Command-line entry point for a single simulation run (PLAN §11).

Examples
    # generate a default office trace (16 cars, 25 floors, up-peak, lambda=3) and run
    python -m elevator_sim --generate --dispatch cost_function --plot

    # run KKR's own trace file with a chosen scheduler
    python -m elevator_sim --input trace.csv --floors 60 --dispatch nearest_car

    # tweak the building / load
    python -m elevator_sim --generate --pattern uniform --lambda 2 --capacity 12 \
        --dispatch hungarian --output outputs/myrun --plot

Pipeline: build config -> get trace (load or generate) -> run engine -> compute
metrics -> print console table -> write files -> (optional) plot.
"""

from __future__ import annotations

import argparse
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
from elevator_sim.io.trace_loader import load_trace
from elevator_sim.io.writers import CsvWriter, format_console_table
from elevator_sim.metrics import compute
from elevator_sim.motion.fcfs import FcfsMotion
from elevator_sim.motion.look import LookMotion
from elevator_sim.plots import plot_distributions

MOTIONS = {"look": LookMotion, "fcfs": FcfsMotion}
DISPATCHERS = ("round_robin", "nearest_car", "zone_based", "cost_function", "hungarian")


def _build_motion(name: str):
    return MOTIONS[name]()


def _build_dispatch(name: str, cfg: SystemConfig, weights: CostWeights, n_zones: int, age_weight: float):
    if name == "round_robin":
        policy = RoundRobin(cfg.n_elevators)
    elif name == "nearest_car":
        policy = NearestCar(cfg.n_floors)
    elif name == "zone_based":
        policy = ZoneBased(cfg.n_elevators, cfg.n_floors, n_zones)
    elif name == "cost_function":
        policy = CostFunction(weights)
    elif name == "hungarian":
        policy = HungarianDispatch(weights)
    else:
        raise ValueError(f"unknown dispatch {name!r}")
    # Aging composes on top of any policy (no-op when age_weight == 0).
    return Aged(policy, age_weight) if age_weight > 0 else policy


def _parse_args(argv=None) -> argparse.Namespace:
    p = argparse.ArgumentParser(prog="elevator_sim", description="Single elevator-sim run.")
    # input: load a trace, or generate one
    src = p.add_argument_group("input (choose one)")
    src.add_argument("--input", type=str, help="CSV trace to load (time,id,source,dest)")
    src.add_argument("--generate", action="store_true", help="generate a synthetic trace")
    # workload (for --generate)
    p.add_argument("--pattern", default="up_peak", choices=["up_peak", "down_peak", "uniform"])
    p.add_argument("--lambda", dest="lam", type=float, default=3.0, help="arrivals per tick")
    p.add_argument("--duration", type=int, default=900, help="arrival window in ticks")
    p.add_argument("--seed", type=int, default=42)
    # system / building
    p.add_argument("--elevators", type=int, default=16)
    p.add_argument("--floors", type=int, default=25)
    p.add_argument("--capacity", type=int, default=10)
    p.add_argument("--dwell", type=int, default=2)
    # scheduler
    p.add_argument("--motion", default="look", choices=list(MOTIONS))
    p.add_argument("--dispatch", default="cost_function", choices=list(DISPATCHERS))
    p.add_argument("--aging", type=float, default=0.1, help="age_weight (0 = off)")
    p.add_argument("--n-zones", type=int, default=3, help="zones for zone_based")
    p.add_argument("--w-dist", type=float, default=1.0)
    p.add_argument("--w-dir", type=float, default=2.0)
    p.add_argument("--w-load", type=float, default=0.5)
    p.add_argument("--w-eta", type=float, default=1.5)
    # output
    p.add_argument("--output", default="outputs/run", help="output directory")
    p.add_argument("--plot", action="store_true",
                   help="render distributions.png (wait, total, and arrival-process panels)")
    return p.parse_args(argv)


def main(argv=None) -> None:
    args = _parse_args(argv)
    cfg = SystemConfig(
        n_elevators=args.elevators, n_floors=args.floors,
        capacity=args.capacity, dwell=args.dwell,
    )
    weights = CostWeights(w_dist=args.w_dist, w_dir=args.w_dir, w_load=args.w_load, w_eta=args.w_eta)

    # --- get the trace ---
    if args.input:
        trace = load_trace(args.input, n_floors=cfg.n_floors)
        workload_meta = {"input": args.input}
    else:  # generate (default when no --input)
        trace = generate(args.pattern, args.lam, cfg.n_floors, args.duration, seed=args.seed)
        workload_meta = {"pattern": args.pattern, "lambda": args.lam,
                         "duration": args.duration, "seed": args.seed}

    # --- build scheduler + run ---
    motion = _build_motion(args.motion)
    dispatch = _build_dispatch(args.dispatch, cfg, weights, args.n_zones, args.aging)
    result = run_sim(trace, cfg, motion, dispatch)

    # --- metrics (self-describing run_meta) + outputs ---
    sched_name = f"{args.motion}+{args.dispatch}" + (f"+aging{args.aging}" if args.aging > 0 else "")
    metrics = compute(result, run_meta={"scheduler": sched_name, "workload": workload_meta})

    print(format_console_table(metrics.summary))
    CsvWriter().write(result, metrics, args.output)
    if args.plot:
        plot_distributions(metrics.per_passenger, Path(args.output) / "distributions.png",
                           title=sched_name, include_arrival=True)
    print(f"\nwrote outputs to {args.output}/")


if __name__ == "__main__":
    main()
