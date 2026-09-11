"""HTTP service lifecycle: add / remove / start / stop."""

from __future__ import annotations

from fastapi import FastAPI
from httpx import ASGITransport, AsyncClient
from fakeredis import FakeAsyncRedis

from scaler.api.events import EventBus
from scaler.api.routes import router
from scaler.config import ServicePolicy
from scaler.controller.policies import PolicyRegistry
from scaler.docker.client import Replica
from scaler.docker.labels import LABEL_MANAGED, LABEL_SERVICE, MANAGED_VALUE
from scaler.store.redis_store import RedisStore


class FakeReconciler:
    async def reconcile(self, policy: ServicePolicy) -> list:
        return []


class FakeLoop:
    def __init__(self) -> None:
        self.reconciler = FakeReconciler()


class FakeMqtt:
    def __init__(self) -> None:
        self.status_publishes = 0

    async def publish_status(self) -> None:
        self.status_publishes += 1


class FakeDocker:
    def __init__(self) -> None:
        self.replicas: list[Replica] = []

    async def list_replicas(self, service: str | None = None, all_: bool = True) -> list[Replica]:
        if service is None:
            return list(self.replicas)
        return [r for r in self.replicas if r.labels.get(LABEL_SERVICE) == service]


def _policy(name: str = "demo") -> ServicePolicy:
    return ServicePolicy(name=name, image=f"scaler-{name}:latest", min_replicas=1, max_replicas=5)


def _app() -> tuple[FastAPI, RedisStore, dict[str, ServicePolicy]]:
    redis = FakeAsyncRedis(decode_responses=True)
    store = RedisStore(redis)
    policies = {"demo": _policy()}
    app = FastAPI()
    app.include_router(router)
    app.state.store = store
    app.state.policies = policies
    app.state.policy_registry = PolicyRegistry(file_names={"demo"}, policies=policies)
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
    app.state.docker = docker
    app.state.events = EventBus()
    app.state.loop = FakeLoop()
    app.state.mqtt = FakeMqtt()
    return app, store, policies


async def _client(app: FastAPI) -> AsyncClient:
    return AsyncClient(transport=ASGITransport(app=app), base_url="http://test")


async def test_stop_and_start_named_service():
    app, _store, _policies = _app()
    async with await _client(app) as client:
        resp = await client.post("/services/demo/stop")
        assert resp.status_code == 200
        assert resp.json()["desired_replicas"] == 0
        resp = await client.post("/services/demo/start")
        assert resp.status_code == 200
        assert resp.json()["desired_replicas"] == 1
    assert app.state.mqtt.status_publishes == 2


async def test_add_and_delete_dynamic_service():
    app, _store, policies = _app()
    async with await _client(app) as client:
        resp = await client.post(
            "/services",
            json={"name": "gamma", "image": "scaler-gamma:latest", "min_replicas": 1},
        )
        assert resp.status_code == 200
        assert "gamma" in policies
        assert policies["gamma"].traefik.rule == "PathPrefix(`/gamma`)"
        resp = await client.delete("/services/gamma")
        assert resp.status_code == 200
        assert "gamma" not in policies


async def test_cannot_delete_file_service():
    app, _store, policies = _app()
    async with await _client(app) as client:
        resp = await client.delete("/services/demo")
        assert resp.status_code == 409
        assert "demo" in policies


async def test_cannot_add_file_service():
    app, _store, _policies = _app()
    async with await _client(app) as client:
        resp = await client.post("/services", json={"name": "demo", "image": "other:latest"})
        assert resp.status_code == 409


async def test_unknown_service_404():
    app, _store, _policies = _app()
    async with await _client(app) as client:
        assert (await client.post("/services/missing/stop")).status_code == 404
        assert (await client.delete("/services/missing")).status_code == 404
