# Phase 1 — Implementation Checklist

**Execution tracker for the Aug-9 submission.** This is the *do-this-next* playbook; the **design lives in `PLAN.md`** (referenced as `→ §X`), config in `default_config.md`, dispatch details in `dispatch_policy_summary.md`. Check boxes off as you go; each milestone has a **DONE WHEN** acceptance test.

> **Gates:** every scheduler (motion *and* dispatch) needs a **manual review of the algorithm logic before it's "done"** (`PLAN §7`). All parameters come from the **§12 confirmed defaults** (office building: 16 cars / 25 floors / cap 10 / dwell 2 / λ=3 / up-peak / `age_weight=0.1` / `n_zones=3`).

---

## Setup (before M1)
- [x] `venv` + `requirements.txt` — `scipy`, `numpy`, `pandas`, `matplotlib` (Python 3.14, all installed in `.venv`)  → `§8`, `§11`
- [x] Package skeleton per `→ §3` (created incrementally as built):
  ```
  elevator_sim/{models.py, engine.py, metrics.py, plots.py, cli.py,
                motion/{base,look,fcfs}.py,
                dispatch/{base,round_robin,nearest_car,zone_based,cost_function,hungarian,aging}.py,
                io/{base,writers,trace_loader,generator}.py}
  tests/  •  outputs/  •  README.md
  ```
- **DONE WHEN:** `python -c "import elevator_sim"` works in the venv.

---

## M1 — Models + generator ✅
*Build the input producer first → a realistic test fixture for everything after.*
- [x] `models.py` — `Request` (frozen; id, submit_tick, source, dest), `Passenger` (wraps Request + pickup/dropoff/assigned; derived wait/travel/total/state), `Elevator` (id, floor, direction, state, capacity, onboard, **targets: set[int]**, dwell_remaining, is_full/free_slots), enums `Direction` / `ElevatorState` / `PassengerState`  → `§3`
- [x] `io/generator.py` — per-tick `rng.poisson(λ)` arrivals + OD by pattern (`rng.integers`); returns `list[Request]`; `to_csv()` helper; stable `PATTERN_ID`  → `§5`, defaults `§12`
- [x] Generated a sample **up-peak** office trace (seed 42) → `outputs/samples/up_peak_l3_s42.csv`
- **DONE ✅:** 2708 reqs (~λ·duration); source==1 (lobby), dest 2–25, no source==dest, floors in [1,25]; arrivals/tick mean 3.01 max 9 (Poisson); reproducible (same seed → identical).

---

## M2 — Engine core ✅ (LOOK + round-robin reviewed by user)
- [x] `motion/base.py` (`MotionPolicy` ABC) + `motion/look.py` (LOOK sweep, set+min/max next-stop) — **✅ REVIEWED**  → `§6`, `§7`, `§8`
- [x] `dispatch/base.py` (`DispatchPolicy` ABC, `dispatch(pending, world)`) + `dispatch/round_robin.py` (`itertools.cycle`) — **✅ REVIEWED**
- [x] `engine.py` — tick loop: log→admit→dispatch→service(board/alight, dwell)→move; `last_arrival` termination + **stall detector** + hard cap `last_arrival + 50×n_floors`  → `§6`
- [x] `io/trace_loader.py` — CSV → `list[Request]`, skip-and-warn validation  → `§4`
- [x] `io/base.py` (`ResultsWriter` ABC) + `io/writers.py` — positions_log.csv (Convention A)  → `§9`
- [x] `config.py` — `SystemConfig` dataclass
- **DONE ✅:** 3-row example → all 3 delivered (correct wait/travel/total); office trace (16/25/up-peak/λ=3) → **all 2708 delivered, drained @1155 ticks in 0.21s**, deterministic, positions_log Convention A verified.
- **DEVIATION (resolved):** fixed `10×n_floors` cap was too tight for heavy-load drain → now **stall detector** (primary) + **`50×n_floors` hard cap** (backstop). §6 & §12 updated to match.

---

