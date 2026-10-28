"""Counterfactual fill models. These are backtests, not exchange emulation.

Latency is measured exchange timestamp -> first processed event after requested
arrival. Hypothetical orders do not change the historical feed or queue.
"""
from __future__ import annotations

from bisect import bisect_left
from dataclasses import asdict, dataclass
from typing import Iterable

from .book import OrderBook
from .events import Event, usd


@dataclass
class PassiveQuote:
    side: str
    price_ticks: int
    remaining: int
    ahead: dict[int, int]


@dataclass
class Fill:
    ts_ns: int
    side: str
    shares: int
    price_ticks: int
    midpoint_ticks: float
    fee_usd: float


def maker_statistics(fills: list[Fill], mids: list[tuple[int, float]],
                     posted_shares: int, cash: float, inventory: int,
                     realized_spread_horizon_ns: int = 250_000_000) -> dict:
    """Weighted realized spread, adverse selection, and mark-to-market in bps."""
    last_mid = mids[-1][1] if mids else None
    total_fill = sum(f.shares for f in fills)
    trades = []
    timestamps = [t for t, _ in mids]
    for f in fills:
        at = bisect_left(timestamps, f.ts_ns + realized_spread_horizon_ns)
        if at >= len(mids) or f.midpoint_ticks <= 0:
            continue
        future_mid = mids[at][1]
        direction = 1 if f.side == "B" else -1
        # Maker realized spread positive when future mid is favorable vs execution.
        spread_bps = 20_000 * direction * (future_mid - f.price_ticks) / f.midpoint_ticks
        # Positive adverse selection means midpoint moved against maker after fill.
        selection_bps = 10_000 * direction * (f.midpoint_ticks - future_mid) / f.midpoint_ticks
        trades.append((f.shares, spread_bps, selection_bps))

    def wavg(index: int) -> float | None:
        qty = sum(row[0] for row in trades)
        return round(sum(row[0] * row[index] for row in trades) / qty, 4) if qty else None

    return {
        "fills": len(fills), "filled_shares": total_fill,
        "posted_shares": posted_shares,
        "fill_rate": round(total_fill / posted_shares, 6) if posted_shares else 0,
        "inventory_shares": inventory,
        "cash_usd": round(cash, 4),
        "mtm_pnl_usd": round(cash + inventory * usd(last_mid), 4) if last_mid else None,
        "realized_spread_bps": wavg(1),
        "adverse_selection_bps": wavg(2),
        "spread_horizon_ms": realized_spread_horizon_ns / 1e6,
        "spread_eligible_shares": sum(row[0] for row in trades),
    }


