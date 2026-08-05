"""Plot helper (PLAN §9) — the ONLY place matplotlib is imported.

Renders the single-run distribution histograms (wait time + total time) from the
per-passenger records. Decoupled from `metrics.py`: it consumes the same
per-passenger data that goes into `passengers.csv`, so a plot can be regenerated
any time from that file. Called by the orchestrator (`cli.py`), never by
`metrics.py` or the engine.
"""

from __future__ import annotations

from pathlib import Path

import matplotlib

matplotlib.use("Agg")  # non-interactive backend: render to file, no display needed
import matplotlib.pyplot as plt  # noqa: E402


def plot_distributions(per_passenger: list[dict], path: str | Path, title: str = "") -> None:
    """Render side-by-side histograms of wait_time and total_time to `path` (PNG)."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    waits = [r["wait_time"] for r in per_passenger if r["wait_time"] is not None]
    totals = [r["total_time"] for r in per_passenger if r["total_time"] is not None]

    fig, (ax_w, ax_t) = plt.subplots(1, 2, figsize=(11, 4))
    if title:
        fig.suptitle(title)

    ax_w.hist(waits, bins=30, color="#4C78A8", edgecolor="white")
    ax_w.set_title("Wait time")
    ax_w.set_xlabel("ticks")
    ax_w.set_ylabel("passengers")

    ax_t.hist(totals, bins=30, color="#F58518", edgecolor="white")
    ax_t.set_title("Total time (wait + travel)")
    ax_t.set_xlabel("ticks")
    ax_t.set_ylabel("passengers")

    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)
