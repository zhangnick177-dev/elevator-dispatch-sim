"""Anti-starvation aging (PLAN §7, dispatch_policy_summary) — composable fairness hook.

`Aged` WRAPS any dispatch policy and, before delegating, reorders the pending pool
so the LONGEST-WAITING passengers are dispatched first. Because the greedy policies
update their committed-load balance as they assign within a batch, going
oldest-first means a long-waiter gets first pick of the least-committed cars. It
composes with any policy: `Aged(CostFunction(w), age_weight=0.1)`.

WHY ORDERING (not a cost discount)
    A per-passenger cost *discount* (`age_weight * wait`) is provably a no-op: it's
    a constant offset across a passenger's car-costs, so it can't change which car
    is cheapest (argmin), and for the Hungarian assignment problem subtracting a
    constant from a whole row leaves the optimal assignment unchanged. ORDERING is
    the only form that can actually affect the outcome.

WHY IT'S ~A NO-OP IN THIS MODEL (a finding, not a bug)
    Greedy dispatch assigns passengers the instant they arrive, so the pending pool
    is almost always all-fresh (wait ≈ 0) — nothing to reorder. Ordering only bites
    when the pool contains passengers of DIFFERENT ages, which needs a policy that
    DEFERS (e.g. Hungarian, when requests exceed free slots). The long waits that
    actually hurt accrue AFTER assignment, where irrevocable assignment leaves aging
    no handle. Real teeth would need **re-dispatch** (the §14 open question). LOOK
    already guarantees no *infinite* starvation, so aging is a tail-reducer, not a
    correctness fix. `age_weight = 0` disables it (identity wrapper).
"""

from __future__ import annotations

from elevator_sim.dispatch.base import DispatchPolicy


class Aged(DispatchPolicy):
    def __init__(self, inner: DispatchPolicy, age_weight: float = 0.1):
        self.inner = inner
        self.age_weight = age_weight

    def dispatch(self, pending, world) -> dict[str, int]:
        # Reorder oldest-first (smallest submit_tick) so long-waiters get first pick.
        # age_weight only gates on/off here (any positive value gives the same
        # oldest-first order); it's kept as the tunable knob for the cost-bias
        # variant / future re-dispatch. Stable sort -> same-age passengers keep
        # arrival order (determinism).
        if self.age_weight > 0 and len(pending) > 1:
            pending = sorted(pending, key=lambda p: p.submit_tick)
        return self.inner.dispatch(pending, world)