class MarketMaker:
    def __init__(self, *, clip: int = 30, max_inventory: int = 150,
                 latency_ms: float = 3, refresh_ms: float = 200,
                 maker_fee_per_share: float = -0.001) -> None:
        if clip <= 0 or max_inventory <= 0 or latency_ms < 0 or refresh_ms <= 0:
            raise ValueError("Invalid market-maker parameters")
        self.clip, self.max_inventory = clip, max_inventory
        self.latency_ns = round(latency_ms * 1e6)
        self.refresh_ns = round(refresh_ms * 1e6)
        self.fee_per_share = maker_fee_per_share
        self.quotes: dict[str, PassiveQuote] = {}
        self.fills: list[Fill] = []
        self.mids: list[tuple[int, float]] = []
        self.inventory = 0
        self.cash = 0.0
        self.posted_shares = 0
        self.next_refresh_ns = -1
        self.pending_refresh_ns: int | None = None

    def _refresh(self, book: OrderBook) -> None:
        # Existing orders stay live until the replacement instruction arrives.
        self.quotes.clear()
        bid, ask = book.best_bid(), book.best_ask()
        if bid is None or ask is None or bid >= ask:
            return
        for side, price in (("B", bid), ("S", ask)):
            if side == "B":
                size = min(self.clip, self.max_inventory - self.inventory)
            else:
                size = min(self.clip, self.max_inventory + self.inventory)
            if size <= 0:
                continue
            self.quotes[side] = PassiveQuote(side, price, size, book.orders_at(side, price))
            self.posted_shares += size

    def _observe_execution(self, event: Event, book: OrderBook, midpoint: float | None) -> None:
        if event.kind in {"A", "F"}:
            return
        old = book.lookup(event.order_id)
        if old is None:
            return
        removed = old.shares if event.kind in {"D", "U"} else event.shares
        for quote in self.quotes.values():
            if quote.price_ticks != old.price_ticks or quote.side != old.side:
                continue
            if event.order_id in quote.ahead:
                # Exact original queue IDs are tracked, rather than crediting
                # cancellations of newly-added orders behind our own quote.
                left = quote.ahead[event.order_id] - removed
                if left <= 0:
                    del quote.ahead[event.order_id]
                else:
                    quote.ahead[event.order_id] = left
            elif not quote.ahead and event.kind in {"E", "C"} and quote.remaining:
                qty = min(event.shares, quote.remaining)
                side_is_buy = quote.side == "B"
                if side_is_buy:
                    qty = min(qty, self.max_inventory - self.inventory)
                else:
                    qty = min(qty, self.max_inventory + self.inventory)
                if qty <= 0:
                    continue
                quote.remaining -= qty
                fee = qty * self.fee_per_share
                self.inventory += qty if side_is_buy else -qty
                self.cash += (-(qty * usd(quote.price_ticks)) if side_is_buy
                              else qty * usd(quote.price_ticks)) - fee
                self.fills.append(Fill(event.ts_ns, quote.side, qty, quote.price_ticks,
                                       midpoint if midpoint is not None else float(quote.price_ticks), fee))

    def run(self, events: Iterable[Event], book: OrderBook | None = None) -> dict:
        book = book or OrderBook()
        for event in events:
            before_mid = book.midpoint_ticks()
            self._observe_execution(event, book, before_mid)
            book.apply(event)
            mid = book.midpoint_ticks()
            if mid is not None:
                self.mids.append((event.ts_ns, mid))
            # Activation occurs after processing the first event at or beyond
            # the latency deadline: conservative discretization on the feed.
            if self.pending_refresh_ns is not None and event.ts_ns >= self.pending_refresh_ns:
                self._refresh(book)
                self.pending_refresh_ns = None
            if self.pending_refresh_ns is None and event.ts_ns >= self.next_refresh_ns:
                self.pending_refresh_ns = event.ts_ns + self.latency_ns
                self.next_refresh_ns = event.ts_ns + self.refresh_ns
        return maker_statistics(self.fills, self.mids, self.posted_shares,
                                self.cash, self.inventory)


def estimate_volume_profile(events: list[Event], buckets: int = 12) -> list[float]:
    """Learn a relative intrawindow volume curve using *training events only*."""
    if buckets < 1:
        raise ValueError("buckets must be positive")
    vols = [0] * buckets
    if not events:
        return [1 / buckets] * buckets
    start = events[0].ts_ns
    span = max(1, events[-1].ts_ns - start)
    for event in events:
        if event.kind in {"E", "C"}:
            i = min(buckets - 1, int((event.ts_ns - start) * buckets / span))
            vols[i] += event.shares
    total = sum(vols)
    return [v / total for v in vols] if total else [1 / buckets] * buckets


