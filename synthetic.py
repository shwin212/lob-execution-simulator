"""Deterministic synthetic exchange messages for demos and regression tests.

NOT market-derived data. Event process is simplistic and unsuitable for any
profitability inference. All synthetic orders use stock locate 1, symbol DEMO.
"""
from __future__ import annotations

import gzip
import random
import struct
from pathlib import Path
from typing import Iterable

from .book import OrderBook
from .events import Event
from .io import write_events


def generate(seed: int = 7, count: int = 5000) -> list[Event]:
    if count < 24:
        raise ValueError("At least 24 demo events are required")
    rng = random.Random(seed)
    book = OrderBook()
    tape: list[Event] = []
    next_id = 100
    ts = 34_200_000_000_000  # 09:30:00 exchange-local, nanoseconds

    def emit(kind: str, oid: int, *, side: str = "", shares: int = 0,
             price_ticks: int = 0, new_order_id: int = 0) -> None:
        nonlocal ts
        e = Event(ts, kind, oid, side, shares, price_ticks, new_order_id,
                  "DEMO" if kind in {"A", "F"} else "")
        book.apply(e)
        tape.append(e)
        ts += 10_000_000  # 10ms event spacing; timestamps monotonic

    for side in ("B", "S"):
        for dist in range(1, 5):
            for _ in range(3):
                price = 1_000_000 + (dist * 100 if side == "S" else -dist * 100)
                emit("A", next_id, side=side, shares=rng.randint(60, 150), price_ticks=price)
                next_id += 1

    for n in range(count - 24):
        available = list(book.orders.values())
        missing_side = "B" if not book.bids else ("S" if not book.asks else None)
        kind_draw = rng.random()
        if kind_draw < 0.20 or not available or missing_side:
            side = missing_side or ("B" if rng.random() < 0.5 else "S")
            bid, ask = book.best_bid(), book.best_ask()
            if side == "B":
                if bid is None:
                    p = (ask - 200) if ask else 999_900
                else:
                    p = bid + (100 if n % 13 == 0 and ask and ask - bid >= 200 else 0)
                if ask is not None:
                    p = min(p, ask - 100)
            else:
                if ask is None:
                    p = (bid + 200) if bid else 1_000_100
                else:
                    p = ask - (100 if n % 13 == 0 and bid and ask - bid >= 200 else 0)
                if bid is not None:
                    p = max(p, bid + 100)
            emit("A", next_id, side=side, shares=rng.randint(20, 95), price_ticks=p)
            next_id += 1
            continue
        if rng.random() < 0.8:
            top_bid, top_ask = book.best_bid(), book.best_ask()
            tops = [o for o in available if o.price_ticks in {top_bid, top_ask}]
            chosen = rng.choice(tops if tops else available)
        else:
            chosen = rng.choice(available)
        if kind_draw < 0.93:
            qty = rng.randint(max(1, chosen.shares // 2), chosen.shares)
            emit("E", chosen.order_id, shares=qty)
        elif kind_draw < 0.97:
            qty = rng.randint(1, chosen.shares)
            emit("X", chosen.order_id, shares=qty)
        elif kind_draw < 0.99:
            emit("D", chosen.order_id)
        else:
            emit("U", chosen.order_id, shares=rng.randint(10, 100),
                 price_ticks=chosen.price_ticks, new_order_id=next_id)
            next_id += 1
    return tape


def pack_message(e: Event) -> bytes:
    """Pack test messages as actual ITCH 5.0-compatible A/E/X/D/U etc."""
    prefix = e.kind.encode("ascii") + struct.pack(">HH", 1, 0) + e.ts_ns.to_bytes(6, "big")
    if e.kind in {"A", "F"}:
        content = struct.pack(">QcI8sI", e.order_id, e.side.encode(), e.shares,
                              e.symbol.encode().ljust(8, b" "), e.price_ticks)
        if e.kind == "F":
            content += b"DEMO"
    elif e.kind == "E":
        content = struct.pack(">QIQ", e.order_id, e.shares, e.order_id)
    elif e.kind == "C":
        content = struct.pack(">QIQcI", e.order_id, e.shares, e.order_id,
                              b"Y", e.trade_price_ticks or e.price_ticks)
    elif e.kind == "X":
        content = struct.pack(">QI", e.order_id, e.shares)
    elif e.kind == "D":
        content = struct.pack(">Q", e.order_id)
    elif e.kind == "U":
        content = struct.pack(">QQII", e.order_id, e.new_order_id, e.shares, e.price_ticks)
    else:
        raise ValueError(f"Unsupported event kind {e.kind}")
    return prefix + content


def write_binary(path: str | Path, tape: Iterable[Event]) -> int:
    opener = gzip.open if str(path).endswith(".gz") else open
    count = 0
    with opener(path, "wb") as f:
        for e in tape:
            msg = pack_message(e)
            f.write(struct.pack(">H", len(msg)))
            f.write(msg)
            count += 1
    return count


def make_demo(out_dir: str | Path, count: int = 5000, seed: int = 7) -> dict:
    dest = Path(out_dir)
    dest.mkdir(parents=True, exist_ok=True)
    tape = generate(seed=seed, count=count)
    csv_path = dest / "demo.csv"
    bin_path = dest / "demo.itch.gz"
    write_events(csv_path, tape)
    write_binary(bin_path, tape)
    return {"events": len(tape), "seed": seed, "csv": str(csv_path),
            "itch": str(bin_path), "synthetic": True}
