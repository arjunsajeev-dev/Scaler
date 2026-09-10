"""Converge actual replica count toward desired. Idempotent create/remove."""

from __future__ import annotations

import asyncio
import time

import structlog
from docker.errors import ImageNotFound

from app.api.events import EventBus
from app.config import ServicePolicy, ServicesFile
from app.dockeriface.client import DockerInterface, Replica
from app.models import ScalingEvent
from app.store.redis_store import RedisStore

log = structlog.get_logger(__name__)


def unused_indices(used: set[int], count: int) -> list[int]:
    """Fill index holes from 0 upward."""
    out: list[int] = []
    i = 0
    while len(out) < count:
        if i not in used:
            out.append(i)
        i += 1
    return out


class Reconciler:
    def __init__(
        self,
        docker: DockerInterface,
        store: RedisStore,
        runtime: ServicesFile,
        events: EventBus,
        network: str,
    ):
        self.docker = docker
        self.store = store
        self.runtime = runtime
        self.events = events
        self.network = network

    async def _emit(self, event: ScalingEvent) -> None:
        await self.store.append_audit(event)
        await self.events.publish(event)

    async def running(self, service: str) -> list[Replica]:
        replicas = await self.docker.list_replicas(service, all_=True)
        running: list[Replica] = []
        for replica in replicas:
            if replica.status == "running":
                running.append(replica)
            else:
                log.info("removing_exited_replica", name=replica.name, status=replica.status)
                await self.docker.stop_and_remove(
                    replica.id, timeout=self.runtime.stop_timeout_seconds
                )
                await self.store.delete_cpu_prev(replica.id)
        return running

    async def reconcile(self, policy: ServicePolicy) -> list[Replica]:
        desired = await self.store.get_desired(policy.name)
        if desired is None:
            desired = policy.min_replicas
            await self.store.set_desired(policy.name, desired)
        desired = max(policy.min_replicas, min(desired, policy.max_replicas))

        running = await self.running(policy.name)
        actual = len(running)

        if actual == desired:
            return running

        if actual < desired:
            used = {r.index for r in running}
            to_create = unused_indices(used, desired - actual)
            for index in to_create:
                try:
                    replica = await self.docker.create_replica(
                        policy, index, self.network
                    )
                except ImageNotFound as exc:
                    await self._emit(
                        ScalingEvent(
                            ts=time.time(),
                            service=policy.name,
                            action="error",
                            message=str(exc),
                            desired=desired,
                            actual=actual,
                        )
                    )
                    log.error("image_missing", service=policy.name, image=policy.image)
                    break
                except Exception as exc:
                    await self._emit(
                        ScalingEvent(
                            ts=time.time(),
                            service=policy.name,
                            action="error",
                            message=f"failed to create replica {index}: {exc}",
                            desired=desired,
                            actual=actual,
                        )
                    )
                    log.exception("create_failed", service=policy.name, index=index)
                    break
                actual += 1
                running.append(replica)
                await self._emit(
                    ScalingEvent(
                        ts=time.time(),
                        service=policy.name,
                        action="reconcile_create",
                        message=f"created {replica.name}",
                        desired=desired,
                        actual=actual,
                    )
                )
            return running

        # Scale down: highest index first. Drain wait, then stop(timeout=30).
        victims = sorted(running, key=lambda r: r.index, reverse=True)[: actual - desired]
        for replica in victims:
            await self._emit(
                ScalingEvent(
                    ts=time.time(),
                    service=policy.name,
                    action="drain",
                    message=(
                        f"draining {replica.name} "
                        f"({self.runtime.drain_seconds:.0f}s) before stop"
                    ),
                    desired=desired,
                    actual=actual,
                )
            )
            await self.docker.disable_traefik(replica.id)
            if self.runtime.drain_seconds > 0:
                await asyncio.sleep(self.runtime.drain_seconds)
            await self.docker.stop_and_remove(
                replica.id, timeout=self.runtime.stop_timeout_seconds
            )
            await self.store.delete_cpu_prev(replica.id)
            actual -= 1
            running = [r for r in running if r.id != replica.id]
            await self._emit(
                ScalingEvent(
                    ts=time.time(),
                    service=policy.name,
                    action="reconcile_remove",
                    message=f"stopped and removed {replica.name}",
                    desired=desired,
                    actual=actual,
                )
            )
        return running
