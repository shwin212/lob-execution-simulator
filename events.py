"""Small, explicit event format shared by Python and C++ replay engines.

Prices are 1/10,000 USD; timestamps are nanoseconds since exchange midnight.
E and C reduce displayed shares. C may also carry a different actual trade price.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True, slots=True)
class Event:
    ts_ns: int
    kind: str  # A F E C X D U
    order_id: int
    side: str = ""  # B or S for additions; derives from book for other kinds
    shares: int = 0
    price_ticks: int = 0
    new_order_id: int = 0
    symbol: str = ""
    trade_price_ticks: int = 0

    def __post_init__(self) -> None:
        if self.ts_ns < 0 or self.kind not in {"A", "F", "E", "C", "X", "D", "U"}:
            raise ValueError("Invalid timestamp or event kind")
        if self.order_id <= 0:
            raise ValueError("Order reference must be positive")
        if self.kind in {"A", "F"}:
            if self.side not in {"B", "S"} or self.shares <= 0 or self.price_ticks <= 0:
                raise ValueError("An add requires side, positive shares, and price")
        elif self.kind in {"E", "C", "X"} and self.shares <= 0:
            raise ValueError("Execution/cancellation shares must be positive")
        elif self.kind == "U" and (self.new_order_id <= 0 or self.shares <= 0 or self.price_ticks <= 0):
            raise ValueError("Replace needs new ID, shares, and price")


def usd(ticks: int) -> float:
    return ticks / 10_000
