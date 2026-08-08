# Elevator System Simulation — Project Plan

**Source:** KKR take-home (`Take_home_Elevator.pdf`)
**Goal:** A discrete-time simulation of a multi-elevator *Destination Dispatch* system that serves all requests, minimizes per-passenger `total_time = wait_time + travel_time`, and honors capacity/direction constraints.

---

## 1. Problem restatement (what's actually required)

- **Discrete-time** model: tick forward **one unit at a time**; 1 tick = 1 floor of travel. No peeking ahead beyond the current tick.
  - **Elevator speed = constant 1 floor/tick** (no acceleration/deceleration modeled — a deliberate simplification). Pure travel between floors A and B costs `|A − B|` ticks; stopping adds time only via `dwell` (§2).
- **Destination Dispatch**: each request carries **origin + destination** up front; controller assigns it to an elevator immediately; assignment is irrevocable.
- **Configurable**: number of elevators, number of floors, max passengers per elevator.
- **Scheduler**: our choice of algorithm, satisfying the three objectives.

**Objectives**
1. Serve all requests eventually (no starvation).
2. Minimize `total_time = wait_time + travel_time` per passenger.
3. Honor capacity + direction logic.

**Required outputs**
1. **Elevator positions log** — one row per timestamp (from t=0), positions of all elevators, written to a file.
2. **Passenger summary statistics** — min/max/avg **wait** and **total** times, plus notable observations about time distributions / system behavior.

---

## 2. Scope & assumptions (state these in the README)

- **Input is a contract, not a dataset.** The `time,id,source,dest` format is the interface; KKR is not expected to supply a dataset. We validate on hand-built traces and characterize on self-generated synthetic loads.
- **Time model**: fixed-tick discrete-time. Each tick, every elevator moves at most one floor; boarding/alighting happens on arrival at a floor.
- **Door dwell**: a parameter — **`dwell` ticks per *stop*** (per stop, **not** per passenger), **default 0**. The engine supports any value at no added cost (`dwell=0` → instant boarding; `dwell≥1` → a doors-open phase). Documented as a knob.
- **Wait time** = ticks from request submission until pickup (boarding at source).
- **Travel time** = ticks from pickup until drop-off at destination.
- **Direction logic**: elevators serve requests in a directional sweep (LOOK), reversing only when no further requests lie ahead in the current direction.
- **Capacity**: hard cap; a full elevator cannot board a waiting passenger. **Bumped passengers stay in the queue with their original request** — same submission time (so `wait_time` keeps counting from the first press; **not** reset), still assigned to the same elevator (irrevocable) — and board on that car's next pass with free capacity. (Real-world "re-pressing" is a no-op: the call is already registered. Re-dispatch to a *different* car is a separate advanced option — see §14.)
- **Determinism**: given the same input trace + seed, output is reproducible (important for testing and for the audit-style positions log).

---

## 3. Architecture (modules)

```
elevator_sim/
  models.py        # Request, Passenger, Elevator (targets = set[int]), enums (Direction, State)
  engine.py        # discrete-time tick loop, world state, event bookkeeping
  motion/          # AXIS 1 — how one car sequences its own stops (low-leverage)
    base.py          # MotionPolicy interface
    look.py          # LOOK sweep — the fixed motion policy for all runs (primary)
    fcfs.py          # arrival-order motion — naive baseline, used only to show the gap
  dispatch/        # AXIS 2 — which elevator serves a new request (HIGH-leverage)
    base.py          # DispatchPolicy interface
    round_robin.py   # KKR-named — rotation baseline
    nearest_car.py   # KKR-named — closest suitable elevator (classic heuristic)
    zone_based.py    # KKR-named — sectoring (each car owns a floor zone)
    cost_function.py # weighted-ETA — destination-dispatch star (expected winner)
    aging.py         # anti-starvation priority boost (composable with any dispatch)
  metrics.py       # wait/travel/total, fairness percentiles, ρ, distance/pooling — compute only
  plots.py         # single-run histograms (wait + total); matplotlib lives ONLY here
  io/
    base.py            # ResultsWriter interface (CsvWriter; core stays I/O-agnostic)
    writers.py         # CsvWriter: positions_log.csv + passengers.csv + summary_stats.json
    trace_loader.py    # read requests from CSV (the input contract)
    generator.py       # Poisson(λ) + origin-destination synthetic loads
  experiments.py   # (Phase 2) 100 seeds × 18 configs → average → summary_mean.json per config
  cli.py           # single run: engine → metrics → writers → plots (histograms)
tests/
  test_correctness.py  # the tiny hand-checked scenarios
README.md
```

**Design principle:** motion and dispatch are **two independent, pluggable axes** (the architecture can compose any motion × any dispatch). Effort is allocated by *leverage*:

- **Motion (Axis 1) is low-leverage and near-solved** → we fix it at **LOOK** for all runs. FCFS-motion exists only as a naive baseline to *measure* the gap, not to develop further.
- **Dispatch (Axis 2) is high-leverage** → this is where the real work, the algorithm comparison, and the interesting plots live.

---

## 4. Input contract (CSV)

Exactly the prompt's format:

```
time,id,source,dest
0,passenger1,1,51
0,passenger2,1,37
10,passenger3,20,1
```

