"""CSV trace loader (PLAN §4).

Reads the input contract `time,id,source,dest` into a flat `list[Request]`
(the engine groups by tick itself). Validation is **lenient: skip & warn** — one
bad row must not fail the run — but visible and accounted: each skipped row is
logged with a reason and a summary is printed. Pass `strict=True` to raise
instead (for tests/CI).
"""

from __future__ import annotations

import csv
import sys
from pathlib import Path

from elevator_sim.models import Request


def load_trace(path: str | Path, n_floors: int, strict: bool = False) -> list[Request]:
    path = Path(path)
    requests: list[Request] = []
    skipped: list[tuple[int, str]] = []
    seen_ids: set[str] = set()

    with path.open(newline="") as f:
        reader = csv.DictReader(f)
        for lineno, row in enumerate(reader, start=2):  # header is line 1
            reason = _validate(row, n_floors, seen_ids)
            if reason is not None:
                skipped.append((lineno, reason))
                continue
            pid = row["id"].strip()
            seen_ids.add(pid)
            requests.append(
                Request(
                    id=pid,
                    submit_tick=int(row["time"]),
                    source=int(row["source"]),
                    dest=int(row["dest"]),
                )
            )

    if skipped:
        if strict:
            raise ValueError(f"{len(skipped)} invalid row(s): {skipped[:5]}")
        _report_skipped(len(requests), skipped)
    return requests


def _validate(row: dict, n_floors: int, seen_ids: set[str]) -> str | None:
    """Return a reason string if the row is invalid, else None."""
    try:
        t = int(row["time"])
        pid = row["id"].strip()
        src = int(row["source"])
        dst = int(row["dest"])
    except (KeyError, ValueError, TypeError, AttributeError) as ex:
        return f"parse error: {ex}"
    if not (1 <= src <= n_floors):
        return f"source {src} out of [1,{n_floors}]"
    if not (1 <= dst <= n_floors):
        return f"dest {dst} out of [1,{n_floors}]"
    if src == dst:
        return "source == dest"
    if t < 0:
        return f"time {t} < 0"
    if not pid:
        return "empty id"
    if pid in seen_ids:
        return f"duplicate id {pid!r}"
    return None


def _report_skipped(n_loaded: int, skipped: list[tuple[int, str]]) -> None:
    from collections import Counter

    by_reason = Counter(reason.split(":")[0].split(" out")[0] for _, reason in skipped)
    detail = ", ".join(f"{n}x {r}" for r, n in by_reason.items())
    print(
        f"[trace_loader] loaded {n_loaded}, skipped {len(skipped)} invalid ({detail})",
        file=sys.stderr,
    )
    for lineno, reason in skipped[:10]:
        print(f"[trace_loader]   line {lineno}: {reason}", file=sys.stderr)
