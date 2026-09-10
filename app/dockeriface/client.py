"""Thin async wrapper around docker-py talking to the socket proxy."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from typing import Any, Callable, TypeVar

import docker
from docker.errors import APIError, ImageNotFound, NotFound
from docker.models.containers import Container

from app.config import ServicePolicy
from app.dockeriface.labels import LABEL_INDEX, LABEL_MANAGED, LABEL_SERVICE, MANAGED_VALUE
from app.dockeriface.templates import nano_cpus, render_labels, replica_name

T = TypeVar("T")


@dataclass
class Replica:
    id: str
    name: str
    index: int
    status: str
    labels: dict[str, str]

    @classmethod
    def from_container(cls, container: Container) -> Replica:
        labels = dict(container.labels or {})
        try:
            index = int(labels.get(LABEL_INDEX, "0"))
        except ValueError:
            index = 0
        return cls(
            id=container.id,
            name=container.name or container.short_id,
            index=index,
            status=container.status,
            labels=labels,
        )


@dataclass
class ContainerInspect:
    id: str
    name: str
    service: str
    index: int
    status: str
    state: str
    image: str
    created: str
    cpu_percent: float | None
    memory_bytes: int | None
    labels: dict[str, str]


class DockerInterface:
    def __init__(self, base_url: str | None = None, max_concurrency: int = 8):
        if base_url:
            self._client = docker.DockerClient(base_url=base_url)
        else:
            self._client = docker.from_env()
        self._sem = asyncio.Semaphore(max_concurrency)

    async def _run(self, fn: Callable[..., T], *args: Any, **kwargs: Any) -> T:
        async with self._sem:
            return await asyncio.to_thread(fn, *args, **kwargs)

    async def ping(self) -> bool:
        return await self._run(self._client.ping)

    async def close(self) -> None:
        await self._run(self._client.close)

    def _list_sync(self, service: str | None, all_: bool) -> list[Replica]:
        filters: dict[str, list[str]] = {"label": [f"{LABEL_MANAGED}={MANAGED_VALUE}"]}
        if service:
            filters["label"].append(f"{LABEL_SERVICE}={service}")
        containers = self._client.containers.list(all=all_, filters=filters)
        return [Replica.from_container(c) for c in containers]

    async def list_replicas(self, service: str | None = None, all_: bool = True) -> list[Replica]:
        return await self._run(self._list_sync, service, all_)

    def _get_managed_sync(self, name: str) -> Container | None:
        try:
            container = self._client.containers.get(name)
        except NotFound:
            return None
        labels = container.labels or {}
        if labels.get(LABEL_MANAGED) != MANAGED_VALUE:
            return None
        return container

    def _cpu_and_memory(self, container: Container) -> tuple[float | None, int | None]:
        if container.status != "running":
            return None, None
        try:
            stats = container.stats(stream=False)
        except APIError:
            return None, None
        mem: int | None = None
        memory_stats = stats.get("memory_stats") or {}
        usage = memory_stats.get("usage")
        if usage is not None:
            detail = memory_stats.get("stats") or {}
            cache = int(detail.get("cache") or detail.get("inactive_file") or 0)
            mem = max(int(usage) - cache, 0)
        cpu: float | None = None
        cpu_stats = stats.get("cpu_stats") or {}
        precpu = stats.get("precpu_stats") or {}
        total = (cpu_stats.get("cpu_usage") or {}).get("total_usage")
        system = cpu_stats.get("system_cpu_usage")
        prev_total = (precpu.get("cpu_usage") or {}).get("total_usage")
        prev_system = precpu.get("system_cpu_usage")
        online = cpu_stats.get("online_cpus") or len(
            (cpu_stats.get("cpu_usage") or {}).get("percpu_usage") or []
        ) or 1
        if (
            total is not None
            and system is not None
            and prev_total is not None
            and prev_system is not None
        ):
            cpu_delta = total - prev_total
            system_delta = system - prev_system
            if cpu_delta >= 0 and system_delta > 0:
                cpu = (cpu_delta / system_delta) * int(online) * 100.0
        return cpu, mem

    def _inspect_managed_sync(self, name: str) -> ContainerInspect | None:
        container = self._get_managed_sync(name)
        if container is None:
            return None
        container.reload()
        replica = Replica.from_container(container)
        attrs = container.attrs or {}
        config = attrs.get("Config") or {}
        state = attrs.get("State") or {}
        image = config.get("Image") or ""
        if not image:
            tags = getattr(container.image, "tags", None) or []
            image = tags[0] if tags else (container.image.short_id if container.image else "")
        cpu, mem = self._cpu_and_memory(container)
        return ContainerInspect(
            id=replica.id,
            name=replica.name,
            service=replica.labels.get(LABEL_SERVICE, ""),
            index=replica.index,
            status=replica.status,
            state=str(state.get("Status") or replica.status),
            image=str(image),
            created=str(attrs.get("Created") or ""),
            cpu_percent=cpu,
            memory_bytes=mem,
            labels=replica.labels,
        )

    async def inspect_managed(self, name: str) -> ContainerInspect | None:
        return await self._run(self._inspect_managed_sync, name)

    def _logs_sync(self, name: str, tail: int) -> str | None:
        container = self._get_managed_sync(name)
        if container is None:
            return None
        raw = container.logs(tail=tail, stdout=True, stderr=True, timestamps=True)
        if isinstance(raw, bytes):
            return raw.decode(errors="replace")
        return str(raw)

    async def get_logs(self, name: str, tail: int = 200) -> str | None:
        return await self._run(self._logs_sync, name, tail)

    def _create_sync(self, policy: ServicePolicy, index: int, network: str) -> Replica:
        name = replica_name(policy.name, index)
        labels = render_labels(policy, index)
        try:
            existing = self._client.containers.get(name)
        except NotFound:
            existing = None
        if existing is not None:
            existing.reload()
            if existing.status != "running":
                existing.start()
                existing.reload()
            return Replica.from_container(existing)

        kwargs: dict[str, Any] = {
            "image": policy.image,
            "name": name,
            "labels": labels,
            "detach": True,
            "network": network,
            "nano_cpus": nano_cpus(policy.cpu_limit),
            "mem_limit": policy.memory_limit,
            "restart_policy": {"Name": "unless-stopped"},
        }
        if policy.command:
            kwargs["command"] = policy.command
        try:
            container = self._client.containers.run(**kwargs)
        except ImageNotFound as exc:
            raise ImageNotFound(
                f"image {policy.image!r} is not present locally; "
                "the socket proxy cannot pull images. Pre-pull it on the host."
            ) from exc
        except APIError:
            # Name race: another worker created it first.
            container = self._client.containers.get(name)
            if container.status != "running":
                container.start()
        container.reload()
        return Replica.from_container(container)

    async def create_replica(
        self, policy: ServicePolicy, index: int, network: str
    ) -> Replica:
        return await self._run(self._create_sync, policy, index, network)

    def _stop_remove_sync(self, container_id: str, timeout: int) -> None:
        try:
            container = self._client.containers.get(container_id)
        except NotFound:
            return
        try:
            container.stop(timeout=timeout)
        except APIError:
            pass
        try:
            container.remove(force=True)
        except (NotFound, APIError):
            pass

    async def stop_and_remove(self, container_id: str, timeout: int) -> None:
        await self._run(self._stop_remove_sync, container_id, timeout)

    def _stop_all_managed_sync(self, timeout: int) -> list[str]:
        names: list[str] = []
        for replica in self._list_sync(None, True):
            self._stop_remove_sync(replica.id, timeout)
            names.append(replica.name)
        return names

    async def stop_all_managed(self, timeout: int = 10) -> list[str]:
        return await self._run(self._stop_all_managed_sync, timeout)

    def _stats_sync(self, container_id: str) -> dict[str, Any] | None:
        try:
            container = self._client.containers.get(container_id)
        except NotFound:
            return None
        return container.stats(stream=False)

    async def stats(self, container_id: str) -> dict[str, Any] | None:
        return await self._run(self._stats_sync, container_id)

    def _disable_traefik_sync(self, container_id: str) -> bool:
        """Best-effort drain. Docker labels are immutable, so we disconnect
        nothing here; callers still wait drain_seconds then stop(). Returns
        False because labels cannot be mutated on a running container."""
        try:
            self._client.containers.get(container_id)
        except NotFound:
            return False
        return False

    async def disable_traefik(self, container_id: str) -> bool:
        return await self._run(self._disable_traefik_sync, container_id)
