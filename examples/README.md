# Example input trace

`sample_trace.csv` is a synthetic trace generated with the **default config**
(up-peak traffic, λ = 3 arrivals/tick, 25 floors, 900-tick arrival window, seed 42) —
**2708 requests** in the input contract format:

```
time,id,source,dest
0,passenger1,1,16
0,passenger2,1,6
...
```

## Run the simulator against it

```bash
python -m elevator_sim --input examples/sample_trace.csv --dispatch cost_function --plot
```

The trace is fully reproducible from its seed, so you don't actually need this file —
it's here as a ready-to-run example. To regenerate it in code:

```python
from elevator_sim.io.generator import generate, to_csv
to_csv(generate("up_peak", 3, 25, 900, seed=42), "examples/sample_trace.csv")
```
