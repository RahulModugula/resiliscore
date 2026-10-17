"""Async TTL cache for federal lookups (county priors, NRI tracts, EPQS tiles).

Only successful results are stored: a failed upstream call is never cached, so the next request retries it.
"""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable, Hashable
from typing import Generic, TypeVar

T = TypeVar("T")


class TTLCache(Generic[T]):
    def __init__(self, ttl_s: float, max_entries: int = 4096, clock: Callable[[], float] = time.monotonic):
        self._ttl_s = ttl_s
        self._max = max_entries
        self._clock = clock
        self._data: dict[Hashable, tuple[float, T]] = {}

    def get(self, key: Hashable) -> T | None:
        hit = self._data.get(key)
        if hit is None:
            return None
        expires, value = hit
        if self._clock() >= expires:
            del self._data[key]
            return None
        return value

    def put(self, key: Hashable, value: T) -> None:
        if len(self._data) >= self._max:
            self._data.pop(next(iter(self._data)))  # oldest insertion first
        self._data[key] = (self._clock() + self._ttl_s, value)

    async def get_or_set(self, key: Hashable, factory: Callable[[], Awaitable[T]]) -> T:
        hit = self.get(key)
        if hit is not None:
            return hit
        value = await factory()
        self.put(key, value)
        return value

    def clear(self) -> None:
        self._data.clear()

    def __len__(self) -> int:
        return len(self._data)