- `time` (int): submission tick. `id` (str): unique. `source`, `dest` (int): floors.
- **Loader output:** a **flat `list[Request]`** (parse + validate only — no tick grouping). The **engine** builds its own `{tick: [requests]}` at init. Keeps the loader a general adapter (Phase 2's DB loader returns the *same* flat list).
- **Validation rules:** floors in `[1, n]`, `source != dest`, `time >= 0`, ids unique, all columns present/parseable.
- **Bad-row policy: lenient — skip & warn** (one bad row must not fail the run), but **visible and accounted**, never silent:
  - log each skipped row with its **reason**;
  - print an **end-of-load summary** — e.g. `"loaded 997, skipped 3 (2 source==dest, 1 out-of-range)"`;
  - optional **`strict=True`** flag to raise instead (for tests/CI).
  - Rationale: robust to messy input *without* silently computing stats on a truncated dataset. Documented in the README.
- Any conforming file runs — including one KKR might supply.

---

## 5. Load generator (synthetic experiments)

Produces a trace matching the CSV contract (`time,id,source,dest`) from stochastic inputs.

**Output form:** `generate(...)` **returns a `list[Request]` in memory** (consumed directly by `run_sim`); a separate **`to_csv()` helper** writes that same trace to disk when a file is wanted. Use `to_csv()` for **single / demo / showcase runs** (e.g. the KKR full run — a reproducible input artifact alongside the positions log) — but **not** for the Phase-1 experiment grid, where traces stay in-memory and regenerate from seed (§5.1) to avoid file explosion.

**Phase 2 note:** the experiment grid never persists traces — each is regenerated from its seed on demand (the seed reproduces any trace exactly). Only the averaged results (`summary_mean.json` per config) are written.

A trace is **two independent random parts**: **WHEN** each request arrives (Poisson) and **WHERE** it goes (origin-destination).

### Part 1 — Arrivals (Poisson)
Use **per-tick counts** (cleaner for discrete-time than exponential gaps): at each tick `t`, draw `N_t ~ Poisson(λ)` arrivals. Naturally allows multiple same-tick requests (the prompt's example has two at t=0).
```python
counts = rng.poisson(lam, size=duration)   # counts[t] = arrivals at tick t
```
> **`duration` = the arrival window** (how long new requests keep coming), **not** the total run length. The sim ticks *past* `duration` to **drain** the last passengers to their destinations. Sample size ≈ `λ × duration`.

### Part 2 — Origin-Destination (spatial)
For each arrival, assign floors by `pattern` (always enforce `source != dest`):

| `pattern` | source | dest |
|---|---|---|
| `uniform` / `interfloor` | Uniform(1, n) | Uniform(1, n), ≠ source |
| `up_peak` | 1 (lobby) | Uniform(2, n) |
| `down_peak` | Uniform(2, n) | 1 (lobby) |

### Parameter buckets (keep these separate)
The generator owns **only** Bucket 1. Building params (Bucket 2) and the scheduler (Bucket 3) do **not** affect the trace — they are applied when the sim *runs* the trace.

| Bucket | Params | Owner | In grid? |
|---|---|---|---|
| **1. Workload** (defines the trace) | `pattern`, `λ`, `n_floors`, `duration` | generator | `pattern`, `λ` **swept**; `n_floors`, `duration` fixed |
| **2. System/building** | `n_elevators` (c), `capacity`, `dwell`, `n_floors` | simulation | fixed (c optional secondary sweep) |
| **3. Scheduler** | motion (LOOK), dispatch policy | simulation | dispatch **swept** |

### Library
- **`numpy`** only for randomness — `rng = numpy.random.default_rng(seed)`, then `rng.poisson(...)`, `rng.integers(...)`. No special "Poisson library"; `rng.poisson` *is* it.
- **`csv`** (stdlib) or `pandas` to write the file.

> Note: we assume a distribution only for **arrivals + origin-destination**. The **service-time distribution is emergent** (travel + stops + dwell + capacity blocking) — measured from the sim, not assumed.

### 5.1 Reproducibility & seeding (Common Random Numbers)

**Replicate:** the sim is stochastic → run **R** replications per workload config and report **mean ± std-error** (error bars).

**Seed from identity, not loop position.** A running counter (`seed += 1`) is fragile — inserting/reordering configs shifts every downstream seed, and no cell is independently reproducible. Instead derive the seed from *what the cell is*:
```python
seed = [base_seed, pattern_id, lam_id, replicate]   # only TRACE-affecting axes
rng  = numpy.random.default_rng(seed)               # SeedSequence → independent streams
```
Only params that change the **trace** go in the key (`pattern`, `λ`; add `n_floors`/`duration` only if swept). **Excluded on purpose:** `n_elevators`, `capacity`, `dwell`, and the **scheduler** — none of them alter the trace.

**One `rng` drives the whole trace (same library throughout).** The single `rng = numpy.random.default_rng(seed)` feeds **both** parts of the trace — arrivals via **`rng.poisson`** (WHEN) *and* the pattern/OD floor draws via **`rng.integers`** (WHERE, `source`/`dest`). So one seed deterministically reproduces the entire trace — *when* and *where*. No second RNG source (don't mix in stdlib `random`), or reproducibility breaks.

**Use stable IDs, not `enumerate()` positions.** Build `pattern_id` / `lam_id` from **fixed mappings**, e.g. `PATTERN_ID = {"uniform": 0, "up_peak": 1, "down_peak": 2}`, rather than a list's `enumerate()` index. `enumerate()` is fine until someone reorders the patterns/λ lists — then the ids shift and every seed silently changes. Fixed mappings make each cell's seed **reorder-proof**.

**Common Random Numbers (CRN):** because the scheduler and building params are *out* of the seed, the **same trace is reused across all schedulers** (and all `c`) at a fixed `(pattern, λ, replicate)`. The measured gap is then **purely the policy**, not luck of the draw → paired comparison, tight error bars. Generate once, run all:
```python
for p in patterns:
    for lam in lambdas:
        for r in range(R):
            pattern_id, lam_id = PATTERN_ID[p], LAMBDA_ID[lam]          # stable ids, not positions
            trace = generate(p, lam, n_floors, duration,
                             seed=[base_seed, pattern_id, lam_id, r])   # ONE trace
            for sched in schedulers:
                run_sim(trace, system_config, sched)                    # every policy, same trace
```
For parallel workers, use `SeedSequence(base_seed).spawn(n)` for independent sub-streams.

---

## 6. Simulation engine (discrete-time tick loop)

**At load time:** `last_arrival = max(submit_tick over all requests)` — engine bookkeeping for termination (does **not** leak to the scheduler; see note).

Per tick `t`:
1. **Log positions** — snapshot each elevator's current floor (**Convention A**: state *at* time t, *before* this tick's move). Row `t=0` is the initial configuration.
2. **Admit** new requests where `submit_tick == t` → into the waiting pool. (The scheduler only ever sees requests with `submit_tick ≤ t` — no peek-ahead.)
3. **Dispatch** — assign any unassigned requests to elevators per policy; adds pickup targets. Irrevocable.
4. **Service current floor** (each elevator, *before* moving): **alight** onboard passengers whose `dest == current_floor` (stamp `dropoff_tick`), then **board** waiting assigned passengers at `current_floor` up to `capacity` (stamp `pickup_tick`). If any boarding/alighting occurred and `dwell > 0`, set `dwell_remaining = dwell`. *(Servicing before moving prevents the "car sitting on the passenger's floor drives away first" bug.)*
5. **Move** (each elevator, dwell-aware): if `dwell_remaining > 0`, decrement it and **stay put**; else move one floor toward the next target (motion policy / LOOK), or stay idle if no targets.
6. **Advance `t`.**

**Termination:** stop when `t > last_arrival` **AND** all passengers delivered **AND** all elevators idle. The sim ticks *past* `last_arrival` to **drain** remaining passengers. **Two safety nets** (both raise a warning → a hang becomes a diagnosable failure):
1. **Stall detector** *(primary)* — break if **no delivery for `4×n_floors + dwell + 20` ticks** while work remains. Allows arbitrarily long *legitimate* drains (heavy load / λ-sweep) but catches a genuine hang fast.
2. **Absolute hard cap** *(backstop)* — `MAX_TICKS = last_arrival + 200×n_floors` (generous: adversarial policies on adversarial patterns legitimately drain up to ~80×n_floors past arrival; the stall detector is the real safety, so this just needs ample headroom).

*(Implementation note, M2: the original fixed `10×n_floors` cap was too tight — a heavy up-peak backlog legitimately drains ~10×n_floors past arrivals, so it tripped on the last passenger. Hence the stall detector + generous `50×n_floors` backstop.)*

> **Peek-ahead note:** `last_arrival` is used *only* for loop termination (engine bookkeeping over the already-loaded trace). Scheduling decisions (step 3) use *only* requests admitted so far (`submit_tick ≤ t`). "Don't peek ahead" constrains the **scheduler's decisions**, not the **engine's stop condition**.

### Engine implementation shape

The engine is a **pure-Python state-stepper** — a `while` loop that mutates object state one tick at a time. There is **no numerical math, no solver, and no simulation framework**.

```python
def run_sim(trace, system_config, scheduler):
    world = init_world(system_config)              # elevators + empty waiting pool
    by_tick = group_by_tick(trace)                 # {t: [requests]} (engine's own grouping)
    last_arrival = max(r.submit_tick for r in trace)
    t, positions_log = 0, []
    while not terminated(world, t, last_arrival):
        positions_log.append(snapshot(world))      # 1. log (Convention A)
        admit(world, by_tick.get(t, []))           # 2. arrivals
        scheduler.dispatch(world)                  # 3. assign (dispatch policy)
        for e in world.elevators:
            service_floor(e)                       # 4. alight/board + dwell
            move(e, scheduler.motion)              # 5. dwell-aware move (LOOK)
        t += 1
    return collect_metrics(world), positions_log
```

- **`while`, not `for`** — the end tick (drain) is dynamic, not known up front.
- **Libraries:** stdlib only — `itertools.cycle` (round-robin); each car's target floors are a **`set[int]`**, and LOOK picks the next stop via a `min()`/`max()` filter in the sweep direction (no heap needed at this scale). **No `numpy` in the engine** (numpy lives in the generator's RNG and in metrics/plots). The "math" is trivial arithmetic (`current_floor ± 1`, `abs(a−b)`, comparisons).
- **Each elevator is a small state machine:** every tick it services its floor and steps one toward its next target (motion policy) or idles — i.e. `state[t+1] = update(state[t])`.

> **Queueing math ≠ engine.** M/M/c, `ρ = λ/cμ`, the `1/(1−ρ)` cliff are the **analytical lens to *interpret* results (§13)** — they are **not computed inside the engine**. The engine mechanically simulates; ρ, wait times, and the cliff are **measured from its output** (§9). We never plug numbers into a queueing formula to run the sim — we run the sim and *observe* behavior the theory then *explains*.

---

## 7. Schedulers (two independent axes)

A scheduler = **one motion policy × one dispatch policy**. We fix motion at LOOK and vary dispatch.

> ⚠️ **Reminder — manual review required.** When implementing each scheduler algorithm (motion *and* dispatch), pause for the user to **manually review the algorithm logic** before moving on. Do not treat the scheduler code as done until that review happens.

### Axis 1 — Motion policy (FIXED at LOOK)
- **LOOK** *(primary, used everywhere)* — sweep in one direction serving all requests ahead, reverse only when nothing remains that way. Near the practical ceiling for single-car online motion; naturally starvation-free.
- **FCFS-motion** *(baseline only)* — serve in arrival order. Included solely to *measure* the LOOK-vs-FCFS gap (thrashing); not developed further. Motion is low-leverage.

### Axis 2 — Dispatch policy (the comparison — high-leverage)
| Dispatch | How it assigns a new request | Role |
|---|---|---|
| **Round-robin** | rotate across elevators | KKR-named; naive load-balancer baseline |
| **Nearest-Car** | closest suitable (direction-compatible) elevator | KKR-named; classic heuristic |
| **Zone-based** | building split into `n_zones` banks; request → zone by `max(source,dest)`, nearest car within zone | KKR-named; good when zones match traffic, fragments a fungible fleet |
| **Cost-function / ETA** *(star)* | `min` over `distance + direction-penalty + load + est-completion` | modern destination-dispatch; expected winner |
| **Optimal batch (Hungarian)** | globally-optimal assignment of the whole pending batch (`linear_sum_assignment`) | the ceiling / benchmark (**Phase 1**); multi-request via **column replication** |

- **Batch-oriented interface**: `DispatchPolicy.dispatch(pending, world) → {request_id: elevator_id}`. Greedy policies loop internally; Hungarian solves the batch jointly — **same signature**, so all five are swappable and Hungarian's column↔car mapping / unmatched / penalty bookkeeping stays **internal**. (If Hungarian ever misbehaves, just exclude it from the run list — nothing else depends on it.)
- **Anti-starvation**: `aging.py` — an `Aged(policy, age_weight)` **wrapper** that reorders pending oldest-first before delegating. Composable with any policy. **Implementation finding (M4):** it's ~a **no-op under immediate + irrevocable greedy dispatch** — dispatch happens at wait≈0 (nothing to age), and a cost *discount* is *provably* no-op (constant per-passenger offset can't change an argmin or a Hungarian assignment). LOOK already prevents *infinite* starvation; aging is a tail-reducer that only bites with a **deferring** policy or **re-dispatch** (§14). Kept as the tunable hook (`age_weight=0` disables).
- **Bonus (optional)**: express elevators (skip floors) — a variant layered on top of dispatch.

