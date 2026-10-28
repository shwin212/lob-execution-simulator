"""Transparent price-time-priority displayed order book (one symbol per book).

Orders at each level are OrderedDict[order_id, remaining_shares]. The ITCH tape
names the resting order for modifications; incoming market orders are *not*
re-matched. The data feed reports their executions explicitly.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass
from typing import Optional

from .events import Event


@dataclass(slots=True)
class Order:
    order_id: int
    side: str
    price_ticks: int
    shares: int


class OrderBook:
    def __init__(self) -> None:
        self.orders: dict[int, Order] = {}
        self.bids: dict[int, OrderedDict[int, int]] = {}
        self.asks: dict[int, OrderedDict[int, int]] = {}
        self.message_count = 0
        self.executed_shares = 0

    def _levels(self, side: str) -> dict[int, OrderedDict[int, int]]:
        if side not in {"B", "S"}:
            raise ValueError(f"Unknown side {side!r}")
        return self.bids if side == "B" else self.asks

    def lookup(self, order_id: int) -> Optional[Order]:
        return self.orders.get(order_id)

    def orders_at(self, side: str, price_ticks: int) -> dict[int, int]:
        """FIFO snapshot for estimating quantity ahead of a hypothetical new quote."""
        return dict(self._levels(side).get(price_ticks, {}))

    def add(self, order_id: int, side: str, shares: int, price_ticks: int) -> None:
        if order_id in self.orders or shares <= 0 or price_ticks <= 0:
            raise ValueError(f"Invalid or duplicate add: {order_id}")
        level = self._levels(side).setdefault(price_ticks, OrderedDict())
        level[order_id] = shares
        self.orders[order_id] = Order(order_id, side, price_ticks, shares)

    def reduce(self, order_id: int, shares: int) -> None:
        order = self.orders[order_id]
        if shares <= 0 or shares > order.shares:
            raise ValueError(f"Invalid reduction of {shares} on {order_id} ({order.shares})")
        order.shares -= shares
        if order.shares == 0:
            self.delete(order_id)
        else:
            self._levels(order.side)[order.price_ticks][order_id] = order.shares

    def delete(self, order_id: int) -> None:
        order = self.orders.pop(order_id)
        levels = self._levels(order.side)
        level = levels[order.price_ticks]
        del level[order_id]
        if not level:
            del levels[order.price_ticks]

    def apply(self, event: Event) -> None:
        k = event.kind
        if k in {"A", "F"}:
            self.add(event.order_id, event.side, event.shares, event.price_ticks)
        elif k in {"E", "C", "X"}:
            self.reduce(event.order_id, event.shares)
            if k in {"E", "C"}:
                self.executed_shares += event.shares
        elif k == "D":
            self.delete(event.order_id)
        elif k == "U":
            # ITCH replace always loses its previous time priority and gets a new ID.
            old = self.orders[event.order_id]
            side = old.side
            self.delete(event.order_id)
            self.add(event.new_order_id, side, event.shares, event.price_ticks)
        self.message_count += 1

    def best_bid(self) -> Optional[int]:
        return max(self.bids) if self.bids else None

    def best_ask(self) -> Optional[int]:
        return min(self.asks) if self.asks else None

    def midpoint_ticks(self) -> Optional[float]:
        bid, ask = self.best_bid(), self.best_ask()
        return (bid + ask) / 2 if bid is not None and ask is not None else None

    def level_qty(self, side: str, price: int) -> int:
        return sum(self._levels(side).get(price, {}).values())

    def top(self, depth: int = 5) -> dict:
        def side_top(side: str) -> list[dict[str, int]]:
            prices = sorted(self._levels(side), reverse=(side == "B"))[:depth]
            return [{"price_ticks": p, "shares": self.level_qty(side, p)} for p in prices]
        return {"bids": side_top("B"), "asks": side_top("S"),
                "live_orders": len(self.orders), "events": self.message_count,
                "executed_shares": self.executed_shares}

    def sweep(self, aggressor: str, requested: int) -> tuple[int, float, list[tuple[int, int]]]:
        """Hypothetical market order against visible *snapshot* depth.

        Does NOT mutate the historical book: a counterfactual replay with zero
        market impact, so this should not be described as executable liquidity.
        """
        if aggressor not in {"B", "S"} or requested <= 0:
            raise ValueError("Expected buy/sell aggressor and positive size")
        opposing = self.asks if aggressor == "B" else self.bids
        prices = sorted(opposing, reverse=(aggressor == "S"))
        remaining = requested
        slices = []
        for p in prices:
            size = min(remaining, self.level_qty("S" if aggressor == "B" else "B", p))
            if size:
                slices.append((p, size))
                remaining -= size
            if remaining == 0:
                break
        qty = requested - remaining
        avg_price = sum(p * q for p, q in slices) / qty if qty else 0.0
        return qty, avg_price, slices

    def assert_consistent(self) -> None:
        seen = set()
        for side, levels in (("B", self.bids), ("S", self.asks)):
            for price, queue in levels.items():
                assert queue and price > 0
                for oid, qty in queue.items():
                    assert oid not in seen and qty > 0
                    seen.add(oid)
                    order = self.orders[oid]
                    assert (order.side, order.price_ticks, order.shares) == (side, price, qty)
        assert seen == set(self.orders)
