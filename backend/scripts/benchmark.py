"""In-process latency and throughput benchmark for the SaveMyHome API.

Calls the ASGI app through httpx's ASGITransport, so no socket is opened and no upstream API is reached.
Run from backend/:  uv run python -m scripts.benchmark --n 500 --warmup 50 --direct-n 1000
"""

import argparse
import asyncio
import json
import logging
import math
import time
from collections.abc import Awaitable, Callable
from dataclasses import asdict, dataclass
from pathlib import Path

import httpx

from app.actuarial import uncertainty
from app.actuarial.base_rates import resolve
from app.actuarial.constants import get as c
from app.actuarial.optimizer import evaluate, simulate
from app.fixtures import by_apn
from app.main import app
from app.verification import evidence

SCENARIOS = [
    "SCENARIO_1_LA_FLOOD",
    "SCENARIO_2_CA_WUI",
    "SCENARIO_3_ESCONDIDO_HITL",
    "SCENARIO_3_ESCONDIDO_HITL__UNPERMITTED",
]
DEFAULT_JSON_OUT = Path(__file__).resolve().parents[1] / "validation" / "results" / "benchmarks.json"
S2_APN = "58430120180000"
S2_ACTIONS = ["CA_ZONE0_1_CLEARANCE", "CA_EMBER_VENTS_EAVES", "CA_IBHS_WPH_CLASS_A_ROOF"]
EVIDENCE_BODY = {"apn_uid": S2_APN, "channel": "LIDAR", "payload_meta": {}}


@dataclass(frozen=True)
class Row:
    name: str
    n: int
    concurrency: int | None
    p50_ms: float
    p95_ms: float
    p99_ms: float
    rps: float


def percentile(samples: list[float], p: float) -> float:
    """Nearest-rank percentile: the smallest sample with at least p% of samples at or below it."""
    if not samples:
        raise ValueError("no samples")
    ordered = sorted(samples)
    rank = math.ceil(p / 100 * len(ordered))
    return ordered[max(rank, 1) - 1]


def _row(name: str, latencies: list[float], wall_s: float, concurrency: int | None) -> Row:
    return Row(
        name=name,
        n=len(latencies),
        concurrency=concurrency,
        p50_ms=percentile(latencies, 50),
        p95_ms=percentile(latencies, 95),
        p99_ms=percentile(latencies, 99),
        rps=len(latencies) / wall_s,
    )


async def _drive(
    send: Callable[[], Awaitable[httpx.Response]], n: int, concurrency: int
) -> tuple[list[float], float]:
    """Send n requests with `concurrency` workers. Returns per-request latencies (ms) and wall time (s).

    Any non-2xx response raises, so an error response is never counted as a timing sample.
    """
    latencies: list[float] = []
    remaining = n

    async def worker() -> None:
        nonlocal remaining
        while remaining > 0:
            remaining -= 1
            t0 = time.perf_counter()
            resp = await send()
            latencies.append((time.perf_counter() - t0) * 1000)
            if not 200 <= resp.status_code < 300:
                raise RuntimeError(f"benchmark request failed: {resp.status_code} {resp.text[:200]}")

    start = time.perf_counter()
    await asyncio.gather(*(worker() for _ in range(concurrency)))
    return latencies, time.perf_counter() - start


async def bench_http(
    client: httpx.AsyncClient,
    name: str,
    path: str,
    body: dict,
    n: int,
    warmup: int,
    concurrency: int,
    before_run: Callable[[], None] | None = None,
) -> Row:
    async def send() -> httpx.Response:
        return await client.post(path, json=body)

    if before_run:
        before_run()
    await _drive(send, warmup, concurrency)
    latencies, wall = await _drive(send, n, concurrency)
    return _row(name, latencies, wall, concurrency)


def bench_simulate_direct(n: int) -> Row:
    """Times actuarial.optimizer.simulate on the S2 base parcel, no HTTP, no validation."""
    base = by_apn(S2_APN)
    assert base is not None, "golden S2 parcel missing"
    latencies: list[float] = []
    start = time.perf_counter()
    for _ in range(n):
        t0 = time.perf_counter()
        simulate(base, [])
        latencies.append((time.perf_counter() - t0) * 1000)
    return _row("simulate() direct, S2, 0 actions", latencies, time.perf_counter() - start, None)


