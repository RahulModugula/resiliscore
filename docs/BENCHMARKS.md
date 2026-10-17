# Benchmarks

In-process latency and throughput for the golden-fixture API. Produced by `backend/scripts/benchmark.py`.

## Run

- **Date:** 2026-10-17 (UTC)
- **Commit:** `4086f70` (origin/main at run time), plus the benchmark files in this PR
- **Machine:** Apple M2 Max, 12 logical CPUs (`sysctl -n machdep.cpu.brand_string hw.ncpu`)
- **Python:** 3.12.14 (the backend venv, `uv run python -V`)
- **Sample size:** n = 500 measured requests per HTTP row, after 50 unmeasured warmup requests. 1,000 direct `simulate()` calls, no warmup.
- **Method:** the ASGI app is driven through `httpx.AsyncClient(transport=ASGITransport)`, so no socket is opened and no upstream API is reached. Latency is per request, measured around the client call. req/s is measured requests divided by wall time. Concurrency is the number of asyncio workers.
- **Excluded:** the JSON access log is silenced for the run (one line per request would flood stdout and add handler time to every sample). The `/readyz` and `/healthz` routes are not benchmarked.
- **Single run.** These are not a distribution across runs. Re-run before quoting a number as a commitment.

Reproduce from `backend/`:

```bash
uv run python -m scripts.benchmark --n 500 --warmup 50 --direct-n 1000 --concurrency 1 16
```

## Results

| Benchmark | n | Concurrency | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| score SCENARIO_1_LA_FLOOD | 500 | 1 | 1.33 | 2.28 | 2.97 | 687.6 |
| score SCENARIO_2_CA_WUI | 500 | 1 | 1.67 | 3.12 | 6.11 | 517.1 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 1 | 1.50 | 1.72 | 1.85 | 653.1 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 1 | 1.51 | 1.76 | 1.85 | 648.6 |
| simulate-mitigation S2, 0 action(s) | 500 | 1 | 2.13 | 2.48 | 2.81 | 460.2 |
| simulate-mitigation S2, 1 action(s) | 500 | 1 | 2.12 | 2.32 | 2.54 | 462.7 |
| simulate-mitigation S2, 3 action(s) | 500 | 1 | 2.13 | 2.34 | 2.60 | 464.6 |
| verification/evidence S2, LIDAR | 500 | 1 | 3.92 | 4.33 | 4.63 | 254.5 |
| score SCENARIO_1_LA_FLOOD | 500 | 16 | 1.46 | 1.62 | 1.71 | 686.0 |
| score SCENARIO_2_CA_WUI | 500 | 16 | 1.73 | 1.93 | 2.09 | 579.9 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 16 | 1.59 | 2.00 | 3.20 | 602.7 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 16 | 1.59 | 1.82 | 1.98 | 622.8 |
| simulate-mitigation S2, 0 action(s) | 500 | 16 | 36.34 | 46.93 | 52.68 | 434.0 |
| simulate-mitigation S2, 1 action(s) | 500 | 16 | 35.83 | 47.53 | 52.78 | 442.8 |
| simulate-mitigation S2, 3 action(s) | 500 | 16 | 36.94 | 46.85 | 55.01 | 429.5 |
| verification/evidence S2, LIDAR | 500 | 16 | 68.83 | 90.01 | 108.35 | 226.7 |
| simulate() direct, S2, 0 actions | 1000 | - | 1.20 | 1.77 | 2.89 | 770.3 |

Reading the concurrency-16 rows: the simulate and evidence endpoints run synchronous code in a thread pool, and the GIL serialises most of it. Latency at 16 workers is roughly 16 ÷ req/s (for example 16 ÷ 434 ≈ 37 ms), so the extra latency is queueing, not slower handlers.

## Not benchmarked here

- **Monte Carlo alone.** There is no sampler on `origin/main` yet; the `Uncertainty` schema has no producer. It is deferred until the uncertainty model lands (PR #18).
- **Live scoring for an address outside the demo.** That path calls upstream APIs (FEMA, Census). Its latency is dominated by those services and the network, so it is not measured by this script. The relevant controls are the per-source timeouts (2.5 s in `backend/app/ingestion/engine.py`, 3.0 s for NFHL in `backend/app/ingestion/nfhl.py`) and the TTL cache in `backend/app/cache.py`, not the in-process code.
