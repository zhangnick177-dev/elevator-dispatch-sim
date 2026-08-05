# Dispatch Policy Summary

A living reference for the **dispatch axis** (Axis 2) of the scheduler — definitions, assumptions, and design discussions. Companion to `PLAN.md` (§7 two-axis design, §8 implementation sources).

> **Scope reminder:** a scheduler = **one motion policy × one dispatch policy**. Motion is fixed at **LOOK** (low-leverage, near-solved). *Dispatch* is the high-leverage comparison axis and the subject of this doc. "Which elevator serves a new request?" is the dispatch question.

---

## The dispatch ladder (five policies)

| # | Policy | Decides by | Nature | Phase |
|---|---|---|---|---|
| 1 | **Round-robin** | rotate across cars in turn | naive, position-blind | 1 |
| 2 | **Nearest-car (NCH)** | closest suitable car (distance + direction) | greedy, one-at-a-time | 1 |
| 3 | **Zone-based** | each car owns a floor zone (sectoring) | static partition | 1 |
| 4 | **Cost-function / ETA** | `min` over a weighted cost | greedy, one-at-a-time | 1 |
| 5 | **Optimal batch (Hungarian)** | globally-optimal assignment of a whole batch | optimal, batch | 1 (multi-request via column replication) |

---

## Greedy vs. optimal-batch — the core distinction

This is the key conceptual split on the dispatch axis.

### Greedy (policies 2 & 4)
- Assign **one request at a time**, as it arrives.
- Each request **independently** picks *its own* best car via `min(cars, key=cost)`.
- Multiple requests can pick the **same** car (up to `capacity`) — nothing prevents it.
- **Capacity "just works":** check `is_full()` before assigning; a car naturally accumulates several riders over ticks.

### Optimal batch (policy 5, Hungarian)
- Assign a **whole batch** of waiting requests to cars **simultaneously**.
- Minimizes **total** cost across all requests at once (resolves conflicts globally).
- Implemented via `scipy.optimize.linear_sum_assignment` on a cost matrix `C[i][j]` = cost of request *i* on car *j*.
- It is the **optimal cousin of the cost-function policy** — same cost matrix, solved *globally* instead of *row-by-row*.
- **Role = benchmark / ceiling**, not a shipping policy: measure how far greedy falls short ("cost-function is within X% of optimal").

### Worked example — `lobby→3` and `lobby→8`, 2 cars

| Policy | Outcome |
|---|---|
| **Greedy** | One car takes **both** (going up anyway: drop at 3, then 8). ✅ |
| **Raw Hungarian** (one solve, no fix) | One-to-one matching → car A gets `lobby→3`; `lobby→8` must take **car B or wait**. ⚠️ |
| **Hungarian + column replication** | Car A has ≥2 free-slot columns → takes **both** `lobby→3` *and* `lobby→8`, like greedy. ✅ |

---

## The capacity wrinkle in Hungarian (and why it's a Phase-2 flex)

**Physical capacity is unchanged** (a car still holds e.g. 8). The "one per car" limit is a property of a **single** `linear_sum_assignment` call — the assignment problem is a **bipartite matching**, so each column (car) matches **at most one row (request) per solve**. It is *not* a physical capacity.

### Example: 3 cars (cap 8, empty), 10 requests this tick
- **Greedy:** `E1←4, E2←3, E3←3` → all 10 assigned. ✅
- **Raw Hungarian:** matrix `10×3` → matches `min(10,3)=3` (one per car) → **7 unmatched**. ⚠️

### Three workarounds
1. **Replicate each car into `free_slots` columns.** A car with 8 free seats → 8 columns (same cost profile). Matrix `10×24` → all 10 match, several to the same physical car. **← CHOSEN.**
2. **Assign in rounds.** Solve (≤3 assigned), remove them, solve again on the rest; repeat until all assigned or capacity full. (10 over ~4 rounds.)
3. **Restrict to ≤ 1 per car per tick.** Assign 3 this tick, the other 7 wait for the next tick. Simplest; under-utilizes but often fine (requests usually trickle in a few per tick). **Document as a stated simplification.**

**Build note (now Phase 1):** the algorithm core is ~1 line (`linear_sum_assignment`); the cost-matrix build + column-replication + unmatched/penalty logic adds ~30–60 lines. Kept in **Phase 1** with a safety valve — because dispatch policies are pluggable, if Hungarian misbehaves it is simply **excluded from the run list**; nothing else depends on it.

