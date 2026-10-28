import pytest

from lob_sim.book import OrderBook
from lob_sim.events import Event


def evt(t, k, oid, side="", qty=0, price=0, new=0):
    return Event(t, k, oid, side, qty, price, new)


def test_price_time_priority_and_partial_reductions():
    book = OrderBook()
    book.apply(evt(0, "A", 1, "B", 100, 999_900))
    book.apply(evt(1, "F", 2, "B", 80, 999_900))
    book.apply(evt(2, "A", 3, "S", 60, 1_000_100))
    assert list(book.orders_at("B", 999_900)) == [1, 2]
    book.apply(evt(3, "E", 1, qty=40))
    book.apply(evt(4, "X", 2, qty=20))
    assert book.level_qty("B", 999_900) == 120
    assert list(book.orders_at("B", 999_900)) == [1, 2]
    book.apply(evt(5, "C", 1, qty=60))
    assert list(book.orders_at("B", 999_900)) == [2]
    book.assert_consistent()
    assert book.executed_shares == 100


def test_replace_gets_new_id_and_loses_priority():
    book = OrderBook()
    for oid in [1, 2]:
        book.apply(evt(oid, "A", oid, "B", 10, 1_000_000))
    book.apply(evt(3, "U", 1, qty=15, price=1_000_000, new=4))
    assert list(book.orders_at("B", 1_000_000)) == [2, 4]
    with pytest.raises(KeyError):
        book.apply(evt(4, "D", 1))
    book.apply(evt(5, "D", 4))
    book.assert_consistent()
    assert book.level_qty("B", 1_000_000) == 10


def test_sweep_snapshot_not_mutated():
    book = OrderBook()
    book.apply(evt(0, "A", 1, "S", 10, 1_000_100))
    book.apply(evt(1, "A", 2, "S", 15, 1_000_200))
    qty, average, detail = book.sweep("B", 20)
    assert qty == 20
    assert average == (10 * 1_000_100 + 10 * 1_000_200) / 20
    assert detail == [(1_000_100, 10), (1_000_200, 10)]
    assert len(book.orders) == 2
    with pytest.raises(ValueError):
        book.apply(evt(2, "X", 1, qty=11))
