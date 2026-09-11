"""Redis store rolling window and desired-state writes."""

from __future__ import annotations

import pytest
from fakeredis import FakeAsyncRedis

from scaler.models import MetricSample
from scaler.store.redis_store import RedisStore


@pytest.fixture
async def store():
    redis = FakeAsyncRedis(decode_responses=True)
    yield RedisStore(redis)
    await redis.aclose()


async def test_desired_roundtrip(store: RedisStore):
    assert await store.get_desired("demo") is None
    await store.set_desired("demo", 3)
    await store.set_desired("demo", 3)
    assert await store.get_desired("demo") == 3


async def test_rolling_window_trimmed(store: RedisStore):
    for i in range(7):
        await store.push_metric_sample(
            "demo",
            MetricSample(ts=float(i), cpu_percent=float(i * 10), memory_bytes=1000),
            window=5,
        )
    samples = await store.get_metric_samples("demo")
    assert len(samples) == 5
    snapshot = await store.get_snapshot("demo")
    assert snapshot is not None
    assert snapshot["count"] == 5
    assert snapshot["avg_cpu"] == sum(range(2, 7)) * 10 / 5


async def test_dynamic_policy_overlay(store: RedisStore):
    from scaler.config import ServicePolicy

    policy = ServicePolicy(name="gamma", image="scaler-gamma:latest")
    await store.upsert_dynamic_policy(policy)
    loaded = await store.get_dynamic_policies()
    assert loaded["gamma"].image == "scaler-gamma:latest"
    await store.set_desired("gamma", 2)
    await store.clear_service_state("gamma")
    await store.remove_dynamic_policy("gamma")
    assert await store.get_dynamic_policies() == {}
    assert await store.get_desired("gamma") is None
