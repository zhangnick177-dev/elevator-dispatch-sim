"""Optimal-batch (Hungarian) dispatch (PLAN §7/§8) — the benchmark / ceiling.

The greedy cost-function assigns one request at a time, each grabbing its own
cheapest car; two requests can both greedily want the same car. Hungarian instead
assigns the WHOLE batch of pending requests at once to minimise TOTAL cost,
resolving those conflicts globally. It's the optimal-per-tick cousin of the
cost-function policy (same cost matrix, solved jointly instead of row-by-row) and
its job is to measure how far the greedy heuristics fall short.

CAPACITY VIA COLUMN REPLICATION
    `scipy.optimize.linear_sum_assignment` is a one-to-one matching: each column
    matches at most one row. But a car holds `capacity` riders. So we replicate
    each car into `free_slots` identical columns — a car with 6 free seats becomes
    6 columns — letting one physical car receive several requests in one solve.
    `col_to_car[j]` maps a column back to its car. scipy handles the resulting
    rectangular matrix (rows != cols) and duplicate columns natively.

    * If there are MORE requests than free slots, the extra rows go unmatched;
      we simply omit them from the result and the engine retries them next tick.
    * "optimal per tick" is not "optimal overall" — the online problem (no
      peek-ahead) has no legitimate global optimum; this is the best *legitimate*
      reference.
"""

from __future__ import annotations

import numpy as np
from scipy.optimize import linear_sum_assignment

from elevator_sim.config import CostWeights
from elevator_sim.dispatch.base import DispatchPolicy
from elevator_sim.dispatch.cost_function import committed_loads, estimate_cost


class HungarianDispatch(DispatchPolicy):
    def __init__(self, weights: CostWeights | None = None):
        self.weights = weights or CostWeights()

    def dispatch(self, pending, world) -> dict[str, int]:
        cars = world.elevators

        # Build the columns: replicate each car into `free_slots` columns so it can
        # take multiple riders this solve. col_to_car[j] -> the car id for column j.
        col_to_car: list[int] = []
        car_by_id = {}
        for e in cars:
            car_by_id[e.id] = e
            for _ in range(max(e.free_slots, 0)):
                col_to_car.append(e.id)

        # Nothing to place, or no free slots anywhere -> defer everyone.
        if not pending or not col_to_car:
            return {}

        # Committed load per car (onboard + assigned-waiting) so the cost steers
        # away from over-committed cars — same balancing signal as the greedy
        # policy. (The joint solve + column replication already spread WITHIN this
        # batch; committed_load balances against the standing backlog.)
        committed = committed_loads(world)

        # Cost matrix: rows = pending requests, cols = car-slots. Same per-(rider,
        # car) cost as the greedy cost-function, so this is its optimal cousin.
        cost = np.empty((len(pending), len(col_to_car)))
        for i, p in enumerate(pending):
            for j, cid in enumerate(col_to_car):
                cost[i, j] = estimate_cost(p, car_by_id[cid], committed[cid], self.weights)

        # Minimise total assignment cost. On a rectangular matrix it matches the
        # smaller dimension fully; unmatched rows (requests) are left out.
        rows, cols = linear_sum_assignment(cost)
        return {pending[i].id: col_to_car[j] for i, j in zip(rows, cols)}
