"""Per-service distributed locks so scaling decisions cannot race."""

from __future__ import annotations

from redis.asyncio import Redis


class ServiceLock:
    """Async context manager wrapping redis.asyncio.Lock."""

    def __init__(self, redis: Redis, service: str, timeout: float = 30.0):
        self._lock = redis.lock(
            f"scaling:lock:{service}",
            timeout=timeout,
            blocking_timeout=timeout,
        )

    async def __aenter__(self) -> ServiceLock:
        acquired = await self._lock.acquire()
        if not acquired:
            raise TimeoutError("timed out waiting for service scaling lock")
        return self

    async def __aexit__(self, exc_type, exc, tb) -> None:
        try:
            await self._lock.release()
        except Exception:
            # Lock may have expired; never fail the caller on release.
            pass
