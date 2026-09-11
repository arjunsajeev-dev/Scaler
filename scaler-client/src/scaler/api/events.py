"""In-process pub/sub for WS /events."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator

from scaler.models import ScalingEvent


class EventBus:
    def __init__(self) -> None:
        self._subs: set[asyncio.Queue[ScalingEvent]] = set()

    def subscribe(self) -> asyncio.Queue[ScalingEvent]:
        queue: asyncio.Queue[ScalingEvent] = asyncio.Queue(maxsize=200)
        self._subs.add(queue)
        return queue

    def unsubscribe(self, queue: asyncio.Queue[ScalingEvent]) -> None:
        self._subs.discard(queue)

    async def publish(self, event: ScalingEvent) -> None:
        for queue in list(self._subs):
            try:
                queue.put_nowait(event)
            except asyncio.QueueFull:
                try:
                    queue.get_nowait()
                except asyncio.QueueEmpty:
                    pass
                try:
                    queue.put_nowait(event)
                except asyncio.QueueFull:
                    pass

    async def stream(self) -> AsyncIterator[ScalingEvent]:
        queue = self.subscribe()
        try:
            while True:
                yield await queue.get()
        finally:
            self.unsubscribe(queue)