### `linear_sum_assignment` usage notes (column replication)
- **Rectangular matrix + duplicate columns** are handled **natively** by scipy — no issue.
- Keep a `col_to_car = [c.id for c in cars for _ in range(c.free_slots)]` map; translate returned column indices back to car ids.
- **Unmatched requests** (when `#requests > total free slots`) → they wait for the next tick.
- **Forbidden pairings** (wrong direction, etc.) → large **finite** penalty (e.g. `1e9`), **never** `np.inf` (inf can make scipy raise `ValueError` on infeasibility).
- **Rebuild the matrix each tick** (dimensions change with waiting count / free slots).

### Shared interface (all five policies)
`DispatchPolicy.dispatch(pending, world) → {request_id: elevator_id}` — **batch-oriented**. Greedy policies loop over `pending` internally; Hungarian solves jointly. **Same signature, same return shape** → all swappable, and Hungarian's column↔car / unmatched / penalty bookkeeping is entirely **internal** (invisible to the engine and other policies).

---

## Per-policy definitions & assumptions

### 1. Round-robin
- **Def:** assign incoming requests to cars in strict rotation (`itertools.cycle`).
- **Assumes:** nothing about position/direction — pure load spreading.
- **Weakness:** ignores where cars are → poor under any spatial structure; naive baseline.

### 2. Nearest-car (NCH)
- **Def:** assign to the closest **suitable** (direction-compatible) car, via the classic **Figure of Suitability**: `FS=(N+2)−d` (moving toward, same dir), `(N+1)−d` (toward, opp dir), `1` (moving away); pick **max FS**. `N`=floors, `d`=distance.
- **Assumes:** distance + direction compatibility are good proxies for service time.
- **Weakness:** myopic under bursts; ignores car load and downstream commitments.

### 3. Zone-based (sectoring)
- **Def:** split the building into `n_zones` banks (default **3**: low/mid/high, ~5 cars each); assign a request to the zone containing **`max(source, dest)`** (the non-lobby floor), then the **nearest car within that zone**.
- **Params:** `n_zones` (default 3); within-zone sub-policy = nearest.
- **Why `max(source, dest)`:** up_peak (all source = lobby) needs **dest**-zoning; down_peak (all dest = lobby) needs **source**-zoning; `max` handles **both** (+ uniform) with one rule — essential since the smoke runs cover all three patterns.
- **Assumes:** traffic is well-approximated by static geographic partitioning.
- **Strength/weakness:** great when zones match traffic structure; **fragments a fungible fleet** — with 16 cars / 25 floors it likely *underperforms* nearest-car / cost-function. That's an interesting finding: zoning helps when it matches structure, hurts when it artificially walls off a flexible fleet.

### 4. Cost-function / ETA *(star)*
- **Def:** score each car by `distance + direction-penalty + load + est-completion` (weighted), pick `min`.
- **Assumes:** a hand-tuned cost captures true service cost well; weights are build-time tunables (see `PLAN.md` §12).
- **Strength:** the modern destination-dispatch approach; expected winner; expresses pooling implicitly (a same-direction, already-moving car scores better → more riders per trip).

### 5. Optimal batch (Hungarian)
- **Def:** minimize total assignment cost over a batch via `linear_sum_assignment`.
- **Assumes:** batching *present* (already-arrived) requests each tick — **does not violate "no peek-ahead"** (never sees future requests).
- **Caveats:** "optimal per tick" ≠ "optimal overall" (the online problem has no legitimate global optimum); capacity wrinkle above.

---

## Parameters: features vs. weights, and when they're input

**Features vs. weights — don't conflate them.**
- **Features** (`distance`, `direction_penalty`, `load`, `est_completion`) are **computed from live state** inside `dispatch()` on *every* call — never "input."
- **Weights** (`w_dist`, `w_dir`, `w_load`, `w_eta`) are the **configurable parameters**, set **once at construction**.

**How cost-function works:** score each car, take the cheapest.
```python
best = min(cars, key=lambda c: w1*distance + w2*direction + w3*load + w4*eta)
```
It **generalizes nearest-car**: zero the `load`/`eta` weights and it reduces to distance+direction (≈ NCH); turn them up and it becomes route-aware. `distance`/`direction` are cheap local proxies; `est_completion` is the full route-aware ETA that partly subsumes them; `load` is the orthogonal utilization-balancer.