## M3 — Metrics + outputs ✅
- [x] `metrics.py` — per-passenger + aggregate (min/max/avg, p90/p95 wait, ρ, throughput, total_distance, stops, distance-per-passenger, passengers-per-stop). **Compute only.**  → `§9`
- [x] engine efficiency counters (total_distance, stops_made, busy_ticks) added to `RunResult`
- [x] `io/writers.py` — `passengers.csv` + `summary_stats.json` + `format_console_table` (ASCII, Windows-safe)  → `§9`
- [x] `plots.py` — `plot_distributions()` → wait & total histograms PNG (matplotlib ONLY here, `Agg` backend)  → `§9`
- **DONE ✅:** office run prints console table + writes all 4 files; summary_stats.json matches §9 schema (self-describing). **⚠ measured ρ = 0.96** under round-robin (near cliff — see note; λ tuning is a user decision).

---

## M4 — Full dispatch ladder + tests ✅
*Now the schedulers can be watched differing on the realistic trace.*
- [x] `dispatch/nearest_car.py` — NCH FS formula + committed-load tie-break — **✅ REVIEWED**  → `§8`, dispatch summary
- [x] `dispatch/zone_based.py` — `n_zones=3`, zone by `max(source,dest)`, nearest+committed within bank — **✅ REVIEWED**
- [x] `dispatch/cost_function.py` — weighted `min` (dist/dir/committed-load/eta) + `committed_loads` helper — **✅ REVIEWED**
- [x] `dispatch/hungarian.py` — `linear_sum_assignment` + column-replication + committed load — **✅ REVIEWED**
- [x] `motion/fcfs.py` — arrival-order baseline + `is_full` deadlock guard — **✅ REVIEWED**
- [x] `dispatch/aging.py` — `Aged` wrapper (oldest-first ordering); **provably ~no-op under immediate+irrevocable greedy dispatch** (documented; re-dispatch = §14 activation path)
- [x] `cli.py` + `__main__.py` — single run, `--motion/--dispatch/--lambda/--capacity/...` + `--input`/`--generate` + `--plot`  → `§11`
- [x] `tests/test_correctness.py` — 7 tests (5 policies × 2 motions deliver-consistent + pooling/opposite/overflow/loader/round-robin/nearest-car) — **all pass**
- **DONE ✅:** all 5 dispatch + FCFS run via CLI; 7 correctness tests pass. **2 bugs found+fixed by testing** (concentration → committed-load; FCFS deadlock → is_full guard). **Key finding:** peak favors round-robin, interfloor favors smart policies (8× on uniform).

---

## M5 — Smoke/demo runs + README → **Aug-9 submission** ✅
- [x] `run_demo.py` — 1 trace per pattern (seed 42), all 6 schedulers on it (mini-CRN) → **18 runs** → `outputs/demo/{pattern}__{motion}_{dispatch}/`  → `§10-B`
- [x] `outputs/demo/comparison.csv` — the 18 summaries collected into one illustrative table
- [x] `README.md` — quick start, CLI usage, model, policies, **observations** (the peak-vs-interfloor finding + comparison table), assumptions, what-I'd-improve, testing, structure  → `§11`
- [x] `requirements.txt`, `.gitignore`; example outputs committed (`outputs/demo/`)
- [x] **Time spent** — placeholder in README for the user to fill in
- **DONE ✅:** 18 demo folders populated (4 files each); comparison.csv written; README complete; 7/7 tests pass; `python -m elevator_sim` + `python run_demo.py` both work. **→ ready to submit (once user fills time-spent + `git init` + push).**

---

## M6 — [Phase 2, NOT Aug-9] Local experiment grid
`experiments.py`: 100 seeds × 18 configs (mini-CRN) → average each metric → `summary_mean.json` per config in `outputs/experiment/`. Local, mean-only, no dashboard.  → **`§16`** (own checklist when we get there).

---

## Progress
- [x] M1  [x] M2  [x] M3  [x] M4  [x] M5   → **✅ PHASE 1 COMPLETE**
