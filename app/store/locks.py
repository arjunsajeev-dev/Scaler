"""Per-service distributed locks so scaling decisions cannot race."""

from __future__ import annotations

import asyncio
import secrets
import time

from redis.asyncio import Redis


class ServiceLock:
    """Async context manager using SET NX so decode_responses Redis stays consistent."""

    def __init__(self, redis: Redis, service: str, timeout: float = 30.0):
        self._redis = redis
        self._key = f"scaling:lock:{service}"
        self._timeout = timeout
        self._token = secrets.token_hex(16)

    async def __aenter__(self) -> ServiceLock:
        deadline = time.monotonic() + self._timeout
        ttl = max(int(self._timeout), 1)
        while True:
            acquired = await self._redis.set(self._key, self._token, nx=True, ex=ttl)
            if acquired:
                return self
            if time.monotonic() >= deadline:
                raise TimeoutError("timed out waiting for service scaling lock")
            await asyncio.sleep(0.05)

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            token = await self._redis.get(self._key)
            if token == self._token:
                await self._redis.delete(self._key)
        except Exception:
            pass