### Scheduler parameters — when & how input
- **Features vs. weights:** the cost terms (`distance`, `direction_penalty`, `load`, `est_completion`) are **computed from live state** each call; the **weights** are the configurable parameters. (Parameterized policies: zone-based [boundaries], cost-function [4 weights], Hungarian [weights + penalty], aging [`age_weight`]; round-robin & nearest-car take none.)
- **At construction, before the run** — e.g. `CostFunction(w_dist=1.0, w_dir=2.0, w_load=0.5, w_eta=1.5)`; **fixed for the whole run** (same values every tick).
- **Single run (Phase 1):** supplied via **CLI args / config / defaults** (`--dispatch cost_function --w-dist 1.0 …`) so KKR can try their own values.
- **Grid (Phase 2):** set once per policy, held **fixed** across the grid — unless a parameter's effect is being studied, then it becomes a sweep axis (weights don't change the trace, so CRN still applies).
- Defaults confirmed at §12.

### A note on pooling (why there is NO third axis)
Pooling is **not** a separate implemented axis here — it is **emergent**: `capacity > 1` plus the dispatch policy grouping same-direction passengers means each car carries several riders, decided *at the instant of assignment* (matching the prompt's *"immediately assigns them to a specific elevator"*). That is instant **grouping**, not waiting. A deliberate **adaptive batching window** (holding requests to accumulate more before assigning) *would* be a third axis — but it **contradicts "immediately assigns" and is out of core scope**. Its pooling ↔ utilization (ρ) trade-off is kept as *analysis only* — see §9 (notable observations) and §13 (conceptual framing), tied to the fairness-vs-efficiency bonus.

---

## 8. Dependencies & implementation sources

**Principle:** the algorithms are the deliverable — they are **hand-written**, not imported. Third-party libraries handle only plumbing (data structures), the optimal-benchmark **solve** (Hungarian, Phase 1), and analysis/plots. No elevator/dispatch "library" exists or is used.

### Dispatch ladder — five policies, increasing sophistication
| # | Policy | Implemented with | Source / reference |
|---|---|---|---|
| 1 | **Round-robin** | `itertools.cycle(elevators)` → `next()` | classic load-balancing |
| 2 | **Nearest-car (NCH)** | hand-written `min()` over the Figure-of-Suitability score | NCH "FS" formula: `FS=(N+2)−d` (toward, same dir), `(N+1)−d` (toward, opp), `1` (away) |
| 3 | **Zone-based** | hand-written: `max(source,dest) → zone` (of `n_zones=3`) → nearest car in zone | sectoring / group control |
| 4 | **Cost-function / ETA** | hand-written `min()` over `estimate_cost()` | modern Destination Dispatch |
| 5 | **Optimal batch (Hungarian)** *(Phase 1)* | `scipy.optimize.linear_sum_assignment`; each car replicated into `free_slots` columns → multi-request | Hungarian algorithm |

- Policies 2 and 4 are **greedy** (one request → its own row-min). Policy 5 solves the **whole** cost matrix optimally per tick — the *globally-optimal cousin of #4*, used to measure how far the greedy heuristics fall short. **Not** the implementation of #2/#4.
- **Capacity for #5 (chosen fix — column replication):** each car is replicated into `free_slots` columns, so one car can receive **multiple** requests per solve. `linear_sum_assignment` handles the rectangular matrix + duplicate columns **natively**; the policy internally keeps a `col_to_car` map, lets **unmatched** requests wait for the next tick, and uses large **finite** penalties (never `inf`) for forbidden pairings. Matrix is rebuilt each tick. All of this is **internal** to the Hungarian class — the `dispatch(pending, world)` signature is identical to the greedy policies.

### Motion policy
- **LOOK** and **FCFS-motion** — both **hand-written**. Each car's targets are a **`set[int]`**; LOOK picks the next stop with a `min()`/`max()` filter in the current sweep direction (`min(f for f in targets if f > current)` going up). **No heap** — at tens of floors an O(n) scan is negligible, and a set handles out-of-order removal cleanly (targets are served in any order).

### stdlib plumbing (no install)
| Tool | Role |
|---|---|
| `itertools.cycle` | *is* the round-robin mechanism (policy #1) |
| builtin `set` / `sorted` | `set[int]` targets for LOOK (next stop via `min()`/`max()` filter); `sorted()` for aging's oldest-first ordering — **no `heapq`** (unnecessary at tens of floors) |
| `dataclasses` | `Request`, `Passenger`, `Elevator` state |

### Third-party
| Library | Use | Required? |
|---|---|---|
| `scipy` | `linear_sum_assignment` — Hungarian dispatch (#5) | **yes** (Phase 1; excludable at run time if #5 dropped) |
| `numpy` | RNG (generator), metrics/array math | yes |
| `pandas` | metrics aggregation, experiment grid, results table | yes |
| `matplotlib` | the cliff / comparison / fairness plots | yes |

### Deliberately NOT used
- **`simpy`** (discrete-event framework) — the prompt wants a discrete-*time* tick loop, and rolling our own demonstrates the understanding being graded. Hand-written engine only.

---

## 9. Single-run metrics & outputs

*(Metrics computed for **one** simulation run. Cross-run aggregation over replications — mean ± SE — lives in §10 / `experiments.py`.)*

**Per passenger**: `wait_time`, `travel_time`, `total_time`.
**Aggregate (required)**: min / max / avg of wait and total.
**Additional (for observations)**:
- **Fairness / tail**: **max wait, p95 wait, p90 wait** — worst-case and near-worst-case wait times (standard latency-tail percentiles; capture starvation without an arbitrary threshold).
- **Efficiency**: **`total_distance`** = Σ of `|floor moves|` across all cars (total work — unambiguous, no "trip" needed); **`stops_made`** = count of door-open service events; avg elevator **utilization ρ** = fraction of ticks each car is busy (moving or dwelling) vs. idle, averaged across cars (empirical, measured from the sim); **throughput** = `passengers_delivered / total_ticks`.
- **Distribution shape**: histogram of total_time (reveals heavy tail under load).
- **Pooling effect** *(fairness-vs-efficiency bonus)*: **`distance-per-passenger`** = `total_distance / passengers_delivered` (**lower = better pooling**) and **`passengers-per-stop`** = `passengers_delivered / stops_made` (**higher = more consolidation**). Under CRN (same traces across policies), any difference is *purely* the policy's routing/pooling efficiency. The story: smarter dispatch → lower distance-per-passenger → lower ρ → lower wait. *(The theoretical link `λ_trip → ρ` lives in §13, not measured here; pooling is emergent — no batching window, see §7 note.)*

**Compute vs. save vs. render (separation of concerns):**
- **`metrics.py` computes** — returns `{per_passenger records, summary stats}`; **no file I/O, no plotting**.
- **`io/writers.py` saves** (behind a `ResultsWriter` interface) — Phase 2 reuses `CsvWriter`/JSON to write the averaged `summary_mean.json`; **no new adapter**, metrics/engine core **untouched**.
- **`plots.py` renders** — `plot_distributions(passengers)` draws histograms of **`wait_time`** and **`total_time`**, saved as PNG in the **same run-output folder** as `passengers.csv`. Called by `cli.py` (single run only). Phase 2 may add **optional** static mean-bar comparison plots (also `plots.py`). matplotlib lives only in `plots.py`, never in `metrics.py`.

**Files** (one run):
- `positions_log.csv` — one row per **tick**; positions of all elevators (KKR required).
- `passengers.csv` — one row per **passenger** (`id, source, dest, submit/pickup/dropoff ticks, wait, travel, total, elevator`); the granular source for distributions & percentiles.
- `summary_stats.json` + **console table** — aggregate metrics (min/max/avg, p90/p95/max wait, ρ).
- `distributions.png` — histograms of **`wait_time`** and **`total_time`** (rendered from `passengers.csv` by `plots.py`, saved beside it); the single-run "notable observation" artifact.

---

## 10. Testing & correctness (Phase 1)

Phase 1 validates the engine with **single runs** — **no grid, no replication** (that's §16). Two tiers:

**A. Correctness tests (~4 tiny deterministic hand cases)** — verify the engine *logic* is right (`tests/test_correctness.py`). **Run each case against all 5 dispatch policies** (+ both motions) so every policy is verified on the deterministic cases. **Pass/fail assertions only — no output files saved.**
1. Two passengers, same direction → should share one elevator.
2. Two passengers, opposite directions → handled without deadlock.
3. Capacity overflow → excess passenger bumped, waits (original clock), served on the car's next pass, no loss (see §2).
4. Edge: `source == dest` **skipped-with-warning** (§4); a request at a later tick is admitted correctly.
   *(Plus a few policy-specific asserts: round-robin rotates; nearest-car picks the closest.)*

**B. Smoke / demo runs (one per scheduler × pattern)** — **single runs, one seed, one representative λ.** **6 scheduler configs** (LOOK + {round-robin, nearest-car, zone-based, cost-function, Hungarian} + **FCFS-motion** baseline) **× 3 patterns = 18 runs.** Purpose:
- **Smoke-test** that every scheduler runs end-to-end without error;
- **Generate example outputs** for the README **"observations"** section;
- Let KKR see the tool run under different policies/patterns (incl. the FCFS→LOOK motion gap).

**Save outputs** to a demo folder for KKR to browse — one subfolder per run:
`outputs/demo/{pattern}__{motion}_{dispatch}/` → `positions_log.csv`, `passengers.csv`, `summary_stats.json`, `distributions.png`.
*(Optional: a tiny script collects the 18 `summary_stats.json` into one **illustrative** comparison CSV for the README — single-seed, no error bars; the rigorous version is §16.)*

All non-varying parameters use the **§12 confirmed defaults** (the office-building config: 16 cars / 25 floors / cap 10 / dwell 2 / λ=3 / age_weight 0.1); only **pattern × scheduler** vary.

Implementation: **generate one trace per pattern** (seed 42, §12 defaults) and run **all 6 schedulers on it** (mini-CRN → fair within-pattern comparison) → **3 traces, 18 runs**. Invoke `cli.py` in a tiny loop — **not** `experiments.py`. No replication, no aggregation, no error bars. *(`generator.py` in its simple single-trace mode is **Phase 1**; the CRN grid `experiments.py` is **Phase 2 / §16**.)*

> These are *illustrative* single runs. The **averaged study** (18 configs × 100 seeds, CRN, per-config mean summaries) is **Phase 2 → §16**.

---

## 11. Deliverables — Phase 1 (the Aug-9 submission)

The KKR-required submission. **Phase 1 only** — the Phase 2 replicated study (local mean summaries) is in §16.

- **Public GitHub repo** with the Python code (pure core + CLI + tests) and a **`requirements.txt`** (`scipy`, `numpy`, `pandas`, `matplotlib`) for clone-and-run.
- **README.md** containing:
  - **How to run:**
    - **A single sim with custom config** — `cli.py` (trace or generated input; choice of motion/dispatch + parameters, e.g. `--dispatch cost_function --lambda 4 --capacity 12 …`).
    - **The demo runs** — generate traces + run the **18 smoke configs** (6 schedulers × 3 patterns, §10-B) to reproduce the outputs / observations.
  - **Time spent.**
  - **Assumptions / simplifications / trade-offs** (see §2).
  - **What we'd improve with more time** (incl. the adaptive batching window, §13).
  - **Observations** — a short, caveated section from the §10-B smoke/demo runs (illustrative single runs; the averaged study is Phase 2, §16).
- **Example outputs** committed for one showcase run: `positions_log.csv`, `passengers.csv`, `summary_stats.json`, `distributions.png`.

*(Phase 2 — the local replicated experiment grid (`experiments.py` → mean summaries) — is in §16.)*

---

## 12. Milestones

> ✅ **Confirmed defaults** — models an office building: **~7,500 people, 25 floors, 16 elevators, morning up-peak rush**; time bridge **1 tick ≈ 2 sec** (30-min rush ≈ 900 ticks). Overridable via CLI; tune `λ` after measuring ρ (target **ρ ≈ 0.7–0.9**).
> - **System/building:** `n_elevators = 16`, `n_floors = 25`, `capacity = 10`, `dwell = 2`
> - **Initial state & engine:** all cars start at **floor 1 (lobby)**, state `IDLE`; dispatch tie-break = **lowest car id** (determinism); termination safety = **stall detector** (`4×n_floors + dwell + 20` ticks with no delivery) + hard cap `MAX_TICKS = last_arrival + 200 × n_floors`
> - **Workload:** `λ = 3`, `duration = 900`, `seed = 42`, `pattern = up_peak` *(smoke runs §10-B vary pattern over up_peak / down_peak / uniform)*
> - **Scheduler:** cost-function weights `w_dist=1.0, w_dir=2.0, w_load=0.5, w_eta=1.5`; `age_weight = 0.1` *(aging on, gentle)*; motion = LOOK
> - **Zone-based:** `n_zones = 3` (low / mid / high — ~8 floors, ~5 cars each); assign a request to the zone containing **`max(source, dest)`** (the non-lobby floor — robust across up/down/uniform), nearest car **within** the zone. **Hungarian penalty** = large finite constant
> - **Experiment (Phase 2 / §16):** `R = 100` replications · `base_seed = 42` · fixed λ (no sweep — a λ-sweep is optional further work)

1. **[P1] Models + generator** — `models.py` (`Request` / `Passenger` / `Elevator` / enums) + `generator.py` (simple single-trace: Poisson + OD, §5) → **generate + eyeball a sample office trace.** *(Models first — the generator produces `Request`s. Independent of the engine → clean starting point + a realistic test fixture.)*
2. **[P1] Engine core** — `engine.py` tick loop + **LOOK motion** + **round-robin dispatch** + `trace_loader.py` + `io/writers.py` (positions log) → run on **the sample trace *and* the prompt's 3-row example.** *(LOOK triggers the §7 review gate.)*
3. **[P1] Metrics + outputs** — `metrics.py` (wait/travel/total, percentiles, ρ, distance/pooling) + writers (`passengers.csv`, `summary_stats.json` + console table) + `plots.py` (wait & total histograms).
4. **[P1] Full dispatch ladder + tests** — **nearest-car, zone-based, cost-function, Hungarian** (all on LOOK) + **FCFS-motion** baseline + **aging** + `cli.py` + the ~4 correctness tests (§10-A). *(Each scheduler triggers a §7 review; now testable on the realistic trace where policies actually differ.)*
5. **[P1] Smoke/demo runs + README** — the 18 runs (§10-B) → example outputs + README (how-to-run, assumptions, observations). **→ completes the Aug-9 submission.**
6. **[P2 — §16] Experiment grid** — `experiments.py`: 100 seeds × 18 configs → average each metric → `summary_mean.json` per config (`outputs/experiment/`); **local, no dashboard**. + optional bonus (express elevators).

---

## 13. Conceptual framing (for the presentation / appendix)

This is an **online, capacity-constrained dispatch problem** — the same abstraction as load-balancing requests across a worker pool or routing orders to venues. The interesting engineering is that **servers are stateful and switching is costly**, so we separate **motion policy (LOOK)** from **dispatch policy (cost function)**.

- **Queueing lens**: model as **M/G/c**; utilization **ρ = λ/(cμ)**; wait ∝ **1/(1−ρ)** → nonlinear "cliff" as ρ→1. Variability (C² of service time) also drives wait (Pollaczek–Khinchine).
- **Levers**: lower ρ (pool / add capacity `c`), lower service variability (smoothing/slicing), raise `c`.
- **Core trade-off (this is the fairness-vs-efficiency bonus)**: pooling more riders per trip → fewer trips → lower **effective** `λ_trip` → lower ρ → lower queue wait (efficient), *but* concentrating flow can defer outliers (fairness cost). In **this** problem pooling is **instant grouping** — emergent from `capacity > 1` + the dispatch policy — matching *"immediately assigns."*
- **The adaptive batching window (out of scope, discuss as analysis)**: deliberately *holding* requests to accumulate more — pool more under high load, fire fast when idle (same physics as TCP Nagle, disk-I/O coalescing, DB group-commit). It further lowers ρ but *delays* assignment, so it sits **outside this problem's rules** ("immediately assigns"). Present it as the natural extension / "what I'd explore with more time," not as implemented behavior.
- **`λ_trip` explained** — the effective arrival rate of *trips* (elevator journeys): `λ_trip = λ_request / passengers-per-trip`.
  - *Why it matters:* in `ρ = λ/(cμ)` the "λ" should be the rate of **jobs the servers actually process**, and an elevator's unit of work is a **trip** (a *batch* of riders), not a single passenger — so `λ_trip`, not the raw request rate, is what drives ρ.
  - *Example* (`λ_request = 3` passengers/tick): good pooling ≈ 10 riders/trip → `λ_trip = 3/10 = 0.3` trips/tick; poor pooling ≈ 5/trip → `λ_trip = 3/5 = 0.6` — **double the trip demand → higher ρ → worse wait.** Same passenger rate, different trip demand: *that's the whole pooling insight in one variable.*
  - *Analytical only:* "trip" is fuzzy under continuous LOOK, so the sim **measures ρ directly** and uses `distance-per-passenger` for pooling (§9). `λ_trip` lives here to *explain why* pooling lowers ρ — it is **not** a computed metric.
- **Theory ↔ measurement bridge**: this framing *predicts*; the sim *measures*. ρ and the pooling effect surface directly in the runs (§9 metrics; §16 averaged study). The wait-vs-λ **cliff** would need a λ-sweep — noted as optional further work (§16.5). We never plug into a queueing formula to *run* the sim — we run it and *observe* the behavior the theory explains.

### Domain mappings (presentation hook — same math, three domains)
The elevator is a disguise for a whole class of online-dispatch problems. Leading with this shows you understand the problem *class*, not just this instance:

| Elevator | Load balancer | Order routing (trading) |
|---|---|---|
| passenger (origin → dest) | request / job | order (current → target position; **buy = up, sell = down**) |
| elevator (stateful, capacity) | server / worker | execution venue / channel (liquidity = capacity) |
| wait + travel | queue + service latency | execution latency ≈ **implementation shortfall** |
| pooling riders per trip | batching requests | **block trading / netting** |
| utilization cliff (ρ→1) | server saturation | venue congestion / market impact |

**The hook:** the elevator's *stateful, switching-costly* server is exactly what makes it richer than stateless load-balancing — and precisely like a real **order router**. Same queueing math (ρ, the cliff, pooling) in all three.

---

## 14. Open questions to raise with KKR (optional, shows rigor)

- Optimize for **average** latency or **tail/fairness**? (changes the algorithm)
- Is assignment strictly **irrevocable**, or is **re-dispatch** allowed?
- Expected **scale** (floors / elevators / request volume)?
- Any **failure-handling** expectation (elevator/server drops mid-trip)?

---

## 15. Roadmap (phased architecture)

**Guiding principle — pure core + adapters (hexagonal).** Build the **simulation engine + policies + metrics as an I/O-agnostic library** (input: a trace → output: metrics; no file/DB/UI dependency). Each phase is then just a different *adapter* around the same core — new phases are wrappers, not rewrites. **This decision is made in Phase 1.**

```
            ┌───────────────────────────────────────┐
            │  CORE (engine + policies + metrics)     │  ← never changes
            │  input: a trace  →  output: metrics     │
            └───────────────────────────────────────┘
                 ▲              ▲               ▲
          CSV in/out      experiments.py     Agent / live
          (Phase 1)       grid (Phase 2)     (Phase 3)
```

### Phase 1 — KKR deliverable (graded)
- Clean, self-contained, **clone-and-run**; CSV in / CSV+JSON out; **no DB, no UI**.
- Builds the **pure core** that Phases 2–3 reuse.
- This is what's evaluated — keep it focused and pristine.

### Phase 2 — Local replicated experiment grid (mean summaries)
> **Full spec: §16.** (This is the overview.)
- **What:** `experiments.py` runs the 18 smoke configs across **100 seeds**, averages each metric, and writes one `summary_mean.json` per config to `outputs/experiment/`.
- **Why:** turns the single-seed Phase-1 observations into robust averaged results — the policy comparison no longer hinges on one random trace.
- **Fully local** — no database, no dashboard, no deploy. Reuses the Phase-1 core (`generate → run_sim → compute`) unchanged; **no new adapters**.
- **Optional:** a combined comparison CSV / static mean-bar plots. **Further work:** a λ-sweep (the utilization cliff) and SE / error bars.

### Phase 3 — Live UI agent
- **Define "agent" first:** (A) *live-run controller* — pick config in the UI → run a sim live → stream progress → write to a `runs` table; or (B) *LLM agent* — natural language ("compare nearest-car vs cost-function under morning rush") → translate to an experiment config → run → report. (B) is a much larger scope (NL→config layer, orchestration, guardrails).
- **Keep live runs small/illustrative** — the Cloud container is resource-limited, so heavy runs stay precomputed; the live button does a short, lightweight sim that finishes in seconds and appends to the `runs` table.

### Repo strategy
- **Keep the KKR deliverable pristine.** The Phase-2 grid is small and local, so it can live in the **same repo** (`experiments.py` at the root, or under `/extras`, or a branch) — no companion repo needed. The reviewer still lands on the clean core; the grid is just one more script that reuses it.

---

## 16. Phase 2 — Local replicated experiment grid (mean summary)

Upgrades the single-seed Phase-1 observations into **averaged results** by running each config across many seeds and averaging — so the policy comparison isn't a fluke of one trace. **Fully local: no database, no dashboard, no deploy.** Builds on the Phase 1 core unchanged. **Not part of the Aug-9 submission.**

### 16.1 The grid (`experiments.py`)
- **Configs:** the same **18** as the smoke runs (§10-B) — 6 schedulers (5 dispatch on LOOK + FCFS-motion baseline) × 3 patterns.
- **Fixed workload:** λ=3, duration=900, office defaults (§12). *(Single λ — no λ-sweep in this scope; see §16.5.)*
- **Replications:** **R = 100** seeds; `base_seed = 42`.
- **Mini-CRN:** for each `(pattern, replication)` generate the trace **once** and run all 6 schedulers on it. Seed per `(pattern, replication)` via `default_rng([base_seed, PATTERN_ID[pattern], r])`.
- **Total:** 100 × 18 = **1,800 runs** (~15–25 min locally, single-threaded).

**The 6 schedulers** (motion fixed at LOOK; FCFS baseline shows the motion gap):
1. LOOK + Round-robin  2. LOOK + Nearest-car  3. LOOK + Zone-based
4. LOOK + Cost-function *(expected winner)*  5. LOOK + Hungarian *(ceiling)*  6. FCFS + Round-robin *(baseline)*

### 16.2 Aggregation → mean summary per config (Option A output)
- For each of the 18 configs, collect the 100 per-run summaries from `metrics.compute()` and **average every metric field** across the 100 runs.
- Write one **`summary_mean.json`** per config to `outputs/experiment/{pattern}__{motion}_{dispatch}/summary_mean.json`.
- **Same schema as `summary_stats.json`**, every value = the mean over 100 runs, plus `"n_replications": 100`. (Mean only — no SE for now.)
- Aggregation note: `avg` / `ρ` / throughput / pooling average cleanly; `p90`/`p95` = the typical tail; `min`/`max` = the typical best/worst (noisier).

### 16.3 Optional add-ons (not required)
- A combined **comparison CSV** (18 rows × key metrics) for quick side-by-side.
- Static **comparison plots** (matplotlib mean bars) via `plots.py`.

### 16.4 Architecture fit
`experiments.py` just loops the existing core: `generate → run_sim → compute` → accumulate → average → write. **No new adapters — `CsvWriter`/JSON reused, the metrics/engine core is untouched.** Runnable with `python experiments.py`; lives in the repo (or `/extras`).

### 16.5 Dropped vs. the original Phase-2 concept (all optional future work)
❌ Supabase (external storage) · ❌ Streamlit dashboard (deployed/interactive viz) · ❌ `SupabaseWriter` / secrets / companion deployed repo · ❌ the **λ-sweep** and `1/(1−ρ)` cliff study · ❌ SE / error bars.