def bench_monte_carlo(n: int) -> Row:
    """Times uncertainty.simulate_losses alone. Inputs are built the way optimizer.simulate builds them for S2."""
    base = by_apn(S2_APN)
    assert base is not None, "golden S2 parcel missing"
    tract, _ = resolve(base, None)
    ev = evaluate(base, base.private_verification_layer, nri=tract)
    freeboard_missing = base.public_hazard_layer.freeboard_delta_h_ft is None and "FLOOD" in {
        t.peril for t in ev.terms
    }
    kwargs = {
        "state": base.parcel_identity.state,
        "rcv_usd": base.parcel_identity.rcv_usd,
        "tract_prior_lcr": tract.tract_prior_lcr,
        "z": ev.credibility.z,
        "freeboard_known": not freeboard_missing,
    }
    latencies: list[float] = []
    start = time.perf_counter()
    for _ in range(n):
        t0 = time.perf_counter()
        uncertainty.simulate_losses(ev.terms, **kwargs)
        latencies.append((time.perf_counter() - t0) * 1000)
    name = f"Monte Carlo alone, S2 ({int(c('mc.draws')):,} draws)"
    return _row(name, latencies, time.perf_counter() - start, None)


async def run_all(n: int, warmup: int, direct_n: int, concurrencies: list[int], mc_n: int = 100) -> list[Row]:
    # The JSON access log writes one line per request. Silence it so it neither floods the table nor adds
    # handler time to every sample. BENCHMARKS.md says so; the logger level is restored afterwards.
    logger = logging.getLogger("resiliscore")
    previous = logger.level
    logger.setLevel(logging.WARNING)
    try:
        return await _run_all(n, warmup, direct_n, concurrencies, mc_n)
    finally:
        logger.setLevel(previous)


async def _run_all(n: int, warmup: int, direct_n: int, concurrencies: list[int], mc_n: int) -> list[Row]:
    rows: list[Row] = []
    transport = httpx.ASGITransport(app=app)
    async with httpx.AsyncClient(transport=transport, base_url="http://benchmark.local") as client:
        for concurrency in concurrencies:
            for scenario in SCENARIOS:
                rows.append(
                    await bench_http(
                        client,
                        f"score {scenario}",
                        "/v1/parcel/score",
                        {"scenario_id": scenario},
                        n,
                        warmup,
                        concurrency,
                    )
                )
            for count in (0, 1, 3):
                rows.append(
                    await bench_http(
                        client,
                        f"simulate-mitigation S2, {count} action(s)",
                        "/v1/parcel/simulate-mitigation",
                        {"apn_uid": S2_APN, "action_ids": S2_ACTIONS[:count]},
                        n,
                        warmup,
                        concurrency,
                    )
                )
            # Each evidence run starts from an empty store; the log grows during the run (warmup + n).
            rows.append(
                await bench_http(
                    client,
                    "verification/evidence S2, LIDAR",
                    "/v1/verification/evidence",
                    EVIDENCE_BODY,
                    n,
                    warmup,
                    concurrency,
                    before_run=lambda: setattr(evidence, "store", evidence.InMemoryEvidenceStore()),
                )
            )
    rows.append(bench_simulate_direct(direct_n))
    rows.append(bench_monte_carlo(mc_n))
    return rows


def to_markdown(rows: list[Row]) -> str:
    lines = [
        "| Benchmark | n | Concurrency | p50 ms | p95 ms | p99 ms | req/s |",
        "|---|---:|---:|---:|---:|---:|---:|",
    ]
    for r in rows:
        conc = "-" if r.concurrency is None else str(r.concurrency)
        lines.append(
            f"| {r.name} | {r.n} | {conc} | {r.p50_ms:.2f} | {r.p95_ms:.2f} | {r.p99_ms:.2f} | {r.rps:.1f} |"
        )
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> list[Row]:
    parser = argparse.ArgumentParser(
        description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter
    )
    parser.add_argument("--n", type=int, default=500, help="measured HTTP requests per benchmark")
    parser.add_argument("--warmup", type=int, default=50, help="unmeasured requests before each benchmark")
    parser.add_argument("--direct-n", type=int, default=1000, help="direct simulate() calls")
    parser.add_argument("--mc-n", type=int, default=100, help="Monte Carlo calls (10k draws each)")
    parser.add_argument("--concurrency", type=int, nargs="+", default=[1, 16], help="worker counts")
    parser.add_argument(
        "--json-out", type=Path, default=DEFAULT_JSON_OUT, help="where to write the rows as JSON"
    )
    args = parser.parse_args(argv)
    rows = asyncio.run(run_all(args.n, args.warmup, args.direct_n, args.concurrency, args.mc_n))
    print(to_markdown(rows))
    args.json_out.parent.mkdir(parents=True, exist_ok=True)
    args.json_out.write_text(json.dumps([asdict(r) for r in rows], indent=2) + "\n")
    return rows


if __name__ == "__main__":
    main()
