"""FastAPI entrypoint: lifespan starts startup reconcile + the tick loop."""

from __future__ import annotations

import asyncio
import logging
from contextlib import asynccontextmanager

import structlog
from fastapi import FastAPI
from redis.asyncio import Redis

from scaler.api.events import EventBus
from scaler.api.metrics import OrchestratorMetrics
from scaler.api.routes import router
from scaler.config import get_runtime_file, get_settings
from scaler.controller.loop import ReconcileLoop
from scaler.controller.policies import load_live_policies
from scaler.docker.client import DockerInterface
from scaler.mqtt.client import create_mqtt_bridge
from scaler.mqtt.discovery import MdnsAdvertiser
from scaler.store.redis_store import RedisStore

structlog.configure(
    processors=[
        structlog.contextvars.merge_contextvars,
        structlog.processors.add_log_level,
        structlog.processors.TimeStamper(fmt="iso"),
        structlog.dev.ConsoleRenderer(),
    ]
)
log = structlog.get_logger("scaler")


@asynccontextmanager
async def lifespan(app: FastAPI):
    settings = get_settings()
    logging.basicConfig(level=getattr(logging, settings.log_level.upper(), logging.INFO))
    runtime = get_runtime_file()
    network = settings.docker_network or runtime.docker_network

    redis = Redis.from_url(settings.redis_url, decode_responses=True)
    store = RedisStore(redis)
    policies, registry = await load_live_policies(settings.services_path(), store)
    docker = DockerInterface(
        base_url=settings.docker_host,
        max_concurrency=settings.docker_concurrency,
    )
    events = EventBus()
    metrics = OrchestratorMetrics()
    loop = ReconcileLoop(
        docker=docker,
        store=store,
        runtime=runtime,
        policies=policies,
        events=events,
        metrics=metrics,
        network=network,
    )

    await store.ping()
    await docker.ping()
    log.info(
        "connected",
        redis=settings.redis_url,
        docker=settings.docker_host,
        network=network,
        services=list(policies),
        mqtt_enabled=settings.mqtt_enabled,
        mqtt_mdns=settings.mqtt_mdns,
    )

    app.state.settings = settings
    app.state.runtime = runtime
    app.state.policies = policies
    app.state.policy_registry = registry
    app.state.store = store
    app.state.docker = docker
    app.state.events = events
    app.state.metrics = metrics
    app.state.loop = loop
    app.state.redis = redis

    mqtt = create_mqtt_bridge(settings, app.state, events)
    app.state.mqtt = mqtt
    loop.after_tick = mqtt.publish_status
    advertiser = MdnsAdvertiser(settings)
    app.state.mdns = advertiser

    # Zeroconf sync register can block; never fail orchestrator startup on mDNS.
    await asyncio.to_thread(advertiser.start)
    await mqtt.start()
    await loop.startup_reconcile()
    loop.start()
    try:
        yield
    finally:
        loop.stop()
        try:
            await mqtt.publish_offline()
        except Exception:
            log.exception("mqtt_offline_publish_failed")
        await mqtt.stop()
        try:
            advertiser.stop()
        except Exception:
            log.exception("mdns_unadvertise_failed")
        try:
            stopped = await docker.stop_all_managed(timeout=10)
            log.info("managed_replicas_stopped", containers=stopped)
        except Exception:
            log.exception("failed_to_stop_managed_replicas")
        await docker.close()
        await redis.aclose()


app = FastAPI(
    title="Docker Autoscaler",
    description="Control-loop orchestrator that reconciles desired vs actual Docker replicas.",
    version="0.1.0",
    lifespan=lifespan,
)
app.include_router(router)
