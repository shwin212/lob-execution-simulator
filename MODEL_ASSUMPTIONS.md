# Model assumptions and limitations

## Data / book reconstruction

- Read complete exchange-day BinaryFILE ITCH 5.0 input from the beginning.
- Implemented book-changing message kinds: `A`, `F`, `E`, `C`, `X`, `D`, `U`.
- `C` reduces displayed quantity at the *order's displayed limit price*, even
  when its trade-price field differs. Actual trade price is retained separately.
- Other messages are ignored (including non-display trades, crosses, trading
  halts, auction-related feeds, and broken-trade corrections). Thus this is a
  **displayed continuous book**, not a complete consolidated exchange view.
- Price integers are 1/10000 USD and timestamp units are ns since midnight.
- ITCH order references are unique within each day; feed is assumed to arrive
  in order, complete, with no dropped messages and no day mixing.
- Symbol filter uses `A/F` stock name to track reference IDs, not a separate
  stock-locate directory. This is sufficient when replaying from the start.
- `OrderBook` reconstructs queue priority but does not infer hidden executions.

## Fill simulation / causal correctness

- **Counterfactual, zero market impact:** simulated orders never alter the
  historical order book or incoming ITCH executions.
- Passive quotes join the back of observed orders at the same price, with
  those order IDs explicitly tracked as queue-ahead. Once all original ahead
  orders are removed, subsequently observed executions of orders added *after*
  quote activation are treated as opportunity for a simulated fill.
- This rests on aggressive assumptions about hidden liquidity, order routing,
  matches, and whether hypothetical inserts would change observed events;
  estimated fills are not proof an order could have traded.
- Queue-ahead cancellations from IDs added *after* quote activation do not
  earn queue credit. Resting canceled agents remain live until refresh arrives.
- Signal latency is approximated to the first feed event after the requested
  deadline, with activation after that event (conservative discretization).
- Market maker refresh is a fixed cadence. Bid/ask sizes honor inventory cap.
  Partial quote fills are supported. No exchange timestamps for own orders.
- Fees are a configurable per-share input, not venue-specific tiered rates.
- Inventory is marked to the **final observed midpoint**, not liquidated.
- Realized spread uses the midpoint at the *first* observation at or after the
  chosen horizon. Points without enough future history are excluded.
- VWAP profile comes solely from training-window trade volume, then is applied
  across the holdout window. Normalized time-window shapes are a simplification
  and should be replaced with time-of-day profiles from historical prior days.
- VWAP child slices sweep the contemporaneous displayed snapshot, without
  mutating it. Multiple slices can overcount liquidity. It does *not* model
  queueing, market impact, signaling, routing, nor fill probability.
- Train/test folds are chronological and non-overlapping on evaluation; order
  book is warmed with every message before the holdout. Maker parameters are
  held fixed, not optimized; do not call the procedure parameter tuning.

## What the benchmark actually measures

- Replay correctness is checked by comparing C++ and Python top five bid/ask
  levels, live orders, total events, and executed shares.
- Reported speedups are **measured live** on normalized CSV and include CSV
  parsing, process startup for C++, and Python consistency assertions. They
  do not establish speedup on binary ITCH parsing or prove a 6x result.
- For a defensible result: use independently sourced, permissioned data;
  multiple trading days and symbols; pin CPU/runtime/compiler, warm caches,
  report p50/p95, include complete-message and book-depth parity checks.

## Reproducibility

- Only Python standard library is needed to run the core code.
- CI tests verify parser round-trip, queue semantics, strategy constraints,
  and Python/C++ replay parity using deterministic synthetic data.
- Demo is explicitly synthetic and does not support profitability or historical
  return claims.
