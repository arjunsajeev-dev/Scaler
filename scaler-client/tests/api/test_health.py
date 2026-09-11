"""GET /health probes Redis and Docker; MQTT is informational."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient
from fakeredis import FakeAsyncRedis

from scaler.api.routes import router
from scaler.store.redis_store import RedisStore


class OkDocker:
    async def ping(self) -> bool:
        return True


class DownDocker:
    async def ping(self) -> bool:
        raise ConnectionError("docker down")


class DownStore:
    async def ping(self) -> bool:
        raise ConnectionError("redis down")


class FakeMqtt:
    def __init__(self, enabled: bool = True, connected: bool = True) -> None:
        self.enabled = enabled
        self.connected = connected


def _client(store, docker, mqtt=None) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.store = store
    app.state.docker = docker
    if mqtt is not None:
        app.state.mqtt = mqtt
    return TestClient(app)


def test_health_ok_mqtt_connected():
    store = RedisStore(FakeAsyncRedis(decode_responses=True))
    client = _client(store, OkDocker(), FakeMqtt(enabled=True, connected=True))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json() == {
        "status": "ok",
        "redis": "ok",
        "docker": "ok",
        "mqtt": "connected",
    }


def test_health_mqtt_disconnected_still_ok():
    store = RedisStore(FakeAsyncRedis(decode_responses=True))
    client = _client(store, OkDocker(), FakeMqtt(enabled=True, connected=False))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mqtt"] == "disconnected"
    assert resp.json()["status"] == "ok"


def test_health_mqtt_disabled():
    store = RedisStore(FakeAsyncRedis(decode_responses=True))
    client = _client(store, OkDocker(), FakeMqtt(enabled=False, connected=False))
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mqtt"] == "disabled"


def test_health_mqtt_absent_is_disabled():
    store = RedisStore(FakeAsyncRedis(decode_responses=True))
    client = _client(store, OkDocker())
    resp = client.get("/health")
    assert resp.status_code == 200
    assert resp.json()["mqtt"] == "disabled"


def test_health_docker_down():
    store = RedisStore(FakeAsyncRedis(decode_responses=True))
    client = _client(store, DownDocker(), FakeMqtt())
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["docker"] == "down"
    assert body["redis"] == "ok"


def test_health_redis_down():
    client = _client(DownStore(), OkDocker(), FakeMqtt())
    resp = client.get("/health")
    assert resp.status_code == 503
    body = resp.json()
    assert body["status"] == "degraded"
    assert body["redis"] == "down"
    assert body["docker"] == "ok"
