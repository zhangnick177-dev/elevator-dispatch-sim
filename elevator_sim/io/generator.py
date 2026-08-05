"""Synthetic trace generator (PLAN §5).

A trace is two independent random parts:
  * WHEN  — per-tick Poisson(lambda) arrivals.
  * WHERE — origin/destination by traffic `pattern`.

`generate(...)` returns a `list[Request]` in memory (what the engine consumes).
`to_csv(...)` optionally writes it to disk in the input-contract format.

The single `rng` drives *both* parts, so one seed reproduces the whole trace.
`seed` may be a plain int (single run) or a list (the Phase-2 CRN key) — numpy's
`default_rng` accepts either.
"""

from __future__ import annotations

import csv
from pathlib import Path

import numpy as np

from elevator_sim.models import Request

# Traffic patterns. PATTERN_ID is a *stable* mapping (reorder-proof) for the
# Phase-2 seed key — never derive ids from list position (PLAN §5.1).
PATTERNS = ("up_peak", "down_peak", "uniform")
PATTERN_ID = {"uniform": 0, "up_peak": 1, "down_peak": 2}


def _sample_od(rng: np.random.Generator, pattern: str, n_floors: int) -> tuple[int, int]:
    """Sample one (source, dest) pair for the given pattern. Floors are 1..n."""
    if pattern == "up_peak":
        source = 1
        dest = int(rng.integers(2, n_floors + 1))
    elif pattern == "down_peak":
        source = int(rng.integers(2, n_floors + 1))
        dest = 1
    elif pattern in ("uniform", "interfloor"):
        source = int(rng.integers(1, n_floors + 1))
        dest = int(rng.integers(1, n_floors + 1))
        while dest == source:  # enforce source != dest (rare collision, ~1/n)
            dest = int(rng.integers(1, n_floors + 1))
    else:
        raise ValueError(f"unknown pattern {pattern!r}; expected one of {PATTERNS}")
    return source, dest


def generate(
    pattern: str,
    lam: float,
    n_floors: int,
    duration: int,
    seed,
) -> list[Request]:
    """Generate a trace of `Request`s over `duration` ticks.

    Args:
        pattern:  one of PATTERNS.
        lam:      expected arrivals per tick (Poisson rate).
        n_floors: building height (floors are 1..n_floors).
        duration: arrival window in ticks (NOT total run length — the sim
                  drains past it). Total requests ~ lam * duration.
        seed:     int or list of ints (passed straight to numpy default_rng).
    """
    if pattern not in PATTERNS and pattern != "interfloor":
        raise ValueError(f"unknown pattern {pattern!r}; expected one of {PATTERNS}")
    if lam <= 0:
        raise ValueError(f"lam must be > 0, got {lam}")
    if n_floors < 2:
        raise ValueError(f"n_floors must be >= 2, got {n_floors}")
    if duration < 1:
        raise ValueError(f"duration must be >= 1, got {duration}")

    rng = np.random.default_rng(seed)
    counts = rng.poisson(lam, size=duration)  # arrivals per tick (WHEN)

    requests: list[Request] = []
    pid = 0
    for t in range(duration):
        for _ in range(int(counts[t])):
            pid += 1
            source, dest = _sample_od(rng, pattern, n_floors)  # WHERE
            requests.append(
                Request(id=f"passenger{pid}", submit_tick=t, source=source, dest=dest)
            )
    return requests


def to_csv(requests: list[Request], path: str | Path) -> None:
    """Write a trace to disk in the input-contract format `time,id,source,dest`."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["time", "id", "source", "dest"])
        for r in requests:
            writer.writerow([r.submit_tick, r.id, r.source, r.dest])
