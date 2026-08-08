"""Phase 2 — Local replicated experiment grid (PLAN §16).

Upgrades the single-seed Phase-1 demo into *averaged* results: run each of the
18 smoke configs (6 schedulers x 3 patterns) across R=100 seeds and average every
metric, so the policy comparison isn't a fluke of one random trace.

  * Mini-CRN: for each (pattern, replication) the trace is generated ONCE and all
    6 schedulers run on it, seeded by `default_rng([base_seed, PATTERN_ID, r])`.
    Same-trace comparison within a replication; independent traces across them.
  * Aggregation is IN MEMORY: the per-run summaries (from metrics.compute) are
    collected in a list per config and averaged field-by-field. No per-replicate
    files are written -- only the 18 means.
  * Output: one `summary_mean.json` per config, same schema as summary_stats.json
    with every value = the mean over R runs, plus n_replications / base_seed.
        outputs/experiment/{pattern}__{motion}_{dispatch}/summary_mean.json

Total: 100 x 18 = 1,800 runs (~15-25 min locally, single-threaded).

Usage:  python experiments.py            # full grid -> outputs/experiment/
        python experiments.py 5          # quick check: R=5 replications
        python experiments.py 100 out    # R=100 into outputs/out/
"""

from __future__ import annotations

import json
import sys
import time
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
from elevator_sim.io.generator import PATTERN_ID, generate
from elevator_sim.metrics import compute
from elevator_sim.motion.fcfs import FcfsMotion
from elevator_sim.motion.look import LookMotion

CFG = SystemConfig()          # office-building defaults (16 / 25 / cap 10 / dwell 2)
WEIGHTS = CostWeights()
AGE_WEIGHT = 0.1
LAM, DURATION = 3, 900
BASE_SEED = 42
R_DEFAULT = 100               # replications per config (PLAN §16.1)
PATTERNS = ("up_peak", "down_peak", "uniform")

# The same 6 schedulers as the smoke runs (§10-B): 5 dispatch on LOOK + FCFS baseline.
SCHEDULERS = [
    ("look", "round_robin"),
    ("look", "nearest_car"),
    ("look", "zone_based"),
    ("look", "cost_function"),
    ("look", "hungarian"),
    ("fcfs", "round_robin"),   # motion baseline (shows the FCFS->LOOK gap)
]


def _make_dispatch(name):
    # Rebuilt fresh for every run: some policies carry state (round-robin's cursor)
    # that must not leak between replications.
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


def _avg(values: list):
    """Average a list of matching summary-values, recursing through nested dicts.

    Numbers -> mean (rounded); nested dicts -> averaged key-by-key; strings ->
    passed through (identity fields are constant across a config's runs). Nones
    (a stalled run with nothing delivered) are dropped before averaging; an
    all-None field stays None. This lets one function average the whole summary.
    """
    non_null = [v for v in values if v is not None]
    if not non_null:
        return None
    first = non_null[0]
    if isinstance(first, dict):
        return {k: _avg([v[k] for v in non_null]) for k in first}
    if isinstance(first, str):
        return first                       # scheduler / pattern names: constant
    return round(sum(non_null) / len(non_null), 4)


def _mean_summary(summaries: list[dict], pattern: str, n_reps: int) -> dict:
    """Field-by-field mean of R per-run summaries into one summary_mean.json body.

    The metric blocks (wait/travel/total/efficiency/pooling) and the run counts
    are averaged; the identity block (system config, scheduler, pattern, lambda)
    is taken verbatim from the first run since it's constant across replications.
    """
    mean = _avg(summaries)

    proto = summaries[0]["run"]
    mean["run"] = {
        "system": proto["system"],                       # constant -> keep as ints
        "scheduler": proto["scheduler"],
        "workload": {"pattern": pattern, "lambda": LAM, "duration": DURATION},
        "base_seed": BASE_SEED,
        "n_replications": n_reps,
        # averaged over the R traces (each seed draws a slightly different trace):
        "n_passengers": mean["run"]["n_passengers"],
        "n_delivered": mean["run"]["n_delivered"],
        "n_ticks": mean["run"]["n_ticks"],
    }
    return mean


def main() -> None:
    reps = int(sys.argv[1]) if len(sys.argv) > 1 else R_DEFAULT
    out_name = sys.argv[2] if len(sys.argv) > 2 else "experiment"
    base = Path("outputs") / out_name

    t0 = time.time()
    n_configs = len(PATTERNS) * len(SCHEDULERS)
    print(f"Grid: {len(SCHEDULERS)} schedulers x {len(PATTERNS)} patterns "
          f"x {reps} reps = {reps * n_configs} runs -> {base}/")

    for pattern in PATTERNS:
        # collect this pattern's per-run summaries, keyed by scheduler
        acc: dict[str, list[dict]] = {f"{m}_{d}": [] for m, d in SCHEDULERS}

        for r in range(reps):
            # mini-CRN: one trace per (pattern, replication), shared by all 6 schedulers
            trace = generate(pattern, LAM, CFG.n_floors, DURATION,
                             seed=[BASE_SEED, PATTERN_ID[pattern], r])
            for motion_name, dispatch_name in SCHEDULERS:
                motion = LookMotion() if motion_name == "look" else FcfsMotion()
                dispatch = Aged(_make_dispatch(dispatch_name), AGE_WEIGHT)

                with warnings.catch_warnings():
                    warnings.simplefilter("ignore")     # suppress per-run stall warnings
                    res = run_sim(trace, CFG, motion, dispatch)

                sched = f"{motion_name}+{dispatch_name}"
                m = compute(res, run_meta={
                    "scheduler": sched,
                    "workload": {"pattern": pattern, "lambda": LAM},
                })
                acc[f"{motion_name}_{dispatch_name}"].append(m.summary)

        # average each config's R summaries and write its single mean file
        for motion_name, dispatch_name in SCHEDULERS:
            summaries = acc[f"{motion_name}_{dispatch_name}"]
            mean = _mean_summary(summaries, pattern, reps)
            outdir = base / f"{pattern}__{motion_name}_{dispatch_name}"
            outdir.mkdir(parents=True, exist_ok=True)
            with (outdir / "summary_mean.json").open("w") as f:
                json.dump(mean, f, indent=2)

        elapsed = time.time() - t0
        print(f"  {pattern:10} done ({reps} reps x {len(SCHEDULERS)} schedulers)  "
              f"[{elapsed:5.1f}s elapsed]")

    print(f"\n{n_configs} summary_mean.json files written to {base}/  "
          f"({time.time() - t0:.1f}s total)")


if __name__ == "__main__":
    main()
