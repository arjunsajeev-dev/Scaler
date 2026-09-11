"""Shared scale / status helpers used by the HTTP API and MQTT commands."""

from __future__ import annotations

import time
from typing import Any

from scaler.config import ServicePolicy
from scaler.controller.policies import PolicyRegistry, build_policy
from scaler.docker.client import Replica
from scaler.models import ReplicaStatus, ScaleResponse, ScalingEvent, ServiceStatus, StatusResponse
from scaler.store.locks import ServiceLock


class UnknownServiceError(LookupError):
    def __init__(self, service: str):
        self.service = service
        super().__init__(f"unknown service {service!r}")


class FileBackedServiceError(ValueError):
    def __init__(self, service: str, action: str = "remove"):
        self.service = service
        if action == "remove":
            message = f"cannot remove file-defined service {service!r}; stop it instead"
        else:
            message = f"cannot {action} file-defined service {service!r}"
        super().__init__(message)


class ServiceExistsError(ValueError):
    def __init__(self, service: str):
        self.service = service
        super().__init__(f"file-defined service {service!r} already exists")


def _registry(app: Any) -> PolicyRegistry:
    registry = getattr(app, "policy_registry", None)
    if registry is None:
        registry = PolicyRegistry(file_names=set(app.policies), policies=app.policies)
        app.policy_registry = registry
    return registry


async def _running_count(app: Any, service: str) -> int:
    running = await app.docker.list_replicas(service, all_=False)
    return len([r for r in running if r.status == "running"])


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


async def _publish_status(app: Any) -> None:
    mqtt = getattr(app, "mqtt", None)
    if mqtt is not None:
        await mqtt.publish_status()


async def apply_manual_scale(app: Any, service: str, replicas: int) -> ScaleResponse:
    """Idempotent: writes desired count only. Reconciler converges actual state."""
    policy: ServicePolicy | None = app.policies.get(service)
    if policy is None:
        raise UnknownServiceError(service)
    target = max(policy.min_replicas, min(replicas, policy.max_replicas))
    async with ServiceLock(app.store.r, service, timeout=30):
        await app.store.set_desired(service, target)
        actual = await _running_count(app, service)
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
        actual = await _running_count(app, service)
    await _publish_status(app)
    return ScaleResponse(
        service=service,
        desired_replicas=target,
        actual_replicas=actual,
        message="desired state updated; reconciler converging",
    )


async def stop_service(app: Any, service: str) -> ScaleResponse:
    policy: ServicePolicy | None = app.policies.get(service)
    if policy is None:
        raise UnknownServiceError(service)
    async with ServiceLock(app.store.r, service, timeout=30):
        await app.store.set_desired(service, 0)
        actual = await _running_count(app, service)
        event = ScalingEvent(
            ts=time.time(),
            service=service,
            action="service_stop",
            message="stopped service (desired=0)",
            desired=0,
            actual=actual,
        )
        await app.store.append_audit(event)
        await app.events.publish(event)
        await app.loop.reconciler.reconcile(policy)
        actual = await _running_count(app, service)
    await _publish_status(app)
    return ScaleResponse(
        service=service,
        desired_replicas=0,
        actual_replicas=actual,
        message="service stopped; replicas draining",
    )


async def start_service(app: Any, service: str) -> ScaleResponse:
    policy: ServicePolicy | None = app.policies.get(service)
    if policy is None:
        raise UnknownServiceError(service)
    current = await app.store.get_desired(service)
    if current is None or current <= 0:
        target = max(policy.min_replicas, 1)
    else:
        target = current
    async with ServiceLock(app.store.r, service, timeout=30):
        await app.store.set_desired(service, target)
        actual = await _running_count(app, service)
        event = ScalingEvent(
            ts=time.time(),
            service=service,
            action="service_start",
            message=f"started service desired={target}",
            desired=target,
            actual=actual,
        )
        await app.store.append_audit(event)
        await app.events.publish(event)
        await app.loop.reconciler.reconcile(policy)
        actual = await _running_count(app, service)
    await _publish_status(app)
    return ScaleResponse(
        service=service,
        desired_replicas=target,
        actual_replicas=actual,
        message="service started; reconciler converging",
    )


async def add_service(app: Any, name: str, image: str, **overrides: Any) -> ScaleResponse:
    registry = _registry(app)
    if registry.is_file_backed(name):
        raise ServiceExistsError(name)
    policy = build_policy(name, image, **overrides)
    registry.policies[name] = policy
    await app.store.upsert_dynamic_policy(policy)
    target = policy.min_replicas
    async with ServiceLock(app.store.r, name, timeout=30):
        await app.store.set_desired(name, target)
        event = ScalingEvent(
            ts=time.time(),
            service=name,
            action="service_add",
            message=f"added service image={policy.image}",
            desired=target,
            actual=0,
        )
        await app.store.append_audit(event)
        await app.events.publish(event)
        await app.loop.reconciler.reconcile(policy)
        actual = await _running_count(app, name)
    await _publish_status(app)
    return ScaleResponse(
        service=name,
        desired_replicas=target,
        actual_replicas=actual,
        message="service added; reconciler converging",
    )


async def remove_service(app: Any, service: str) -> ScaleResponse:
    registry = _registry(app)
    policy: ServicePolicy | None = app.policies.get(service)
    if policy is None:
        raise UnknownServiceError(service)
    if registry.is_file_backed(service):
        raise FileBackedServiceError(service, "remove")
    async with ServiceLock(app.store.r, service, timeout=30):
        await app.store.set_desired(service, 0)
        await app.loop.reconciler.reconcile(policy)
        actual = await _running_count(app, service)
        event = ScalingEvent(
            ts=time.time(),
            service=service,
            action="service_remove",
            message="removed dynamic service",
            desired=0,
            actual=actual,
        )
        await app.store.append_audit(event)
        await app.events.publish(event)
        registry.policies.pop(service, None)
        await app.store.remove_dynamic_policy(service)
        await app.store.clear_service_state(service)
    await _publish_status(app)
    return ScaleResponse(
        service=service,
        desired_replicas=0,
        actual_replicas=actual,
        message="dynamic service removed",
    )


async def stop_managed(app: Any) -> list[str]:
    """Sticky host-wide stop: desired=0 for every service, then kill replicas."""
    for name, _policy in list(app.policies.items()):
        async with ServiceLock(app.store.r, name, timeout=30):
            await app.store.set_desired(name, 0)
            actual = await _running_count(app, name)
            event = ScalingEvent(
                ts=time.time(),
                service=name,
                action="service_stop",
                message="stopped service (desired=0)",
                desired=0,
                actual=actual,
            )
            await app.store.append_audit(event)
            await app.events.publish(event)
    names = await app.docker.stop_all_managed(timeout=10)
    await _publish_status(app)
    return names


async def start_managed(app: Any) -> None:
    """Bring every service back: restore desired=0 to min_replicas, then reconcile."""
    for name in list(app.policies):
        await start_service(app, name)
    await _publish_status(app)
