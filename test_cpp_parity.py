import shutil
import subprocess

import pytest

from lob_sim.cli import benchmark
from lob_sim.io import write_events
from lob_sim.synthetic import generate


def test_cpp_matches_python_orderbook(tmp_path):
    compiler = shutil.which("g++")
    if compiler is None:
        pytest.skip("g++ unavailable")
    from pathlib import Path
    source = Path(__file__).resolve().parents[1] / "cpp" / "itch_replay.cpp"
    binary = tmp_path / "itch_replay"
    subprocess.run([compiler, "-O2", "-std=c++17", str(source), "-o", str(binary)], check=True)
    data = tmp_path / "test.csv"
    write_events(data, generate(seed=42, count=1500))
    result = benchmark(str(data), str(binary), 1)
    assert result["parity"] is True
    assert result["events"] == 1500
