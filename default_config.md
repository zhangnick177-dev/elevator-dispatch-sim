# Default Configuration

The default parameter values for the simulation, with the reasoning behind each. Companion to `PLAN.md` §12 (which lists them) and §5/§6/§7 (which define them). These are the values the **smoke/demo runs (§10-B)** and any **single run** use unless overridden via CLI.

> **Modeling target:** a real office building — **~7,500 people, 25 floors, 16 elevators, morning up-peak rush.**

---

## The time bridge: 1 tick ≈ 2 seconds

The model is abstract (`1 tick = 1 floor of travel`). To map it to the real building we assume a mid-speed elevator does ~1 floor per **~2 seconds**, so:

- **1 tick ≈ 2 sec** → 1 min ≈ 30 ticks → a **30-min morning rush ≈ 900 ticks**.
- A full 25-floor trip ≈ 25 ticks ≈ 50 sec (realistic).

Everything time-related (`λ`, `duration`, `dwell`, `MAX_TICKS`) is derived through this bridge.

---

## The defaults (grouped by bucket)

```python
DEFAULTS = {
    "system":   {"n_elevators": 16, "n_floors": 25, "capacity": 10, "dwell": 2},
    "workload": {"lambda": 3, "duration": 900, "seed": 42, "pattern": "up_peak"},
    "cost_weights": {"w_dist": 1.0, "w_dir": 2.0, "w_load": 0.5, "w_eta": 1.5},
    "age_weight": 0.1,
    "engine":   {"init_floor": 1, "init_state": "IDLE",
                 "tie_break": "lowest_car_id", "max_ticks": "last_arrival + 10*n_floors"},
}
```

### System / building
| Param | Value | Why |
|---|---|---|
| `n_elevators` | **16** | given (the building) |
| `n_floors` | **25** | given (the building) |
| `capacity` | **10** | typical mid-size passenger car (range 8–20; 13 felt too high) |
| `dwell` | **2** | ~4 sec door dwell per stop ÷ 2 sec/tick ≈ 2 ticks |

### Workload
| Param | Value | Why |
|---|---|---|
| `pattern` | **up_peak** | the morning scenario (lobby → upper floors). *Smoke runs (§10-B) vary this over up_peak / down_peak / uniform.* |
| `duration` | **900** | the 30-min rush window (900 ticks) |
| `seed` | **42** | fixed for reproducibility |
| **`λ`** | **3** | see derivation below |

### Scheduler
| Param | Value | Why |
|---|---|---|
| motion | **LOOK** | fixed (low-leverage, near-solved) |
| dispatch | *(varies)* | the 5 policies — smoke runs sweep them |
| cost weights | `w_dist=1.0, w_dir=2.0, w_load=0.5, w_eta=1.5` | provisional; tunable (weight grid-search = further work) |
| `age_weight` | **0.1** | aging **on but gentle** (mild tail-reducer; ~10 ticks of wait ≈ 1 floor of preference). `0` = off, `1` = moderate. |
| `n_zones` | **3** | low/mid/high (~8 floors, ~5 cars each); assign by zone of `max(source,dest)`, nearest car within zone — robust across up/down/uniform |
| Hungarian penalty | large finite constant | for forbidden pairings — **never** `inf` (scipy infeasibility) |

### Initial state & engine
| Param | Value | Why |
|---|---|---|
| **initial position** | **all cars at floor 1 (lobby)** | realistic for a morning up-peak (cars idle at the lobby before the rush); simplest |
| initial state | `IDLE` | nothing assigned at t=0 |
| **dispatch tie-break** | **lowest car id** | deterministic → reproducible (two cars with equal cost) |
| **`MAX_TICKS`** | **`last_arrival + 10 × n_floors`** | §6 safety cap — a non-draining sim (starvation bug) raises/warns instead of hanging |

---

## λ derivation (the crux)

`λ` is arrivals per tick — the one parameter that isn't read straight off the building.

**Demand (morning rush):** ~60% of the 7,500 population arrives over the 30-min window → ~4,500 people / 900 ticks ≈ **5 req/tick** at full peak.

**Service capacity (capacity = 10):** one up-peak round trip per car ≈
- up to the highest destination (~24 floors) = ~24 ticks + ~8 stops × 2 dwell (16) ≈ **40 ticks**
- return express (empty) ≈ 24 ticks
- round trip ≈ **64 ticks**, delivering ~10 people → ~**0.16 people/tick per car**
- × 16 cars → **~2.5–4 people/tick** total capacity (higher end with good pooling).

**Conclusion:** full peak (λ=5) would **overwhelm** capacity 10 (ρ ≈ 1.5–2). To sit in the **busy-but-stable band (ρ ≈ 0.7–0.9)** where the scheduler matters, **λ = 3**.

| λ | ρ (approx) | regime |
|---|---|---|
| 2 | ~0.6 | comfortable |
| **3** | **~0.8** | **busy rush ← default** |
| 4 | ~0.9+ | near the cliff |
| 5+ | ≥1 | overwhelmed (queues explode) |

---

## The honest validator: measured ρ

All the above is back-of-envelope. **The real check is the ρ the sim reports** (§9, `utilization_rho`):

- **ρ ≈ 0.7–0.9** → realistic busy rush ✅
- **ρ ≥ 1** → overwhelmed; **lower λ**
- **ρ ≈ 0.3** → over-provisioned; **raise λ**

Workflow: run once with the defaults → read ρ → nudge `λ` into the band. That's how the config is *confirmed* against reality, since ρ is measured, not assumed.

---

## How the defaults are consumed

- Encoded as a `DEFAULTS` config (dataclass defaults / dict).
- **Single runs / smoke runs** use them; **CLI overrides** any (`--lambda 4 --capacity 12 …`) so KKR can experiment.
- **Smoke runs (§10-B)** hold all defaults fixed and vary only **pattern × scheduler** (18 runs).
- **Phase 2 grid (§16)** replicates the same 18 configs across **`R = 100` seeds** (`base_seed = 42`) at **fixed λ**, and averages each metric into `summary_mean.json` per config. (A λ-sweep is optional further work.)
