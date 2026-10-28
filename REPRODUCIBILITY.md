# Reproducibility checklist

Run from the repository root:

```bash
python -m pip install -e '.[dev]'
pytest -q
lob-sim demo --out-dir sample --events 5000 --seed 7
lob-sim parse --input sample/demo.itch.gz --symbol DEMO --output sample/reparsed.csv
lob-sim replay --input sample/demo.csv
lob-sim backtest --input sample/demo.csv --strategy maker --output sample/maker_results.json
lob-sim backtest --input sample/demo.csv --strategy vwap --output sample/vwap_results.json
make cpp
lob-sim benchmark --input sample/demo.csv --cpp-bin build/itch_replay --repeats 5
```

For the synthetic fixture, `sample/reparsed.csv` should match the
original `sample/demo.csv` exactly (byte for byte on POSIX; newline
normalization may differ across OS). Binary and CSV preserve the same events.

Tests do not claim support for all exchange message types or every malformed
file scenario. Report compiler flags, OS, CPU and Python version with timing
results. Do not include licensed Nasdaq feed files in a public repository.
