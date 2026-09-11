"""Redis-backed desired state, rolling metrics, engine counters, and audit log."""

from __future__ import annotations

import json
from typing import Any

from redis.asyncio import Redis

from scaler.config import ServicePolicy
from scaler.models import CpuSample, EngineState, MetricSample, ScalingEvent

DESIRED = "desired:{service}"
SAMPLES = "metrics:{service}:samples"
SNAPSHOT = "metrics:{service}:snapshot"
CPU_PREV = "cpu_prev:{container_id}"
ENGINE = "engine:{service}"
AUDIT = "audit:events"
DYNAMIC_POLICIES = "scaler:policies"


class RedisStore:
    def __init__(self, redis: Redis):
        self.r = redis

    async def ping(self) -> bool:
        return bool(await self.r.ping())

    async def get_desired(self, service: str) -> int | None:
        raw = await self.r.get(DESIRED.format(service=service))
        if raw is None:
            return None
        return int(raw)

    async def set_desired(self, service: str, n: int) -> None:
        await self.r.set(DESIRED.format(service=service), int(n))

    async def get_engine_state(self, service: str) -> EngineState:
        raw = await self.r.get(ENGINE.format(service=service))
        if not raw:
            return EngineState()
        return EngineState.model_validate_json(raw)

    async def set_engine_state(self, service: str, state: EngineState) -> None:
        await self.r.set(ENGINE.format(service=service), state.model_dump_json())

    async def get_cpu_prev(self, container_id: str) -> CpuSample | None:
        raw = await self.r.get(CPU_PREV.format(container_id=container_id))
        if not raw:
            return None
        return CpuSample.model_validate_json(raw)

    async def set_cpu_prev(self, container_id: str, sample: CpuSample) -> None:
        await self.r.set(
            CPU_PREV.format(container_id=container_id),
            sample.model_dump_json(),
            ex=600,
        )

    async def delete_cpu_prev(self, container_id: str) -> None:
        await self.r.delete(CPU_PREV.format(container_id=container_id))

    async def push_metric_sample(
        self, service: str, sample: MetricSample, window: int
    ) -> list[MetricSample]:
        key = SAMPLES.format(service=service)
        await self.r.lpush(key, sample.model_dump_json())
        await self.r.ltrim(key, 0, max(window - 1, 0))
        samples = await self.get_metric_samples(service)
        snapshot = {
            "avg_cpu": _avg([s.cpu_percent for s in samples]),
            "avg_memory_bytes": _avg([float(s.memory_bytes) for s in samples]),
            "avg_net_rx_bytes": _avg([float(s.net_rx_bytes) for s in samples]),
            "avg_net_tx_bytes": _avg([float(s.net_tx_bytes) for s in samples]),
            "count": len(samples),
            "latest": sample.model_dump(),
        }
        await self.r.set(SNAPSHOT.format(service=service), json.dumps(snapshot))
        return samples

    async def get_metric_samples(self, service: str) -> list[MetricSample]:
        raw = await self.r.lrange(SAMPLES.format(service=service), 0, -1)
        return [MetricSample.model_validate_json(item) for item in raw]

    async def get_snapshot(self, service: str) -> dict[str, Any] | None:
        raw = await self.r.get(SNAPSHOT.format(service=service))
        if not raw:
            return None
        return json.loads(raw)

    async def append_audit(self, event: ScalingEvent, keep: int = 200) -> None:
        await self.r.lpush(AUDIT, event.model_dump_json())
        await self.r.ltrim(AUDIT, 0, keep - 1)

    async def list_audit(self, limit: int = 50) -> list[ScalingEvent]:
        raw = await self.r.lrange(AUDIT, 0, limit - 1)
        return [ScalingEvent.model_validate_json(item) for item in raw]

    async def get_dynamic_policies(self) -> dict[str, ServicePolicy]:
        raw = await self.r.get(DYNAMIC_POLICIES)
        if not raw:
            return {}
        data = json.loads(raw)
        return {
            name: ServicePolicy.model_validate(spec)
            for name, spec in data.items()
        }

    async def upsert_dynamic_policy(self, policy: ServicePolicy) -> None:
        current = await self.get_dynamic_policies()
        current[policy.name] = policy
        payload = {name: item.model_dump() for name, item in current.items()}
        await self.r.set(DYNAMIC_POLICIES, json.dumps(payload))

    async def remove_dynamic_policy(self, name: str) -> None:
        current = await self.get_dynamic_policies()
        current.pop(name, None)
        payload = {key: item.model_dump() for key, item in current.items()}
        await self.r.set(DYNAMIC_POLICIES, json.dumps(payload))

    async def clear_service_state(self, service: str) -> None:
        await self.r.delete(
            DESIRED.format(service=service),
            SAMPLES.format(service=service),
            SNAPSHOT.format(service=service),
            ENGINE.format(service=service),
        )


def _avg(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)
