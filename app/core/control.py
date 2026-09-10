"""Shared scale / status helpers used by the HTTP API and MQTT commands."""

from __future__ import annotations

import time
from typing import Any

from app.config import ServicePolicy
from app.dockeriface.client import Replica
from app.models import ReplicaStatus, ScaleResponse, ScalingEvent, ServiceStatus, StatusResponse
from app.store.locks import ServiceLock


class UnknownServiceError(LookupError):
    def __init__(self, service: str):
        self.service = service
        super().__init__(f"unknown service {service!r}")


async def service_status(app: Any, policy: ServicePolicy, now: float) -> ServiceStatus:
    desired = await app.store.get_desired(policy.name)
    if desired is None:
        desired = policy.min_replicas
    replicas: list[Replica] = await app.docker.list_replicas(policy.name, all_=True)
    running = [r for r in replicas if r.status == "running"]
    snapshot = await app.store.get_snapshot(policy.name)
    engine = await app.store.get_engine_state(policy.name)
    cooldown = 0.0
    if engine.last_scale_at is not None:
        cooldown = max(0.0, policy.cooldown_seconds - (now - engine.last_scale_at))
    replica_statuses = [
        ReplicaStatus(
            id=r.id[:12],
            name=r.name,
            index=r.index,
            status=r.status,
        )
        for r in sorted(replicas, key=lambda r: r.index)
    ]
    return ServiceStatus(
        name=policy.name,
        desired_replicas=desired,
        actual_replicas=len(running),
        healthy=len(running),
        avg_cpu=None if snapshot is None else snapshot.get("avg_cpu"),
        avg_memory_bytes=None if snapshot is None else snapshot.get("avg_memory_bytes"),
        consecutive_high=engine.consecutive_high,
        consecutive_low=engine.consecutive_low,
        cooldown_remaining_seconds=round(cooldown, 1),
        replicas=replica_statuses,
    )


async def status_snapshot(app: Any, now: float | None = None) -> StatusResponse:
    stamp = time.time() if now is None else now
    services: list[ServiceStatus] = []
    for policy in app.policies.values():
        services.append(await service_status(app, policy, stamp))
    return StatusResponse(services=services)


async def apply_manual_scale(app: Any, service: str, replicas: int) -> ScaleResponse:
    """Idempotent: writes desired count only. Reconciler converges actual state."""
    policy: ServicePolicy | None = app.policies.get(service)
    if policy is None:
        raise UnknownServiceError(service)
    target = max(policy.min_replicas, min(replicas, policy.max_replicas))
    async with ServiceLock(app.store.r, service, timeout=30):
        await app.store.set_desired(service, target)
        running = await app.docker.list_replicas(service, all_=False)
        actual = len([r for r in running if r.status == "running"])
        event = ScalingEvent(
            ts=time.time(),
            service=service,
            action="manual_scale",
            message=f"manual override desired={target}",
            desired=target,
            actual=actual,
        )
        await app.store.append_audit(event)
        await app.events.publish(event)
        await app.loop.reconciler.reconcile(policy)
        running = await app.docker.list_replicas(service, all_=False)
        actual = len([r for r in running if r.status == "running"])
    return ScaleResponse(
        service=service,
        desired_replicas=target,
        actual_replicas=actual,
        message="desired state updated; reconciler converging",
    )


async def stop_managed(app: Any) -> list[str]:
    return await app.docker.stop_all_managed(timeout=10)


async def start_managed(app: Any) -> None:
    await app.loop.startup_reconcile()
