"""Streaming NASDAQ TotalView-ITCH 5.0 BinaryFILE parser (subset).

Recognized A/F/E/C/X/D/U records are decoded. Other official message types
(trades, crosses, trading status, etc.) are deliberately skipped: they do not
change *displayed* order-level depth. Not a full exchange message decoder.

Source: https://www.nasdaqtrader.com/content/technicalsupport/specifications/dataproducts/NQTVITCHSpecification.pdf
"""
from __future__ import annotations

import gzip
import struct
from pathlib import Path
from typing import Iterator

from .events import Event

LENGTHS = {"A": 36, "F": 40, "E": 31, "C": 36, "X": 23, "D": 19, "U": 35}


def read_frames(path: str | Path) -> Iterator[bytes]:
    opener = gzip.open if str(path).endswith(".gz") else open
    with opener(path, "rb") as f:
        while True:
            prefix = f.read(2)
            if not prefix:
                return
            if len(prefix) != 2:
                raise ValueError("Truncated BinaryFILE record length")
            (length,) = struct.unpack(">H", prefix)
            if length == 0:
                continue
            raw = f.read(length)
            if len(raw) != length:
                raise ValueError("Truncated BinaryFILE message")
            yield raw


def decode(raw: bytes) -> Event | None:
    if not raw:
        raise ValueError("Empty ITCH frame")
    kind = chr(raw[0])
    if kind not in LENGTHS:
        return None
    if len(raw) != LENGTHS[kind]:
        raise ValueError(f"ITCH {kind} must have {LENGTHS[kind]} bytes, got {len(raw)}")
    ts = int.from_bytes(raw[5:11], "big")
    oid = struct.unpack_from(">Q", raw, 11)[0]
    if kind in {"A", "F"}:
        shares = struct.unpack_from(">I", raw, 20)[0]
        price = struct.unpack_from(">I", raw, 32)[0]
        return Event(ts, kind, oid, chr(raw[19]), shares, price,
                     symbol=raw[24:32].decode("ascii").strip())
    if kind in {"E", "C", "X"}:
        qty = struct.unpack_from(">I", raw, 19)[0]
        price = struct.unpack_from(">I", raw, 32)[0] if kind == "C" else 0
        return Event(ts, kind, oid, shares=qty, trade_price_ticks=price)
    if kind == "D":
        return Event(ts, kind, oid)
    new_id, shares, price = struct.unpack_from(">QII", raw, 19)
    return Event(ts, kind, oid, shares=shares, price_ticks=price, new_order_id=new_id)


def iter_itch(path: str | Path, symbol: str | None = None,
              limit: int | None = None) -> Iterator[Event]:
    """Stream one symbol; filter modifications by their added/replaced IDs.

    Start at beginning of day's data for completeness. A symbol filter avoids
    loading books for other stocks, but the feed itself is still read in order.
    A limit applies to *selected decoded events*, not raw messages.
    """
    selected_ids: set[int] = set()
    emitted = 0
    previous_ts = -1
    for raw in read_frames(path):
        event = decode(raw)
        if event is None:
            continue
        if event.ts_ns < previous_ts:
            raise ValueError("Out-of-order ITCH timestamps")
        previous_ts = event.ts_ns
        if symbol is not None:
            if event.kind in {"A", "F"}:
                if event.symbol.strip().upper() != symbol.upper():
                    continue
                selected_ids.add(event.order_id)
            elif event.order_id not in selected_ids:
                continue
            if event.kind == "U":
                selected_ids.add(event.new_order_id)
        yield event
        emitted += 1
        if limit is not None and emitted >= limit:
            return
