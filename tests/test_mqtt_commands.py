"""MQTT command parsing and dispatch without a live broker."""

from __future__ import annotations

from types import SimpleNamespace

import pytest
from fakeredis import FakeAsyncRedis

from app.api.events import EventBus
from app.config import ServicePolicy
from app.core.control import apply_manual_scale
from app.dockeriface.client import Replica
from app.dockeriface.labels import LABEL_MANAGED, LABEL_SERVICE, MANAGED_VALUE
from app.mqtt.commands import CommandError, handle_raw_command, parse_command
from app.mqtt.publisher import status_payload
from app.models import StatusResponse, ServiceStatus
from app.store.redis_store import RedisStore


class FakeDocker:
    def __init__(self) -> None:
        self.replicas: list[Replica] = []
        self.stopped: list[str] = []

    async def list_replicas(self, service: str | None = None, all_: bool = True) -> list[Replica]:
        return list(self.replicas)

    async def stop_all_managed(self, timeout: int = 10) -> list[str]:
        names = [r.name for r in self.replicas]
        self.stopped.extend(names)
        self.replicas = []
        return names


class FakeReconciler:
    async def reconcile(self, policy: ServicePolicy) -> list:
        return []


class FakeLoop:
    def __init__(self) -> None:
        self.reconciler = FakeReconciler()
        self.started = 0

    async def startup_reconcile(self) -> None:
        self.started += 1


def _policy(name: str = "demo") -> ServicePolicy:
    return ServicePolicy(
        name=name,
        image=f"scaler-{name}:latest",
        min_replicas=1,
        max_replicas=5,
    )


async def _app() -> SimpleNamespace:
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisStore(redis)
    docker = FakeDocker()
    docker.replicas = [
        Replica(
            id="a" * 64,
            name="orch-demo-0",
            index=0,
            status="running",
            labels={LABEL_MANAGED: MANAGED_VALUE, LABEL_SERVICE: "demo"},
        )
    ]
    return SimpleNamespace(
        policies={"demo": _policy()},
        store=store,
        docker=docker,
        events=EventBus(),
        loop=FakeLoop(),
        redis=redis,
    )


def test_parse_scale_command():
    cmd = parse_command('{"action":"scale","service":"alpha","replicas":2}')
    assert cmd.action == "scale"
    assert cmd.service == "alpha"
    assert cmd.replicas == 2


def test_parse_stop_and_start():
    assert parse_command(b'{"action":"stop"}').action == "stop"
    assert parse_command('{"action":"start"}').action == "start"


def test_parse_scale_requires_fields():
    with pytest.raises(CommandError):
        parse_command('{"action":"scale"}')
    with pytest.raises(CommandError):
        parse_command("not-json")
    with pytest.raises(CommandError):
        parse_command('{"action":"explode"}')


def test_status_payload_shape():
    snapshot = StatusResponse(
        services=[
            ServiceStatus(
                name="demo",
                desired_replicas=1,
                actual_replicas=1,
                healthy=1,
            )
        ]
    )
    payload = status_payload("scaler-hw-01", snapshot)
    assert payload["device_id"] == "scaler-hw-01"
    assert payload["online"] is True
    assert payload["services"][0]["name"] == "demo"


async def test_dispatch_scale_unknown_service():
    app = await _app()
    event = await handle_raw_command(
        app, '{"action":"scale","service":"missing","replicas":2}'
    )
    assert event is not None
    assert event.action == "error"
    assert "missing" in event.message


async def test_dispatch_scale_updates_desired():
    app = await _app()
    event = await handle_raw_command(
        app, '{"action":"scale","service":"demo","replicas":3}'
    )
    assert event is None
    assert await app.store.get_desired("demo") == 3


async def test_dispatch_stop_and_start():
    app = await _app()
    event = await handle_raw_command(app, '{"action":"stop"}')
    assert event is None
    assert app.docker.stopped == ["orch-demo-0"]
    event = await handle_raw_command(app, '{"action":"start"}')
    assert event is None
    assert app.loop.started == 1


async def test_apply_manual_scale_shared_helper():
    app = await _app()
    result = await apply_manual_scale(app, "demo", 2)
    assert result.service == "demo"
    assert result.desired_replicas == 2
