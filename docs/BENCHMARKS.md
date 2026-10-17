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
- **Machine-readable output:** the same rows are written to `backend/validation/results/benchmarks.json` (a list of `{name, n, concurrency, p50_ms, p95_ms, p99_ms, rps}`; `concurrency` is `null` for the direct rows).

Reproduce from `backend/`:

```bash
uv run python -m scripts.benchmark --n 500 --warmup 50 --direct-n 1000 --mc-n 100 --concurrency 1 16
```

## Results

| Benchmark | n | Concurrency | p50 ms | p95 ms | p99 ms | req/s |
|---|---:|---:|---:|---:|---:|---:|
| score SCENARIO_1_LA_FLOOD | 500 | 1 | 7.31 | 9.11 | 12.71 | 130.6 |
| score SCENARIO_2_CA_WUI | 500 | 1 | 7.34 | 7.96 | 11.58 | 133.7 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 1 | 8.88 | 12.37 | 17.11 | 106.7 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 1 | 8.97 | 12.99 | 16.19 | 106.1 |
| simulate-mitigation S2, 0 action(s) | 500 | 1 | 7.89 | 9.31 | 10.50 | 124.1 |
| simulate-mitigation S2, 1 action(s) | 500 | 1 | 7.89 | 9.77 | 11.57 | 122.9 |
| simulate-mitigation S2, 3 action(s) | 500 | 1 | 7.99 | 9.74 | 13.60 | 120.6 |
| verification/evidence S2, LIDAR | 500 | 1 | 15.15 | 23.01 | 32.20 | 60.9 |
| score SCENARIO_1_LA_FLOOD | 500 | 16 | 7.41 | 11.01 | 13.14 | 127.4 |
| score SCENARIO_2_CA_WUI | 500 | 16 | 7.65 | 12.17 | 15.58 | 122.6 |
| score SCENARIO_3_ESCONDIDO_HITL | 500 | 16 | 8.93 | 9.97 | 12.33 | 109.4 |
| score SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED | 500 | 16 | 8.79 | 9.37 | 9.74 | 113.0 |
| simulate-mitigation S2, 0 action(s) | 500 | 16 | 111.09 | 143.28 | 161.60 | 141.4 |
| simulate-mitigation S2, 1 action(s) | 500 | 16 | 111.37 | 144.89 | 162.30 | 139.6 |
| simulate-mitigation S2, 3 action(s) | 500 | 16 | 110.38 | 136.82 | 144.96 | 143.9 |
| verification/evidence S2, LIDAR | 500 | 16 | 205.91 | 241.14 | 256.12 | 77.2 |
| simulate() direct, S2, 0 actions | 1000 | - | 6.62 | 7.82 | 11.54 | 146.6 |
| Monte Carlo alone, S2 (10,000 draws) | 100 | - | 2.79 | 2.93 | 2.96 | 356.4 |

Reading the concurrency-16 rows: the simulate and evidence endpoints run synchronous code in a thread pool, and the GIL serialises most of it. Latency at 16 workers is roughly 16 ÷ req/s (for example 16 ÷ 141.4 ≈ 113 ms), so the extra latency is queueing, not slower handlers. A deployment would scale this with `uvicorn --workers N` (one process per core, each with its own GIL), or move the CPU-bound simulate path to a process pool; making handlers `async` alone would not help, since the work is CPU-bound, not I/O-bound.

Model v2 cost: on the pre-v2 model (commit `4086f70`, same machine, same settings), `simulate()` direct p50 was 1.20 ms and `simulate-mitigation` at concurrency 1 was about 2.1 ms. The v2 engine is about 5× slower per simulate call, and the uncertainty step accounts for only part of that (Monte Carlo alone is 2.79 ms p50). The rest of the increase is elsewhere in the chain and has not been profiled.

## Not benchmarked here

- **Live scoring for an address outside the demo.** That path calls upstream APIs (FEMA, Census). Its latency is dominated by those services and the network, so it is not measured by this script. The relevant controls are the per-source timeouts (2.5 s in `backend/app/ingestion/engine.py`, 3.0 s for NFHL in `backend/app/ingestion/nfhl.py`) and the TTL cache in `backend/app/cache.py`, not the in-process code.
