# Benchmarks

In-process latency and throughput for the golden-fixture API, on the Model v2 engine. Produced by `backend/scripts/benchmark.py`.

## Run

- **Date:** 2026-10-17 (UTC)
- **Commit:** `15a3574` (origin/main at run time, Model v2, PR #18), plus the benchmark files in this PR
- **Machine:** Apple M2 Max, 12 logical CPUs (`sysctl -n machdep.cpu.brand_string hw.ncpu`)
- **Python:** 3.12.14 (the backend venv, `uv run python -V`)
- **Sample size:** n = 500 measured requests per HTTP row, after 50 unmeasured warmup requests. 1,000 direct `simulate()` calls and 100 Monte Carlo calls (10,000 draws each), no warmup.
- **Method:** the ASGI app is driven through `httpx.AsyncClient(transport=ASGITransport)`, so no socket is opened and no upstream API is reached. Latency is per request, measured around the client call. req/s is measured requests divided by wall time. Concurrency is the number of asyncio workers.
- **Excluded:** the JSON access log is silenced for the run (one line per request would flood stdout and add handler time to every sample). The `/readyz` and `/healthz` routes are not benchmarked.
- **Single run.** These are not a distribution across runs. Re-run before quoting a number as a commitment.

Reproduce from `backend/`:

```bash
uv run python -m scripts.benchmark --n 500 --warmup 50 --direct-n 1000 --mc-n 100 --concurrency 1 16
```

## Results

| Benchmark | n | Concurrency | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| score SCENARIO_1_LA_FLOOD | 500 | 1 | 7.15 | 7.84 | 12.66 | 135.5 |
| score SCENARIO_2_CA_WUI | 500 | 1 | 7.39 | 9.18 | 12.94 | 130.3 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 1 | 8.65 | 9.24 | 10.38 | 114.1 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 1 | 8.64 | 9.28 | 12.00 | 113.7 |
| simulate-mitigation S2, 0 action(s) | 500 | 1 | 7.66 | 8.49 | 9.81 | 128.3 |
| simulate-mitigation S2, 1 action(s) | 500 | 1 | 7.50 | 8.13 | 8.94 | 131.9 |
| simulate-mitigation S2, 3 action(s) | 500 | 1 | 7.72 | 8.62 | 9.78 | 127.9 |
| verification/evidence S2, LIDAR | 500 | 1 | 14.76 | 16.05 | 22.12 | 66.7 |
| score SCENARIO_1_LA_FLOOD | 500 | 16 | 7.05 | 7.37 | 7.63 | 141.2 |
| score SCENARIO_2_CA_WUI | 500 | 16 | 7.13 | 7.83 | 11.72 | 137.2 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 16 | 8.56 | 9.30 | 13.22 | 114.8 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 16 | 8.76 | 9.30 | 9.49 | 113.4 |
| simulate-mitigation S2, 0 action(s) | 500 | 16 | 109.00 | 135.13 | 146.64 | 145.5 |
| simulate-mitigation S2, 1 action(s) | 500 | 16 | 108.74 | 134.44 | 148.85 | 146.6 |
| simulate-mitigation S2, 3 action(s) | 500 | 16 | 110.54 | 148.62 | 195.77 | 140.3 |
| verification/evidence S2, LIDAR | 500 | 16 | 207.04 | 243.53 | 261.31 | 76.9 |
| simulate() direct, S2, 0 actions | 1000 | - | 6.56 | 7.04 | 8.90 | 150.5 |
| Monte Carlo alone, S2 (10,000 draws) | 100 | - | 2.77 | 2.96 | 3.07 | 356.9 |

Reading the concurrency-16 rows: the simulate and evidence endpoints run synchronous code in a thread pool, and the GIL serialises most of it. Latency at 16 workers is roughly 16 ÷ req/s (for example 16 ÷ 145.5 ≈ 110 ms), so the extra latency is queueing, not slower handlers. A deployment would scale this with `uvicorn --workers N` (one process per core, each with its own GIL), or move the CPU-bound simulate path to a process pool; making handlers `async` alone would not help, since the work is CPU-bound, not I/O-bound.

Model v2 cost: on the pre-v2 model (commit `4086f70`, same machine, same settings), `simulate()` direct p50 was 1.20 ms and `simulate-mitigation` at concurrency 1 was about 2.1 ms. The v2 engine is about 5× slower per simulate call, and the uncertainty step accounts for only part of that (Monte Carlo alone is 2.77 ms p50). The rest of the increase is elsewhere in the chain and has not been profiled.

## Not benchmarked here

- **Live scoring for an address outside the demo.** That path calls upstream APIs (FEMA, Census). Its latency is dominated by those services and the network, so it is not measured by this script. The relevant controls are the per-source timeouts (2.5 s in `backend/app/ingestion/engine.py`, 3.0 s for NFHL in `backend/app/ingestion/nfhl.py`) and the TTL cache in `backend/app/cache.py`, not the in-process code.