**Which of the 5 policies are parameterized:**
| Policy | Parameters |
|---|---|
| Round-robin | none |
| Nearest-car (NCH) | none (fixed FS formula) |
| Zone-based | zone boundaries (often auto-derived) |
| Cost-function | 4 weights |
| Hungarian | reuses cost weights + forbidden-pairing penalty |

*(Aging, cross-cutting, adds `age_weight` — not one of the 5.)*

**When & how input:**
- **At construction, before the run** — `CostFunction(w_dist=1.0, w_dir=2.0, w_load=0.5, w_eta=1.5)`; **fixed for the whole run** (same values every tick).
- **Single run (Phase 1):** CLI args / config / defaults — `--dispatch cost_function --w-dist 1.0 …` so KKR can try their own values.
- **Grid (Phase 2):** set once per policy, held fixed — unless studying a parameter's effect, then it becomes a **sweep axis on the same traces** (weights don't change the trace, so CRN still applies).
- Defaults confirmed at `PLAN.md` §12.

---

## Cross-cutting: anti-starvation (aging)

**Purpose / nuance.** Serves KKR Objective 1 ("serve all eventually"). But **LOOK already gives a baseline no-starvation guarantee per car** (its sweep reaches every assigned floor). So aging isn't strictly required to avoid *infinite* starvation — its real job is **bounding the worst-case wait (the tail)**, especially for **cost-function**, which optimizes the *average* and could keep deferring an unlucky outlier. Aging is the **fairness knob** in the fairness-vs-efficiency trade-off.

**Structure — a tiny priority utility, NOT a policy.** It doesn't pick a car; it computes a priority that grows with wait time:
```python
# aging.py
def aged_priority(request, t, weight):
    wait = t - request.submit_tick
    return weight * wait          # longer wait → higher priority
```
`weight` is a build-time tunable (how aggressively to favor long-waiters).

**Two integration styles (dispatch consumes the signal):**
1. **Ordering** — process `pending` **oldest-first** so a long-waiter gets first pick of cars each tick.
2. **Cost biasing** — subtract `aged_priority` from the dispatch cost so a long-waiter scores "cheaper to serve."

```python
# ordering style, inside any dispatch policy:
pending = sorted(pending, key=lambda r: -aged_priority(r, world.t, self.age_weight))
```
Or a **decorator** wrapping any policy: `Aged(RoundRobin())`, `Aged(CostFunction())` — all gain aging for free.

**Why a separate module (and yet not standalone):**
- **Cross-cutting rule** — "prioritize long-waiters" should apply regardless of which dispatch policy is chosen → **one implementation, reused by all five** (DRY). Baking it into each policy would duplicate + desync it.
- **Orthogonal knob** — turn on/off and tune strength independently of the policy choice.
- **Not an independent actor** — it doesn't run alone; it's a **priority modifier the dispatch policy consults** (ordering or cost-bias).
- **Primarily dispatch-level.** Could influence motion (pickup order), but since LOOK is already starvation-free per car, aging's leverage is on the **dispatch** side.

**Implementation finding (M4).** Built as an `Aged(policy, age_weight)` **wrapper** (ordering style). Empirically it's ~a **no-op** in this model and here's the proof:
- **Cost-bias is *provably* no-op** — subtracting a per-passenger constant (`age_weight × wait`) from all its car-costs can't change the `argmin`; and for the Hungarian *assignment problem*, subtracting a constant from a whole row leaves the optimal assignment unchanged.
- **Ordering only bites when the pending pool has *mixed* ages** — but greedy dispatch assigns everyone the instant they arrive (wait≈0), so the pool is all-fresh. Only a **deferring** policy (Hungarian past capacity) creates aged pending.
- The long waits that hurt accrue **after** assignment, where **irrevocable** assignment leaves aging no handle. Real teeth need **re-dispatch** (§14). Verified: `Aged(CostFunction, 0.1)` gives byte-identical results to plain `CostFunction`.

---

## Implementation notes: balancing & correctness fixes (found during M4 testing)

Two bugs surfaced the moment all policies were run on the same trace — both worth
presenting as "found by testing", not hidden.

### 1. Committed-load balancing (the concentration bug)

