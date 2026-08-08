"""Comparison charts for the Phase-2 mean grid (PLAN §16.3, optional add-on).

Reads the 18 `summary_mean.json` files in outputs/experiment/ and renders a
grid of one metric block's statistics (averaged over 100 seeds):

    rows    = the chosen statistics
    columns = traffic pattern: up_peak / down_peak / uniform
    bars    = the 6 schedulers

The best DISPATCH policy per panel (of the 5 LOOK policies) is outlined -- in the
"good" direction for that stat (lower time/distance/stops, higher throughput;
utilization has no single best, so it's left unmarked). The FCFS motion baseline
is always hatched (it answers a different question).

Built-in presets:
    total       -> avg / min / max                              (lower better)
    wait        -> avg / max / p90                              (lower better)
    efficiency  -> total_distance / stops_made / rho / throughput

Usage:  python plot_experiment.py                    # all presets
        python plot_experiment.py efficiency         # just one
        python plot_experiment.py total outputs/x    # a preset from another grid
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402

PATTERNS = ("up_peak", "down_peak", "uniform")

# preset -> (metric block in the summary, statistics to stack as rows, filename)
PRESETS = {
    "total": ("total", ("avg", "min", "max"), "comparison_chart.png"),
    "wait":  ("wait",  ("avg", "max", "p90"), "comparison_chart_wait.png"),
    "travel": ("travel", ("min", "max", "avg"), "comparison_chart_travel.png"),
    "efficiency": ("efficiency",
                   ("total_distance", "utilization_rho", "throughput"),
                   "comparison_chart_efficiency.png"),
    "pooling": ("pooling",
                ("distance_per_passenger", "passengers_per_stop"),
                "comparison_chart_pooling.png"),
}

# which direction is "better" for the winner outline; None = don't mark a winner
DIRECTION = {
    "avg": "min", "min": "min", "max": "min", "p90": "min", "p95": "min",
    "total_distance": "min", "stops_made": "min",   # less movement = more efficient
    "throughput": "max",                            # more delivered per tick = better
    "utilization_rho": None,                        # no single "best" (high can = near cliff)
    "distance_per_passenger": "min",                # less travel per rider = better pooling
    "passengers_per_stop": "max",                   # more riders per stop = more consolidation
}

# nicer y-axis labels for the efficiency stats (time stats are labelled generically)
YLABEL = {
    "total_distance": "total distance (floors)",
    "stops_made": "stops made (count)",
    "utilization_rho": "utilization (busy fraction)",
    "throughput": "throughput (pax/tick)",
    "distance_per_passenger": "distance per passenger (floors)",
    "passengers_per_stop": "passengers per stop",
}

# scheduler folder keys, display order, short labels, colors (match run_demo.py)
ORDER = ["look_round_robin", "look_nearest_car", "look_zone_based",
         "look_cost_function", "look_hungarian", "fcfs_round_robin"]
SHORT = {"look_round_robin": "round-robin", "look_nearest_car": "nearest-car",
         "look_zone_based": "zone-based", "look_cost_function": "cost-function",
         "look_hungarian": "hungarian", "fcfs_round_robin": "fcfs+rr\n(motion base)"}
COLORS = {"look_round_robin": "#9e9e9e", "look_nearest_car": "#4C78A8",
          "look_zone_based": "#B279A2", "look_cost_function": "#54A24B",
          "look_hungarian": "#2E7D32", "fcfs_round_robin": "#E45756"}


def _load(base: Path, metric: str) -> dict:
    """{(pattern, scheduler): metric-block} from the mean files."""
    data = {}
    for pat in PATTERNS:
        for sched in ORDER:
            f = base / f"{pat}__{sched}" / "summary_mean.json"
            data[(pat, sched)] = json.load(f.open())[metric]
    return data


def make_chart(base: Path, preset: str) -> Path:
    metric, stats, fname = PRESETS[preset]
    data = _load(base, metric)

    if metric in ("total", "wait", "travel"):
        suptitle = (f"{metric.upper()} time per passenger, mean over 100 seeds  "
                    f"({' / '.join(stats)} by dispatch policy)")
    else:
        suptitle = f"{metric.capitalize()} metrics, mean over 100 seeds  (by dispatch policy)"

    fig, axes = plt.subplots(len(stats), len(PATTERNS),
                             figsize=(14, 3.4 * len(stats) + 1), sharex="col",
                             squeeze=False)
    fig.suptitle(suptitle, fontsize=13, fontweight="bold")

    for row, stat in enumerate(stats):
        for col, pat in enumerate(PATTERNS):
            ax = axes[row][col]
            vals = [data[(pat, s)][stat] for s in ORDER]
            bars = ax.bar(range(len(ORDER)), vals,
                          color=[COLORS[s] for s in ORDER], edgecolor="white")
            bars[-1].set_hatch("//")                  # FCFS = motion baseline

            direction = DIRECTION.get(stat, "min")
            if direction is not None:                 # outline best of the 5 LOOK policies
                pick = min if direction == "min" else max
                win = vals[:5].index(pick(vals[:5]))
                bars[win].set_edgecolor("black")
                bars[win].set_linewidth(2.2)

            # small floats (rho ~0.8, throughput ~2) need decimals; big counts don't
            fmt = ".2f" if max(abs(v) for v in vals) < 10 else ".0f"
            for i, v in enumerate(vals):
                ax.text(i, v, f"{v:{fmt}}", ha="center", va="bottom", fontsize=8)

            ax.margins(y=0.20)
            if row == 0:
                ax.set_title(pat, fontsize=11, fontweight="bold")
            if col == 0:
                ylab = YLABEL.get(stat, f"{stat} {metric} time (ticks)")
                ax.set_ylabel(ylab, fontsize=10.5, fontweight="bold")
            if row == len(stats) - 1:                 # x labels on the bottom row only
                ax.set_xticks(range(len(ORDER)))
                ax.set_xticklabels([SHORT[s] for s in ORDER],
                                   rotation=40, ha="right", fontsize=8.5)

    fig.tight_layout(rect=[0, 0, 1, 1 - 0.5 / (3.4 * len(stats) + 1)])
    out = base / fname
    fig.savefig(out, dpi=110)
    plt.close(fig)
    print(f"wrote {out}")
    return out


def main() -> None:
    args = sys.argv[1:]
    presets = [a for a in args if a in PRESETS] or list(PRESETS)
    folders = [a for a in args if a not in PRESETS]
    base = Path(folders[0]) if folders else Path("outputs/experiment")
    for preset in presets:
        make_chart(base, preset)


if __name__ == "__main__":
    main()
