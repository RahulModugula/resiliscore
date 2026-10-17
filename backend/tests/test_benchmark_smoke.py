"""Smoke test for scripts/benchmark.py: it runs end to end with n=5 and returns numbers.

The only timing assertion is that direct simulate() p95 stays under 50 ms.
"""

import importlib.util
from pathlib import Path

import pytest

SCRIPT = Path(__file__).resolve().parents[1] / "scripts" / "benchmark.py"


@pytest.fixture(scope="module")
def benchmark():
    spec = importlib.util.spec_from_file_location("benchmark", SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_percentile_is_nearest_rank(benchmark):
    samples = [float(i) for i in range(1, 101)]
    assert benchmark.percentile(samples, 50) == 50.0
    assert benchmark.percentile(samples, 95) == 95.0
    assert benchmark.percentile(samples, 99) == 99.0
    assert benchmark.percentile([7.0], 99) == 7.0


def test_percentile_rejects_empty(benchmark):
    with pytest.raises(ValueError):
        benchmark.percentile([], 50)


def test_benchmark_runs_with_n_5_and_returns_numbers(benchmark, capsys):
    rows = benchmark.main(["--n", "5", "--warmup", "1", "--direct-n", "5", "--concurrency", "1", "2"])

    # 4 scenarios + 3 simulate counts + 1 evidence, for each of 2 concurrency levels, plus 1 direct row.
    assert len(rows) == 2 * (4 + 3 + 1) + 1
    for row in rows:
        assert row.n == 5
        assert row.rps > 0
        assert 0 <= row.p50_ms <= row.p95_ms <= row.p99_ms

    direct = rows[-1]
    assert direct.name.startswith("simulate() direct")
    assert direct.p95_ms < 50

    out = capsys.readouterr().out
    assert out.startswith("| Benchmark | n | Concurrency |")
