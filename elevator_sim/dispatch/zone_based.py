"""Zone-based (sectoring) dispatch (PLAN §7/§8, dispatch_policy_summary).

Split the building into `n_zones` banks (default 3: low / mid / high). Each bank
owns a contiguous range of floors AND a group of elevators. A request is assigned
to the bank whose floor-range contains `max(source, dest)`, then to the NEAREST
car within that bank.

WHY `max(source, dest)`
    The smoke runs cover all three patterns, and a single rule must work for each:
      * up_peak   : everyone's source is the lobby -> must zone by DESTINATION.
      * down_peak : everyone's dest is the lobby   -> must zone by SOURCE.
      * uniform   : either works.
    `max(source, dest)` = the higher / non-lobby floor, which handles all three
    with one rule (the responsible car may still pick up or drop off outside its
    zone; the bank just balances the *workload* by the served floor).

EXPECTED BEHAVIOUR
    Good when zones match the traffic structure; but with 16 fungible cars over 25
    floors it FRAGMENTS a flexible fleet (a busy bank's cars overload while another
    bank idles), so it typically underperforms nearest-car / cost-function here —
    an interesting finding, not a bug.
"""

from __future__ import annotations

from elevator_sim.dispatch.base import DispatchPolicy
from elevator_sim.dispatch.cost_function import committed_loads


def _partition(count: int, n_groups: int) -> list[list[int]]:
    """Split range(count) into `n_groups` roughly-equal contiguous groups.
    e.g. _partition(16, 3) -> [[0..5], [6..10], [11..15]] (sizes 6,5,5)."""
    groups: list[list[int]] = []
    base, extra = divmod(count, n_groups)
    start = 0
    for g in range(n_groups):
        size = base + (1 if g < extra else 0)   # first `extra` groups get one more
        groups.append(list(range(start, start + size)))
        start += size
    return groups


class ZoneBased(DispatchPolicy):
    def __init__(self, n_elevators: int, n_floors: int, n_zones: int = 3):
        self.n_floors = n_floors
        self.n_zones = n_zones
        # Elevators split into `n_zones` banks (bank z serves floor-zone z).
        self.banks = _partition(n_elevators, n_zones)

    def _zone_of(self, floor: int) -> int:
        # Map a floor (1..n) to a zone index (0..n_zones-1), contiguous & even.
        # (floor-1) so floor 1 -> 0; clamp guards the top floor.
        z = (floor - 1) * self.n_zones // self.n_floors
        return min(z, self.n_zones - 1)

    def dispatch(self, pending, world) -> dict[str, int]:
        cars_by_id = {e.id: e for e in world.elevators}
        committed = committed_loads(world)
        assignments: dict[str, int] = {}
        for p in pending:
            zone = self._zone_of(max(p.source, p.dest))   # the non-lobby floor
            bank = self.banks[zone]
            # Nearest car within this bank; among equally-near cars prefer the
            # least committed (spreads the bank's load), then lowest id.
            best_id = min(
                bank,
                key=lambda cid: (
                    abs(cars_by_id[cid].current_floor - p.source),
                    committed[cid],
                    cid,
                ),
            )
            assignments[p.id] = best_id
            committed[best_id] += 1
        return assignments