**Bug.** The greedy policies judged "how busy is a car?" by `len(car.onboard)` —
passengers *physically inside*. But an assigned-yet-**waiting** passenger (queued
at their floor, not boarded) isn't onboard, so a car with hundreds queued looked
*empty* and kept attracting more. Result on up-peak: one car got **522**
passengers while others got ~4 → the fleet couldn't drain.

**Fix.** Use **committed load = onboard + assigned-but-waiting** = the car's true
backlog, and update it **within** each dispatch batch so a burst of simultaneous
arrivals spreads instead of dogpiling one car.
```python
def committed_loads(world):                     # dispatch/cost_function.py
    loads = {e.id: len(e.onboard) for e in world.elevators}
    for p in world.waiting:                      # + assigned, not yet boarded
        loads[p.assigned_elevator] += 1
    return loads
```

**Per-policy usage (they differ):**
| Policy | How committed load is used |
|---|---|
| Cost-function / Hungarian | *is* the `w_load` term in the cost — the **correct** load measure (barely a deviation) |
| **Nearest-car** | added as a **tie-breaker** (`max(FS, -committed, -id)`) — classic NCH has NO load term |
| Zone-based | same tie-break, but among equally-near cars **within a bank** |

**Why it's a defensible deviation.** Classic NCH assumes cars are **spread across
the building**; morning up-peak violates that (all cars pile at the lobby → all
tie on FS → the pure formula sends everyone to the lowest-id car). The
committed-load tie-break is a minimal, principled fix for the degenerate case: the
FS formula and cost terms are unchanged; we only fixed the load *measure* and
spread ties among equally-good cars. Necessary for correctness — without it the
policies concentrate pathologically and can't drain.

### 2. FCFS-motion deadlock (the `is_full` guard)

**Bug.** FCFS serves the *oldest* commitment first. A **full** car chased its
oldest *waiting pickups* (which it can't board) and thrashed between them forever,
never delivering its onboard riders to free a seat → deadlock (on down_peak only
666/2708 delivered). LOOK avoids this naturally because its *sweep* hits the drop-off
floors monotonically; FCFS's oldest-first *jumping* does not.

**Fix.** A full car targets only its **drop-offs** (onboard dests); it considers
pickups again once it frees a seat. One `is_full()` guard in `motion/fcfs.py`.

### 3. Initial car positions (a simplification worth noting)

**All cars start at floor 1 (the lobby), IDLE, for *every* pattern** — a single
`SystemConfig.init_floor = 1` applied uniformly to all cars in the engine loop.
The *value* is a config default (not a hard-coded literal), but "all cars at one
shared floor" is structural (init_floor is an `int`, not a list).

- **Effect on down_peak.** There the passengers start on *upper* floors while the
  cars begin at the lobby, so the cars must first travel up to collect the first
  riders — a small initial transient. It's identical across all policies, so the
  *comparison* stays fair; over a 900-tick run the transient is minor.
- **More realistic alternative.** For down_peak (and normal daytime traffic) the
  cars would in reality be *spread through the building*, not parked at the lobby.
  A **uniform-random initial position** (or pattern-aware placement — e.g. some
  cars pre-positioned high before a down-rush) would better match real life.
- **Decision.** Kept as all-at-lobby for all patterns for **simplicity and
  consistency**. Making it per-car would mean generalizing `init_floor` from an
  `int` to a list/strategy (and optionally a `--init-floor` CLI flag) — a clean
  "what I'd improve" item, not needed for the core comparison.

---

## Future discussion / open questions
*(append as they come up)*

- **Re-dispatch vs. irrevocable:** the plan keeps assignment irrevocable (a bumped passenger waits for its assigned car). Should any policy be allowed to *re-dispatch* a long-waiting request to a different car? (Trade-off: better fairness vs. breaking the "immediately assigns" rule.) — see `PLAN.md` §14.
- **Cost-function weights:** how to set/tune `distance / direction-penalty / load / est-completion`? Grid-search on the experiment harness, or hand-tune?
- **Zone boundaries:** static equal-size zones vs. load-adaptive zones (bonus).
- **Hungarian cost matrix:** reuse the cost-function `estimate_cost()` verbatim, or a simpler distance-only cost for the benchmark?
- **Direction "suitability":** exact definition of a car being "suitable" for a request (same direction + will pass the source floor before reversing?).
