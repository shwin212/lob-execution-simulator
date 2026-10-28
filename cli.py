"""Entry point. Run `lob-sim --help` after `pip install -e .`."""
from __future__ import annotations

import argparse
import json
import statistics
import subprocess
import time
from pathlib import Path

from .book import OrderBook
from .io import read_events, write_events
from .itch import iter_itch
from .sim import walk_forward
from .synthetic import make_demo


def replay(events, check_every: int = 0) -> OrderBook:
    book = OrderBook()
    for n, e in enumerate(events, 1):
        book.apply(e)
        if check_every and n % check_every == 0:
            book.assert_consistent()
    book.assert_consistent()
    return book


def benchmark(csv_path: str, cpp_bin: str, repeats: int) -> dict:
    # Includes Python CSV ingestion and C++ executable start / parsing. Repeated
    # runs on the same workload are illustrative, NOT rigorous microbenchmarks.
    python_times = []
    cpp_times = []
    py_result = None
    cpp_result = None
    for _ in range(repeats):
        t0 = time.perf_counter()
        book = replay(read_events(csv_path))
        python_times.append(time.perf_counter() - t0)
        py_result = book.top(5)
        t0 = time.perf_counter()
        result = subprocess.run([cpp_bin, csv_path], capture_output=True,
                                text=True, check=True)
        cpp_times.append(time.perf_counter() - t0)
        cpp_result = json.loads(result.stdout)
        if py_result != cpp_result:
            raise RuntimeError(f"Python and C++ book states differ: {py_result} vs {cpp_result}")
    py_ms = statistics.median(python_times) * 1000
    cpp_ms = statistics.median(cpp_times) * 1000
    return {"parity": True, "repeats": repeats, "events": py_result["events"],
            "python_wall_ms_median": round(py_ms, 3),
            "cpp_wall_ms_median": round(cpp_ms, 3),
            "observed_wall_speedup": round(py_ms / cpp_ms, 3) if cpp_ms else None,
            "caveat": "wall-clock including CSV parsing and subprocess startup; environment-specific"}


def main() -> None:
    p = argparse.ArgumentParser(prog="lob-sim", description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)

    demo = sub.add_parser("demo", help="Generate reproducible SYNTHETIC CSV + ITCH")
    demo.add_argument("--out-dir", default="sample")
    demo.add_argument("--events", type=int, default=5000)
    demo.add_argument("--seed", type=int, default=7)

    parse = sub.add_parser("parse", help="Normalize ITCH BinaryFILE or .gz to CSV")
    parse.add_argument("--input", required=True)
    parse.add_argument("--symbol", required=True, help="Exactly one stock (e.g. DEMO)")
    parse.add_argument("--output", required=True)
    parse.add_argument("--limit", type=int, default=None)

    show = sub.add_parser("replay", help="Reconstruct top of displayed order book")
    show.add_argument("--input", required=True)
    show.add_argument("--depth", type=int, default=5)
    show.add_argument("--check-every", type=int, default=1000)

    back = sub.add_parser("backtest", help="Expanding-history, disjoint holdout folds")
    back.add_argument("--input", required=True)
    back.add_argument("--strategy", choices=["maker", "vwap"], default="maker")
    back.add_argument("--folds", type=int, default=3)
    back.add_argument("--output", default=None, help="Optional JSON report file")
    back.add_argument("--latency-ms", type=float, default=3.0)
    back.add_argument("--refresh-ms", type=float, default=200.0)
    back.add_argument("--clip", type=int, default=30)
    back.add_argument("--max-inventory", type=int, default=150)
    back.add_argument("--target", type=int, default=250)
    back.add_argument("--side", choices=["B", "S"], default="B")

    bench = sub.add_parser("benchmark", help="Measure C++/Python parity and wall time")
    bench.add_argument("--input", required=True)
    bench.add_argument("--cpp-bin", default="build/itch_replay")
    bench.add_argument("--repeats", type=int, default=5)

    args = p.parse_args()
    if args.command == "demo":
        result = make_demo(args.out_dir, args.events, args.seed)
    elif args.command == "parse":
        count = write_events(args.output, iter_itch(args.input, args.symbol, args.limit))
        result = {"selected_events": count, "output": args.output, "symbol": args.symbol}
    elif args.command == "replay":
        result = replay(read_events(args.input), args.check_every).top(args.depth)
    elif args.command == "backtest":
        events = list(read_events(args.input))
        if args.strategy == "maker":
            kwargs = dict(latency_ms=args.latency_ms, refresh_ms=args.refresh_ms,
                          clip=args.clip, max_inventory=args.max_inventory)
        else:
            kwargs = dict(target=args.target, side=args.side)
        result = {"strategy": args.strategy, "folds": walk_forward(events, args.strategy,
                                                                     args.folds, **kwargs),
                  "data_note": "Synthetic sample does not validate strategy profitability"}
        if args.output:
            Path(args.output).write_text(json.dumps(result, indent=2) + "\n", encoding="utf-8")
    else:
        if args.repeats < 1:
            p.error("--repeats must be >= 1")
        result = benchmark(args.input, args.cpp_bin, args.repeats)
    print(json.dumps(result, indent=2))


if __name__ == "__main__":
    main()
