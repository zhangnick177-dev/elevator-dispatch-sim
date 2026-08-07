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


def plot_distributions(
    per_passenger: list[dict],
    path: str | Path,
    title: str = "",
    include_arrival: bool = False,
) -> None:
    """Render histograms of wait_time and total_time to `path` (PNG).

    If `include_arrival` is True, add a third panel showing the *arrival process* —
    the distribution of arrivals-per-tick against the theoretical Poisson(λ) curve
    (a check that the generated trace is a Poisson process). Default False keeps
    the original two-panel chart, so existing callers (e.g. cli.py) are unchanged.
    """
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)

    waits = [r["wait_time"] for r in per_passenger if r["wait_time"] is not None]
    totals = [r["total_time"] for r in per_passenger if r["total_time"] is not None]

    n = 3 if include_arrival else 2
    fig, axes = plt.subplots(1, n, figsize=(5.5 * n, 4))
    if title:
        fig.suptitle(title)

    ax_w, ax_t = axes[0], axes[1]
    ax_w.hist(waits, bins=30, color="#4C78A8", edgecolor="white")
    ax_w.set_title("Wait time")
    ax_w.set_xlabel("ticks")
    ax_w.set_ylabel("passengers")

    ax_t.hist(totals, bins=30, color="#F58518", edgecolor="white")
    ax_t.set_title("Total time (wait + travel)")
    ax_t.set_xlabel("ticks")
    ax_t.set_ylabel("passengers")

    if include_arrival:
        _plot_arrival_process(axes[2], per_passenger)

    fig.tight_layout()
    fig.savefig(path, dpi=100)
    plt.close(fig)


def _plot_arrival_process(ax, per_passenger: list[dict]) -> None:
    """Panel: observed arrivals-per-tick vs the theoretical Poisson(λ) PMF.

    A homogeneous Poisson arrival process has per-tick counts that follow
    Poisson(λ). We bin the number of arrivals in each tick, then overlay the
    Poisson curve at the observed mean rate λ̂ — if the bars track the curve, the
    trace is Poisson. (A raw histogram of arrival *times* would be ~uniform and
    wouldn't test this; the *count* distribution is the right test.)
    """
    import numpy as np
    from scipy.stats import poisson

    submits = [r["submit_tick"] for r in per_passenger]
    n_ticks = max(submits) + 1
    per_tick = np.bincount(submits, minlength=n_ticks)   # arrivals in each tick
    lam = per_tick.mean()                                # λ̂ (observed rate)

    kmax = int(per_tick.max())
    ks = np.arange(kmax + 1)
    observed = np.bincount(per_tick, minlength=kmax + 1)  # #ticks with k arrivals
    expected = poisson.pmf(ks, lam) * n_ticks             # Poisson prediction

    ax.bar(ks, observed, color="#54A24B", edgecolor="white", label="observed")
    ax.plot(ks, expected, "o-", color="black", lw=1.5, label=f"Poisson(λ={lam:.2f})")
    ax.set_title("Arrivals per tick (vs Poisson)")
    ax.set_xlabel("arrivals in one tick")
    ax.set_ylabel("number of ticks")
    ax.legend()
