"""Container list / detail / logs HTTP API."""

from __future__ import annotations

from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api.routes import router
from app.dockeriface.client import ContainerInspect, Replica
from app.dockeriface.labels import LABEL_MANAGED, LABEL_SERVICE, MANAGED_VALUE


class FakeDocker:
    def __init__(self) -> None:
        self.replicas: list[Replica] = []
        self.inspected: dict[str, ContainerInspect] = {}
        self.logs: dict[str, str] = {}

    async def list_replicas(self, service: str | None = None, all_: bool = True) -> list[Replica]:
        return list(self.replicas)

    async def inspect_managed(self, name: str) -> ContainerInspect | None:
        return self.inspected.get(name)

    async def get_logs(self, name: str, tail: int = 200) -> str | None:
        return self.logs.get(name)

    async def stop_all_managed(self, timeout: int = 10) -> list[str]:
        names = [r.name for r in self.replicas]
        self.replicas = []
        return names


def _app(docker: FakeDocker) -> TestClient:
    app = FastAPI()
    app.include_router(router)
    app.state.docker = docker
    return TestClient(app)


def _replica(name: str = "orch-demo-0", index: int = 0) -> Replica:
    return Replica(
        id="a" * 64,
        name=name,
        index=index,
        status="running",
        labels={LABEL_MANAGED: MANAGED_VALUE, LABEL_SERVICE: "demo"},
    )


def _inspect(name: str = "orch-demo-0") -> ContainerInspect:
    return ContainerInspect(
        id="a" * 64,
        name=name,
        service="demo",
        index=0,
        status="running",
        state="running",
        image="scaler-demo:latest",
        created="2026-09-10T10:00:00Z",
        cpu_percent=12.5,
        memory_bytes=8_388_608,
        labels={LABEL_MANAGED: MANAGED_VALUE, LABEL_SERVICE: "demo"},
    )


def test_list_containers_empty():
    client = _app(FakeDocker())
    resp = client.get("/containers")
    assert resp.status_code == 200
    assert resp.json() == []


def test_list_containers_summaries():
    docker = FakeDocker()
    docker.replicas = [_replica("orch-demo-1", 1), _replica("orch-demo-0", 0)]
    client = _app(docker)
    resp = client.get("/containers")
    assert resp.status_code == 200
    names = [row["name"] for row in resp.json()]
    assert names == ["orch-demo-0", "orch-demo-1"]
    assert resp.json()[0]["id"] == "a" * 12
    assert resp.json()[0]["service"] == "demo"
    assert resp.json()[0]["status"] == "running"


def test_get_container_detail():
    docker = FakeDocker()
    docker.inspected["orch-demo-0"] = _inspect()
    client = _app(docker)
    resp = client.get("/containers/orch-demo-0")
    assert resp.status_code == 200
    body = resp.json()
    assert body["name"] == "orch-demo-0"
    assert body["image"] == "scaler-demo:latest"
    assert body["state"] == "running"
    assert body["cpu_percent"] == 12.5
    assert body["memory_bytes"] == 8_388_608
    assert body["labels"]["orchestrator.managed"] == "true"


def test_get_container_unknown_404():
    client = _app(FakeDocker())
    resp = client.get("/containers/missing")
    assert resp.status_code == 404
    assert "missing" in resp.json()["detail"]


def test_container_logs():
    docker = FakeDocker()
    docker.logs["orch-demo-0"] = "line one\nline two\n"
    client = _app(docker)
    resp = client.get("/containers/orch-demo-0/logs?tail=50")
    assert resp.status_code == 200
    assert resp.text == "line one\nline two\n"


def test_container_logs_unknown_404():
    client = _app(FakeDocker())
    resp = client.get("/containers/ghost/logs")
    assert resp.status_code == 404


def test_container_logs_bad_tail():
    client = _app(FakeDocker())
    resp = client.get("/containers/orch-demo-0/logs?tail=0")
    assert resp.status_code == 422


def test_stop_all_managed_containers():
    docker = FakeDocker()
    docker.replicas = [_replica("orch-alpha-0", 0), _replica("orch-beta-0", 0)]
    client = _app(docker)
    resp = client.post("/containers/stop-all")
    assert resp.status_code == 200
    body = resp.json()
    assert body["stopped"] == ["orch-alpha-0", "orch-beta-0"]
    assert docker.replicas == []
