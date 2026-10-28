.PHONY: install demo test cpp parity benchmark backtest clean

install:
	python -m pip install -e '.[dev]'

demo:
	python -m lob_sim demo --out-dir sample --events 5000 --seed 7

test:
	python -m pytest -q

cpp:
	mkdir -p build
	g++ -O3 -DNDEBUG -std=c++17 -Wall -Wextra -pedantic cpp/itch_replay.cpp -o build/itch_replay

parity: cpp
	python -m lob_sim benchmark --input sample/demo.csv --cpp-bin build/itch_replay --repeats 1

benchmark: cpp
	python -m lob_sim benchmark --input sample/demo.csv --cpp-bin build/itch_replay --repeats 5

backtest:
	python -m lob_sim backtest --input sample/demo.csv --strategy maker --output sample/maker_results.json
	python -m lob_sim backtest --input sample/demo.csv --strategy vwap --output sample/vwap_results.json

clean:
	rm -rf build .pytest_cache .ruff_cache