def vwap_backtest(events: list[Event], book: OrderBook, profile: list[float],
                  target: int = 250, side: str = "B",
                  taker_fee_per_share: float = 0.003) -> dict:
    """Out-of-sample VWAP schedule from a previously trained volume profile.

    Slices are hypothetical sweeps of displayed snapshots, with no market
    impact, signaling, hidden liquidity, or order-routing decisions. Taker
    fills are therefore optimistic upper bounds rather than achievable fills.
    """
    if target <= 0 or side not in {"B", "S"} or not profile or any(v < 0 for v in profile):
        raise ValueError("Invalid VWAP backtest parameters")
    if not events:
        return {"filled_shares": 0, "target_shares": target, "fill_rate": 0}
    weights = [v / sum(profile) for v in profile] if sum(profile) else [1 / len(profile)] * len(profile)
    start, end = events[0].ts_ns, events[-1].ts_ns
    span = max(1, end - start)
    next_bucket = 0
    filled = 0
    cost_ticks_shares = 0.0
    benchmark_ticks_shares = 0.0
    bench_qty = 0
    trade_count = 0
    arrival_mid = book.midpoint_ticks()
    for event in events:
        old = book.lookup(event.order_id) if event.kind in {"E", "C"} else None
        if old is not None:
            benchmark_ticks_shares += event.shares * (
                event.trade_price_ticks if event.kind == "C" and event.trade_price_ticks
                else old.price_ticks)
            bench_qty += event.shares
        book.apply(event)
        if arrival_mid is None:
            arrival_mid = book.midpoint_ticks()
        bucket_due = min(len(weights) - 1, int((event.ts_ns - start) * len(weights) / span))
        while next_bucket <= bucket_due:
            scheduled_total = round(target * sum(weights[:next_bucket + 1]))
            to_buy = max(0, min(target - filled, scheduled_total - filled))
            if to_buy:
                qty, avg, _ = book.sweep(side, to_buy)
                filled += qty
                cost_ticks_shares += qty * avg
                trade_count += bool(qty)
            next_bucket += 1
    avg_ticks = cost_ticks_shares / filled if filled else None
    reference_vwap = benchmark_ticks_shares / bench_qty if bench_qty else None
    direction = 1 if side == "B" else -1
    slippage_bps = (10_000 * direction * (avg_ticks - reference_vwap) / reference_vwap
                    if reference_vwap and avg_ticks else None)
    return {"strategy": "trained_volume_profile_vwap", "side": side,
            "target_shares": target, "filled_shares": filled,
            "fill_rate": round(filled / target, 6), "child_fills": trade_count,
            "execution_vwap_usd": round(usd(avg_ticks), 6) if avg_ticks else None,
            "market_print_vwap_usd": round(usd(reference_vwap), 6) if reference_vwap else None,
            "implementation_shortfall_vs_print_vwap_bps": round(slippage_bps, 4) if slippage_bps is not None else None,
            "arrival_mid_usd": round(usd(arrival_mid), 6) if arrival_mid else None,
            "taker_fees_usd": round(filled * taker_fee_per_share, 4),
            "model": "counterfactual_snapshot_no_market_impact"}


def walk_forward(events: list[Event], strategy: str = "maker", folds: int = 3,
                 **params: object) -> list[dict]:
    """Expanding training history and disjoint evaluation blocks.

    Each fold replays all preceding messages for state warmup. For VWAP,
    volume profile learned from the past only; for maker, parameters fixed,
    *not tuned* on the past. No return is an estimate of future profitability.
    """
    if len(events) < 2 * (folds + 1) or folds <= 0:
        raise ValueError("Need more events than the number of folds")
    chunk = len(events) // (folds + 1)
    reports = []
    for i in range(1, folds + 1):
        start = i * chunk
        stop = len(events) if i == folds else (i + 1) * chunk
        train, test = events[:start], events[start:stop]
        book = OrderBook()
        for e in train:
            book.apply(e)
        if strategy == "maker":
            model = MarketMaker(**params)
            report = model.run(test, book)
        elif strategy == "vwap":
            profile = estimate_volume_profile(train)
            report = vwap_backtest(test, book, profile, **params)
        else:
            raise ValueError("strategy must be maker or vwap")
        report.update({"fold": i, "warmup_events": len(train),
                       "test_events": len(test), "test_first_ts_ns": test[0].ts_ns,
                       "test_last_ts_ns": test[-1].ts_ns})
        reports.append(report)
    return reports


def fills_as_dicts(fills: list[Fill]) -> list[dict]:
    return [asdict(fill) for fill in fills]
