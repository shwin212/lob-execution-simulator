# Verified local smoke-test output (synthetic data only)

Data: `sample/demo.csv` / `sample/demo.itch.gz`, deterministic seed 7,
5,000 normalized messages, one fictional symbol `DEMO`.

On the development environment used for this repository:

- `pytest`: **12 passed**.
- Binary ITCH -> normalized CSV round-trip: **5,000 matching events**.
- Python and C++ replay: **top-five bid/ask state, event count, live order
  count, and executed volume matched**.
- 5-run median replay wall time, 5,000 events: Python **18.191 ms**;
  C++ **4.471 ms**; ratio **4.069×**, including C++ executable startup.
- Market-making, three chronological holdout folds: simulated quote share
  fill rates **27.10%, 28.54%, 22.50%** with a 3ms latency input and a
  150-share inventory cap.
- VWAP-style schedule: fills of **250/250**, **225/250**, and **235/250**
  shares across the same three disjoint holdout blocks.

**These numbers are only demonstration checks**, not a strategy performance
study. They are sensitive to a deliberately simplified synthetic order-flow
model, zero-impact fill assumptions, the CPU, Python interpreter, cache state,
compiler and runtime. In particular they **do not confirm** 12M real NASDAQ
ITCH messages, any historical trading return, or a 6× C++ speedup.

To verify the current environment, regenerate the synthetic sample and run:

```bash
pytest -q
lob-sim backtest --input sample/demo.csv --strategy maker
lob-sim backtest --input sample/demo.csv --strategy vwap
make benchmark
```
