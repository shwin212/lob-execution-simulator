from lob_sim.book import OrderBook
from lob_sim.events import Event
from lob_sim.sim import MarketMaker, estimate_volume_profile, vwap_backtest, walk_forward
from lob_sim.synthetic import generate


def test_maker_queue_ahead_and_late_arrivals():
    tape = [
        Event(0, "A", 1, "B", 10, 999_900),
        Event(1, "A", 2, "S", 10, 1_000_100),
        Event(2, "A", 3, "B", 10, 999_900),  # new order AFTER agent quote
        Event(3, "E", 1, shares=10),  # clears exactly the ahead queue
        Event(4, "E", 3, shares=5),  # execution at price behind agent quote
    ]
    # 0 ms is applied after event, next event at ts=1 activates quote.
    maker = MarketMaker(clip=5, max_inventory=15, latency_ms=0, refresh_ms=1000)
    stats = maker.run(tape)
    assert stats["filled_shares"] == 5
    assert maker.fills[0].side == "B"
    assert maker.inventory == 5
    assert stats["fill_rate"] > 0


def test_maker_inventory_cap_and_latency():
    tape = generate(seed=11, count=400)
    maker = MarketMaker(clip=10, max_inventory=10, latency_ms=3, refresh_ms=50)
    result = maker.run(tape)
    assert -10 <= maker.inventory <= 10
    assert result["posted_shares"] >= 0
    assert 0 <= result["fill_rate"] <= 1


def test_vwap_train_only_and_walk_forward():
    tape = generate(seed=13, count=500)
    profile = estimate_volume_profile(tape[:200], buckets=8)
    assert len(profile) == 8
    assert abs(sum(profile) - 1) < 1e-9
    book = OrderBook()
    for e in tape[:200]:
        book.apply(e)
    result = vwap_backtest(tape[200:300], book, profile, target=40)
    assert 0 <= result["filled_shares"] <= 40
    reports = walk_forward(tape, "vwap", folds=2, target=50)
    assert len(reports) == 2
    assert reports[0]["warmup_events"] < reports[1]["warmup_events"]
    maker_reports = walk_forward(tape, "maker", folds=2, clip=5)
    assert len(maker_reports) == 2
