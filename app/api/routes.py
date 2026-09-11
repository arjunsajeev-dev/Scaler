"""HTTP and WebSocket API."""

from __future__ import annotations

from fastapi import APIRouter, HTTPException, Request, WebSocket, WebSocketDisconnect
from fastapi.responses import JSONResponse, PlainTextResponse

from app.core.control import (
    FileBackedServiceError,
    ServiceExistsError,
    UnknownServiceError,
    add_service,
    apply_manual_scale,
    remove_service,
    start_service,
    status_snapshot,
    stop_managed,
    stop_service,
)
from app.dockeriface.client import Replica
from app.dockeriface.labels import LABEL_SERVICE
from app.models import (
    ContainerDetail,
    ContainerSummary,
    ScaleRequest,
    ScaleResponse,
    ScalingEvent,
    ServiceCreateRequest,
    StatusResponse,
    StopManagedResponse,
)

router = APIRouter()


def _state(request: Request):
    return request.app.state


async def _ping_status(ping) -> str:
    try:
        ok = await ping()
    except Exception:
        return "down"
    return "ok" if ok else "down"


def _mqtt_health(state) -> str:
    mqtt = getattr(state, "mqtt", None)
    if mqtt is None or not getattr(mqtt, "enabled", False):
        return "disabled"
    if getattr(mqtt, "connected", False):
        return "connected"
    return "disconnected"


@router.get("/health")
async def health(request: Request) -> JSONResponse:
    state = _state(request)
    redis_status = await _ping_status(state.store.ping)
    docker_status = await _ping_status(state.docker.ping)
    mqtt_status = _mqtt_health(state)
    degraded = redis_status != "ok" or docker_status != "ok"
    body = {
        "status": "degraded" if degraded else "ok",
        "redis": redis_status,
        "docker": docker_status,
        "mqtt": mqtt_status,
    }
    return JSONResponse(body, status_code=503 if degraded else 200)


@router.get("/status", response_model=StatusResponse)
async def status(request: Request) -> StatusResponse:
    return await status_snapshot(_state(request))


@router.post("/scale/{service}", response_model=ScaleResponse)
async def scale(service: str, body: ScaleRequest, request: Request) -> ScaleResponse:
    """Idempotent: writes desired count only. Reconciler converges actual state."""
    try:
        return await apply_manual_scale(_state(request), service, body.replicas)
    except UnknownServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/services", response_model=ScaleResponse)
async def create_service(body: ServiceCreateRequest, request: Request) -> ScaleResponse:
    try:
        return await add_service(
            _state(request), body.name, body.image, **body.policy_overrides()
        )
    except ServiceExistsError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc
    except FileBackedServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.delete("/services/{name}", response_model=ScaleResponse)
async def delete_service(name: str, request: Request) -> ScaleResponse:
    try:
        return await remove_service(_state(request), name)
    except UnknownServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    except FileBackedServiceError as exc:
        raise HTTPException(status_code=409, detail=str(exc)) from exc


@router.post("/services/{name}/start", response_model=ScaleResponse)
async def start_named_service(name: str, request: Request) -> ScaleResponse:
    try:
        return await start_service(_state(request), name)
    except UnknownServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


@router.post("/services/{name}/stop", response_model=ScaleResponse)
async def stop_named_service(name: str, request: Request) -> ScaleResponse:
    try:
        return await stop_service(_state(request), name)
    except UnknownServiceError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc


def _replica_summary(replica: Replica) -> ContainerSummary:
    return ContainerSummary(
        id=replica.id[:12],
        name=replica.name,
        service=replica.labels.get(LABEL_SERVICE, ""),
        index=replica.index,
        status=replica.status,
    )


@router.get("/containers", response_model=list[ContainerSummary])
async def list_containers(request: Request) -> list[ContainerSummary]:
    replicas = await _state(request).docker.list_replicas(service=None, all_=True)
    return [_replica_summary(r) for r in sorted(replicas, key=lambda r: (r.name, r.index))]


@router.get("/containers/{name}", response_model=ContainerDetail)
async def get_container(name: str, request: Request) -> ContainerDetail:
    inspected = await _state(request).docker.inspect_managed(name)
    if inspected is None:
        raise HTTPException(status_code=404, detail=f"container {name!r} not found")
    return ContainerDetail(
        id=inspected.id[:12],
        name=inspected.name,
        service=inspected.service,
        index=inspected.index,
        status=inspected.status,
        image=inspected.image,
        created=inspected.created,
        state=inspected.state,
        cpu_percent=inspected.cpu_percent,
        memory_bytes=inspected.memory_bytes,
        labels=inspected.labels,
    )


@router.get("/containers/{name}/logs")
async def container_logs(
    name: str, request: Request, tail: int = 200
) -> PlainTextResponse:
    if tail < 1:
        raise HTTPException(status_code=422, detail="tail must be >= 1")
    payload = await _state(request).docker.get_logs(name, tail=tail)
    if payload is None:
        raise HTTPException(status_code=404, detail=f"container {name!r} not found")
    return PlainTextResponse(payload)


@router.post("/containers/stop-all", response_model=StopManagedResponse)
async def stop_all_containers(request: Request) -> StopManagedResponse:
    """Sticky host-wide stop: desired=0 for every service, then kill replicas."""
    names = await stop_managed(_state(request))
    return StopManagedResponse(
        stopped=names,
        message=f"stopped {len(names)} managed container(s)",
    )


@router.get("/metrics")
async def metrics(request: Request) -> PlainTextResponse:
    payload = _state(request).metrics.render()
    return PlainTextResponse(payload, media_type="text/plain; version=0.0.4; charset=utf-8")


@router.websocket("/events")
async def events_ws(websocket: WebSocket) -> None:
    await websocket.accept()
    bus = websocket.app.state.events
    queue = bus.subscribe()
    try:
        while True:
            event: ScalingEvent = await queue.get()
            await websocket.send_json(event.model_dump())
    except WebSocketDisconnect:
        pass
    finally:
        bus.unsubscribe(queue)
