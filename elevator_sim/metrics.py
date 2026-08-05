"""Metrics computation (PLAN §9) — COMPUTE ONLY.

Takes a finished `RunResult` and produces:
  * `per_passenger` — one record per passenger (the granular source for
    `passengers.csv`, the histograms, and the percentiles).
  * `summary`       — the aggregate stats (the `summary_stats.json` shape).

This module does **no file I/O and no plotting** (matplotlib never appears here).
Saving is `io/writers.py`; rendering is `plots.py`. Keeping compute separate is
what lets Phase 2 redirect outputs to Supabase without touching this logic.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass

import numpy as np


@dataclass
class Metrics:
    per_passenger: list[dict]
    summary: dict


def compute(result, run_meta: dict | None = None) -> Metrics:
    """Compute per-passenger records and the aggregate summary from a RunResult.

    `run_meta` is optional identity/config info (scheduler name, workload params,
    seed, ...) merged into summary["run"] so `summary_stats.json` is
    self-describing and drops straight into the Phase-2 results table. The CLI /
    experiment harness supplies it; a bare run just omits it.
    """
    passengers = result.passengers
    n = len(passengers)

    # --- per-passenger records (granular; source for everything below) ---
    per_passenger = [
        {
            "id": p.id,
            "source": p.source,
            "dest": p.dest,
            "submit_tick": p.submit_tick,
            "pickup_tick": p.pickup_tick,
            "dropoff_tick": p.dropoff_tick,
            "wait_time": p.wait_time,
            "travel_time": p.travel_time,
            "total_time": p.total_time,
            "elevator": p.assigned_elevator,
        }
        for p in passengers
    ]

    # Only completed passengers contribute to timing stats (all should be
    # delivered in a healthy run; guarding keeps a stalled run from crashing).
    waits = [p.wait_time for p in passengers if p.wait_time is not None]
    travels = [p.travel_time for p in passengers if p.travel_time is not None]
    totals = [p.total_time for p in passengers if p.total_time is not None]
    n_delivered = len(totals)

    # --- efficiency (from the engine's counters) ---
    car_ticks = max(result.n_ticks * result.n_elevators, 1)
    rho = result.busy_ticks / car_ticks                        # fraction of car-ticks busy
    throughput = n_delivered / max(result.n_ticks, 1)          # passengers per tick
    dist_per_pax = result.total_distance / max(n_delivered, 1)  # lower = better pooling
    pax_per_stop = n_delivered / max(result.stops_made, 1)      # higher = more consolidation

    summary = {
        "run": {
            "system": asdict(result.config),
            "n_passengers": n,
            "n_delivered": n_delivered,
            "n_ticks": result.n_ticks,
            **(run_meta or {}),
        },
        "wait": _stats(waits, percentiles=(90, 95)),
        "travel": _stats(travels),
        "total": _stats(totals),
        "efficiency": {
            "total_distance": result.total_distance,
            "stops_made": result.stops_made,
            "utilization_rho": round(rho, 4),
            "throughput": round(throughput, 4),
        },
        "pooling": {
            "distance_per_passenger": round(dist_per_pax, 4),
            "passengers_per_stop": round(pax_per_stop, 4),
        },
    }
    return Metrics(per_passenger=per_passenger, summary=summary)


def _stats(values: list, percentiles: tuple[int, ...] = ()) -> dict:
    """min / max / avg (+ optional percentiles like p90, p95). Empty -> Nones."""
    if not values:
        out = {"min": None, "max": None, "avg": None}
        out.update({f"p{p}": None for p in percentiles})
        return out
    arr = np.asarray(values)
    out = {
        "min": int(arr.min()),
        "max": int(arr.max()),
        "avg": round(float(arr.mean()), 2),
    }
    for p in percentiles:
        out[f"p{p}"] = round(float(np.percentile(arr, p)), 2)
    return out
