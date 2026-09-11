"""Poll Docker stats and write rolling averages into Redis."""

from __future__ import annotations

import time
from typing import Any

import structlog

from scaler.docker.client import DockerInterface, Replica
from scaler.models import CpuSample, MetricSample
from scaler.store.redis_store import RedisStore

log = structlog.get_logger(__name__)


def cpu_percent_from_delta(
    prev: CpuSample,
    curr: CpuSample,
) -> float | None:
    """Compute CPU % from two cumulative samples. Do not trust precpu_stats."""
    cpu_delta = curr.total_usage - prev.total_usage
    system_delta = curr.system_cpu_usage - prev.system_cpu_usage
    if cpu_delta < 0 or system_delta <= 0 or curr.online_cpus <= 0:
        return None
    return (cpu_delta / system_delta) * curr.online_cpus * 100.0


def _online_cpus(cpu_stats: dict[str, Any]) -> int:
    n = cpu_stats.get("online_cpus")
    if n:
        return int(n)
    percpu = cpu_stats.get("cpu_usage", {}).get("percpu_usage") or []
    return len(percpu) or 1


def parse_cpu_sample(stats: dict[str, Any]) -> CpuSample | None:
    cpu_stats = stats.get("cpu_stats") or {}
    usage = cpu_stats.get("cpu_usage") or {}
    total = usage.get("total_usage")
    system = cpu_stats.get("system_cpu_usage")
    if total is None or system is None:
        return None
    return CpuSample(
        total_usage=int(total),
        system_cpu_usage=int(system),
        online_cpus=_online_cpus(cpu_stats),
    )


def parse_memory_bytes(stats: dict[str, Any]) -> int:
    mem = stats.get("memory_stats") or {}
    usage = int(mem.get("usage") or 0)
    stats_detail = mem.get("stats") or {}
    cache = int(stats_detail.get("cache") or stats_detail.get("inactive_file") or 0)
    return max(usage - cache, 0)


def parse_network(stats: dict[str, Any]) -> tuple[int, int]:
    networks = stats.get("networks") or {}
    rx = tx = 0
    for iface in networks.values():
        rx += int(iface.get("rx_bytes") or 0)
        tx += int(iface.get("tx_bytes") or 0)
    return rx, tx


async def collect_replica_sample(
    docker: DockerInterface,
    store: RedisStore,
    replica: Replica,
) -> MetricSample | None:
    stats = await docker.stats(replica.id)
    if not stats:
        return None
    curr = parse_cpu_sample(stats)
    if curr is None:
        return None
    prev = await store.get_cpu_prev(replica.id)
    await store.set_cpu_prev(replica.id, curr)
    if prev is None:
        # First tick after a container appears is a warm-up; no usable %.
        return None
    cpu = cpu_percent_from_delta(prev, curr)
    if cpu is None:
        return None
    rx, tx = parse_network(stats)
    return MetricSample(
        ts=time.time(),
        cpu_percent=cpu,
        memory_bytes=parse_memory_bytes(stats),
        net_rx_bytes=rx,
        net_tx_bytes=tx,
    )


async def collect_service_metrics(
    docker: DockerInterface,
    store: RedisStore,
    service: str,
    window: int,
) -> MetricSample | None:
    replicas = await docker.list_replicas(service, all_=False)
    samples: list[MetricSample] = []
    for replica in replicas:
        if replica.status != "running":
            continue
        sample = await collect_replica_sample(docker, store, replica)
        if sample is not None:
            samples.append(sample)
    if not samples:
        return None
    averaged = MetricSample(
        ts=time.time(),
        cpu_percent=sum(s.cpu_percent for s in samples) / len(samples),
        memory_bytes=int(sum(s.memory_bytes for s in samples) / len(samples)),
        net_rx_bytes=int(sum(s.net_rx_bytes for s in samples) / len(samples)),
        net_tx_bytes=int(sum(s.net_tx_bytes for s in samples) / len(samples)),
    )
    await store.push_metric_sample(service, averaged, window)
    log.debug(
        "metrics_collected",
        service=service,
        replicas=len(samples),
        avg_cpu=round(averaged.cpu_percent, 2),
    )
    return averaged
