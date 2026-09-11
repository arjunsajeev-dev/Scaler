"""asyncio tick loop driven by APScheduler."""

from __future__ import annotations

import time
from collections.abc import Awaitable, Callable

import structlog
from apscheduler.schedulers.asyncio import AsyncIOScheduler

from scaler.api.events import EventBus
from scaler.api.metrics import OrchestratorMetrics
from scaler.collectors.docker_stats import collect_service_metrics
from scaler.config import ServicePolicy, ServicesFile
from scaler.controller.engine import evaluate
from scaler.controller.reconciler import Reconciler
from scaler.docker.client import DockerInterface
from scaler.models import ScalingEvent
from scaler.store.locks import ServiceLock
from scaler.store.redis_store import RedisStore

log = structlog.get_logger(__name__)


class ReconcileLoop:
    def __init__(
        self,
        docker: DockerInterface,
        store: RedisStore,
        runtime: ServicesFile,
        policies: dict[str, ServicePolicy],
        events: EventBus,
        metrics: OrchestratorMetrics,
        network: str,
        lock_timeout: float = 30.0,
        after_tick: Callable[[], Awaitable[None]] | None = None,
    ):
        self.docker = docker
        self.store = store
        self.runtime = runtime
        self.policies = policies
        self.events = events
        self.metrics = metrics
        self.network = network
        self.lock_timeout = lock_timeout
        self.after_tick = after_tick
        self.reconciler = Reconciler(docker, store, runtime, events, network)
        self._scheduler = AsyncIOScheduler()

    async def startup_reconcile(self) -> None:
        for policy in self.policies.values():
            if await self.store.get_desired(policy.name) is None:
                await self.store.set_desired(policy.name, policy.min_replicas)
            async with ServiceLock(self.store.r, policy.name, timeout=self.lock_timeout):
                await self.reconciler.reconcile(policy)
        log.info("startup_reconcile_complete", services=list(self.policies))

    async def tick(self) -> None:
        for policy in self.policies.values():
            try:
                await self._tick_service(policy)
            except Exception:
                log.exception("tick_failed", service=policy.name)
        if self.after_tick is not None:
            try:
                await self.after_tick()
            except Exception:
                log.exception("after_tick_failed")

    async def _tick_service(self, policy: ServicePolicy) -> None:
        async with ServiceLock(self.store.r, policy.name, timeout=self.lock_timeout):
            await collect_service_metrics(
                self.docker, self.store, policy.name, self.runtime.metrics_window
            )
            snapshot = await self.store.get_snapshot(policy.name)
            avg_cpu = None if snapshot is None else snapshot.get("avg_cpu")

            running = await self.reconciler.running(policy.name)
            actual = len(running)
            desired = await self.store.get_desired(policy.name)
            if desired is None:
                desired = policy.min_replicas
                await self.store.set_desired(policy.name, desired)

            state = await self.store.get_engine_state(policy.name)
            decision, state = evaluate(
                avg_cpu, actual, desired, policy, state, now=time.time()
            )
            await self.store.set_engine_state(policy.name, state)

            if decision.direction is not None and decision.desired != desired:
                await self.store.set_desired(policy.name, decision.desired)
                self.metrics.inc_scale(policy.name, decision.direction)
                event = ScalingEvent(
                    ts=time.time(),
                    service=policy.name,
                    action="scale_up" if decision.direction == "up" else "scale_down",
                    message=decision.reason,
                    desired=decision.desired,
                    actual=actual,
                )
                await self.store.append_audit(event)
                await self.events.publish(event)
                log.info(
                    "engine_decision",
                    service=policy.name,
                    direction=decision.direction,
                    desired=decision.desired,
                    reason=decision.reason,
                )

            await self.reconciler.reconcile(policy)
            running = await self.reconciler.running(policy.name)
            latest_desired = await self.store.get_desired(policy.name) or 0
            self.metrics.set_service(
                policy.name,
                desired=latest_desired,
                actual=len(running),
                cpu=avg_cpu,
                memory=(None if snapshot is None else snapshot.get("avg_memory_bytes")),
            )

    def start(self) -> None:
        self._scheduler.add_job(
            self.tick,
            "interval",
            seconds=self.runtime.tick_interval_seconds,
            id="reconcile",
            max_instances=1,
            coalesce=True,
        )
        self._scheduler.start()
        log.info("loop_started", interval=self.runtime.tick_interval_seconds)

    def stop(self) -> None:
        if self._scheduler.running:
            self._scheduler.shutdown(wait=False)
            log.info("loop_stopped")
