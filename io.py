"""Round-trippable, dependency-free normalized event CSV format."""
from __future__ import annotations

import csv
from pathlib import Path
from typing import Iterable, Iterator

from .events import Event

COLUMNS = ["ts_ns", "kind", "order_id", "side", "shares", "price_ticks",
           "new_order_id", "symbol", "trade_price_ticks"]


def write_events(path: str | Path, events: Iterable[Event]) -> int:
    count = 0
    with open(path, "w", newline="", encoding="utf-8") as f:
        writer = csv.writer(f, lineterminator="\n")
        writer.writerow(COLUMNS)
        for e in events:
            writer.writerow([getattr(e, key) for key in COLUMNS])
            count += 1
    return count


def read_events(path: str | Path) -> Iterator[Event]:
    with open(path, newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        if reader.fieldnames != COLUMNS:
            raise ValueError(f"Expected exact columns: {COLUMNS}")
        last_ts = -1
        for line, row in enumerate(reader, 2):
            try:
                e = Event(
                    ts_ns=int(row["ts_ns"]), kind=row["kind"],
                    order_id=int(row["order_id"]), side=row["side"],
                    shares=int(row["shares"]), price_ticks=int(row["price_ticks"]),
                    new_order_id=int(row["new_order_id"]), symbol=row["symbol"],
                    trade_price_ticks=int(row["trade_price_ticks"]),
                )
            except (ValueError, TypeError) as exc:
                raise ValueError(f"Invalid event CSV line {line}: {exc}") from exc
            if e.ts_ns < last_ts:
                raise ValueError(f"Nonmonotonic timestamp on line {line}")
            last_ts = e.ts_ns
            yield e
