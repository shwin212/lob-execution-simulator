import gzip
import struct

import pytest

from lob_sim.events import Event
from lob_sim.io import read_events, write_events
from lob_sim.itch import decode, iter_itch, read_frames
from lob_sim.synthetic import generate, pack_message, write_binary


def test_normalized_roundtrip(tmp_path):
    tape = generate(seed=7, count=100)
    path = tmp_path / "events.csv"
    assert write_events(path, tape) == 100
    assert list(read_events(path)) == tape


def test_binary_roundtrip_and_selected_symbol(tmp_path):
    tape = generate(seed=9, count=250)
    path = tmp_path / "tape.itch.gz"
    write_binary(path, tape)
    assert list(iter_itch(path, symbol="DEMO")) == tape
    assert list(iter_itch(path, symbol="ANOTHER")) == []
    assert len(list(iter_itch(path, symbol="DEMO", limit=7))) == 7


def test_c_execution_and_f_attribution(tmp_path):
    tape = [Event(10, "F", 1, "B", 50, 1_000_000, symbol="TEST"),
            Event(20, "C", 1, shares=8, trade_price_ticks=1_000_100),
            Event(30, "U", 1, shares=33, price_ticks=1_000_200, new_order_id=2),
            Event(40, "D", 2)]
    path = tmp_path / "input.bin"
    write_binary(path, tape)
    assert list(iter_itch(path, symbol="TEST")) == tape
    assert len(pack_message(tape[0])) == 40
    assert len(pack_message(tape[1])) == 36


def test_unknown_non_book_messages_skipped(tmp_path):
    order = Event(10, "A", 1, "B", 10, 10000, symbol="DEMO")
    path = tmp_path / "mixed.itch.gz"
    # Synthetic stock directory: type 'R' is deliberately ignored.
    extra = b"R" + b"\x00" * 38
    with gzip.open(path, "wb") as out:
        for raw in [extra, pack_message(order)]:
            out.write(struct.pack(">H", len(raw)))
            out.write(raw)
    assert list(iter_itch(path, "DEMO")) == [order]


def test_truncated_frame_rejected(tmp_path):
    path = tmp_path / "broken.bin"
    path.write_bytes(b"\x00\x24" + b"A" * 3)
    with pytest.raises(ValueError, match="Truncated"):
        list(read_frames(path))
    with pytest.raises(ValueError, match="must have"):
        decode(b"A" * 35)
