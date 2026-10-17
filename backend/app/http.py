"""One shared httpx.AsyncClient for every federal lookup, created in the FastAPI lifespan."""

from __future__ import annotations

from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

import httpx

USER_AGENT = "SaveMyHome/0.1 (+https://github.com/RahulModugula/resiliscore)"

_client: httpx.AsyncClient | None = None


def new_client() -> httpx.AsyncClient:
    return httpx.AsyncClient(
        timeout=httpx.Timeout(10.0, connect=5.0),
        limits=httpx.Limits(max_connections=32, max_keepalive_connections=16),
        headers={"User-Agent": USER_AGENT},
        follow_redirects=True,
    )


def get_client() -> httpx.AsyncClient | None:
    """The lifespan client, or None outside a running app (callers then open a short-lived one)."""
    return _client


@asynccontextmanager
async def borrowed_client() -> AsyncIterator[httpx.AsyncClient]:
    """The lifespan client when the app runs, else a short-lived one (tests, scripts)."""
    if _client is not None:
        yield _client
        return
    async with new_client() as own:
        yield own


@asynccontextmanager
async def lifespan(_app: object) -> AsyncIterator[None]:
    global _client
    client = _client = new_client()
    try:
        yield
    finally:
        _client = None
        await client.aclose()
