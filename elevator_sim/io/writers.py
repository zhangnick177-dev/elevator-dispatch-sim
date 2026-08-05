"""CSV/JSON writers + console table (PLAN §9).

`CsvWriter` saves the three files for one run:
  * positions_log.csv  — one row per tick (Convention A: floor at start of tick).
  * passengers.csv     — one row per passenger (granular; source for plots).
  * summary_stats.json — the aggregate metrics.

`format_console_table` renders the human-readable summary for stdout.
"""

from __future__ import annotations

import csv
import json
from pathlib import Path

from elevator_sim.io.base import ResultsWriter

# Column order for passengers.csv (matches metrics.per_passenger keys).
_PASSENGER_COLUMNS = [
    "id", "source", "dest", "submit_tick", "pickup_tick", "dropoff_tick",
    "wait_time", "travel_time", "total_time", "elevator",
]


class CsvWriter(ResultsWriter):
    def write(self, result, metrics, outdir: str | Path) -> None:
        outdir = Path(outdir)
        outdir.mkdir(parents=True, exist_ok=True)
        self.write_positions_log(result, outdir / "positions_log.csv")
        self.write_passengers(metrics.per_passenger, outdir / "passengers.csv")
        self.write_summary(metrics.summary, outdir / "summary_stats.json")

    @staticmethod
    def write_positions_log(result, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.writer(f)
            w.writerow(["tick"] + [f"e{i}" for i in range(result.n_elevators)])
            w.writerows(result.positions_log)

    @staticmethod
    def write_passengers(per_passenger: list[dict], path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w", newline="") as f:
            w = csv.DictWriter(f, fieldnames=_PASSENGER_COLUMNS)
            w.writeheader()
            w.writerows(per_passenger)

    @staticmethod
    def write_summary(summary: dict, path: str | Path) -> None:
        path = Path(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("w") as f:
            json.dump(summary, f, indent=2)


def format_console_table(summary: dict) -> str:
    """Render the aggregate summary as a human-readable table for stdout."""
    run = summary["run"]
    w, tr, tot = summary["wait"], summary["travel"], summary["total"]
    eff, pool = summary["efficiency"], summary["pooling"]
    sched = run.get("scheduler", "")
    # ASCII-only for portable console output (Windows console is cp1252).
    lines = [
        "Passenger Summary"
        + (f"  ({run['n_delivered']}/{run['n_passengers']} delivered, "
           f"{run['n_ticks']} ticks{', ' + sched if sched else ''})"),
        "-" * 52,
        f"{'':10}{'min':>8}{'max':>8}{'avg':>8}{'p90':>8}{'p95':>8}",
        f"{'wait':10}{w['min']:>8}{w['max']:>8}{w['avg']:>8}{w['p90']:>8}{w['p95']:>8}",
        f"{'travel':10}{tr['min']:>8}{tr['max']:>8}{tr['avg']:>8}{'':>8}{'':>8}",
        f"{'total':10}{tot['min']:>8}{tot['max']:>8}{tot['avg']:>8}{'':>8}{'':>8}",
        "-" * 52,
        f"  utilization (rho): {eff['utilization_rho']:<7} throughput: {eff['throughput']}",
        f"  distance/passenger: {pool['distance_per_passenger']:<7} "
        f"passengers/stop: {pool['passengers_per_stop']}",
        f"  total_distance: {eff['total_distance']}   stops: {eff['stops_made']}",
    ]
    return "\n".join(lines)
