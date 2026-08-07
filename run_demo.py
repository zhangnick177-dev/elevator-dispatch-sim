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
import sys
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


def _write_comparison_chart(rows, base: Path) -> None:
    """Grouped bar chart of avg TOTAL time (the objective) by policy, per pattern.
    Best DISPATCH policy per pattern is outlined; the FCFS motion baseline is hatched.
    Folded into run_demo so `python run_demo.py` reproduces the whole output folder."""
    import matplotlib
    matplotlib.use("Agg")
    import matplotlib.pyplot as plt

    by = {(r["pattern"], r["scheduler"]): r for r in rows}
    dispatch5 = ["look+round_robin", "look+nearest_car", "look+zone_based",
                 "look+cost_function", "look+hungarian"]
    order = dispatch5 + ["fcfs+round_robin"]
    short = {"look+round_robin": "round-robin", "look+nearest_car": "nearest-car",
             "look+zone_based": "zone-based", "look+cost_function": "cost-function",
             "look+hungarian": "hungarian", "fcfs+round_robin": "fcfs+rr\n(motion base)"}
    colors = {"look+round_robin": "#9e9e9e", "look+nearest_car": "#4C78A8",
              "look+zone_based": "#B279A2", "look+cost_function": "#54A24B",
              "look+hungarian": "#2E7D32", "fcfs+round_robin": "#E45756"}

    fig, axes = plt.subplots(1, 3, figsize=(14, 4.8))
    fig.suptitle("Average TOTAL time per passenger (wait + travel = the objective)",
                 fontsize=12.5, fontweight="bold")
    for ax, pat in zip(axes, PATTERNS):
        vals = [by[(pat, s)]["total_avg"] for s in order]
        bars = ax.bar(range(len(order)), vals, color=[colors[s] for s in order], edgecolor="white")
        bars[-1].set_hatch("//")                        # FCFS = motion baseline (different axis)
        win = vals[:5].index(min(vals[:5]))             # best DISPATCH policy (of the 5 LOOK)
        bars[win].set_edgecolor("black"); bars[win].set_linewidth(2.2)
        for i, v in enumerate(vals):
            ax.text(i, v, f"{v:.0f}", ha="center", va="bottom", fontsize=8)
        ax.set_title(pat)
        ax.set_xticks(range(len(order)))
        ax.set_xticklabels([short[s] for s in order], rotation=40, ha="right", fontsize=8.5)
        ax.set_ylabel("avg total time (ticks)")
        ax.margins(y=0.18)
    fig.tight_layout(rect=[0, 0, 1, 0.93])
    fig.savefig(base / "comparison_chart.png", dpi=110)
    plt.close(fig)


def main() -> None:
    # output folder: optional CLI arg (e.g. outputs/demo_arrival_process), else the default
    base = Path(sys.argv[1]) if len(sys.argv) > 1 else Path("outputs/demo")

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
            outdir = base / f"{pattern}__{motion_name}_{dispatch_name}"
            CsvWriter().write(res, m, outdir)
            # 3-panel distributions: wait, total, AND the arrival process (Poisson check)
            plot_distributions(m.per_passenger, outdir / "distributions.png",
                               title=f"{sched}, {pattern} lambda={LAM}", include_arrival=True)

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

    # write the illustrative comparison table + chart (single-seed; rigorous grid is Phase 2)
    base.mkdir(parents=True, exist_ok=True)
    comp = base / "comparison.csv"
    with comp.open("w", newline="") as f:
        w = csv.DictWriter(f, fieldnames=list(rows[0].keys()))
        w.writeheader()
        w.writerows(rows)
    _write_comparison_chart(rows, base)
    print(f"\n18 runs written to {base}/  (+ comparison.csv + comparison_chart.png)")


if __name__ == "__main__":
    main()
