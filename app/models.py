"""API and internal domain models."""

from __future__ import annotations

from typing import Literal

from typing import Any

from pydantic import BaseModel, Field


class ScaleRequest(BaseModel):
    replicas: int = Field(..., ge=0)


class ReplicaStatus(BaseModel):
    id: str
    name: str
    index: int
    status: str
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    net_rx_bytes: int | None = None
    net_tx_bytes: int | None = None


class ServiceStatus(BaseModel):
    name: str
    desired_replicas: int
    actual_replicas: int
    healthy: int
    avg_cpu: float | None = None
    avg_memory_bytes: float | None = None
    consecutive_high: int = 0
    consecutive_low: int = 0
    cooldown_remaining_seconds: float = 0
    replicas: list[ReplicaStatus] = Field(default_factory=list)


class StatusResponse(BaseModel):
    services: list[ServiceStatus]


class ContainerSummary(BaseModel):
    id: str
    name: str
    service: str
    index: int
    status: str


class ContainerDetail(ContainerSummary):
    image: str
    created: str
    state: str
    cpu_percent: float | None = None
    memory_bytes: int | None = None
    labels: dict[str, str] = Field(default_factory=dict)


class StopManagedResponse(BaseModel):
    stopped: list[str]
    message: str


class ScaleResponse(BaseModel):
    service: str
    desired_replicas: int
    actual_replicas: int
    message: str


class ServiceCreateRequest(BaseModel):
    name: str
    image: str
    min_replicas: int | None = None
    max_replicas: int | None = None
    scale_up_cpu: float | None = None
    scale_down_cpu: float | None = None
    scale_up_ticks: int | None = None
    scale_down_ticks: int | None = None
    cooldown_seconds: float | None = None
    container_port: int | None = None
    cpu_limit: float | None = None
    memory_limit: str | None = None
    command: list[str] | None = None
    traefik: dict[str, Any] | None = None

    def policy_overrides(self) -> dict:
        fields = (
            "min_replicas",
            "max_replicas",
            "scale_up_cpu",
            "scale_down_cpu",
            "scale_up_ticks",
            "scale_down_ticks",
            "cooldown_seconds",
            "container_port",
            "cpu_limit",
            "memory_limit",
            "command",
            "traefik",
        )
        return {name: getattr(self, name) for name in fields if getattr(self, name) is not None}


class ScalingEvent(BaseModel):
    ts: float
    service: str
    action: Literal[
        "scale_up",
        "scale_down",
        "manual_scale",
        "reconcile_create",
        "reconcile_remove",
        "drain",
        "error",
        "info",
        "service_start",
        "service_stop",
        "service_add",
        "service_remove",
    ]
    message: str
    desired: int | None = None
    actual: int | None = None


class CpuSample(BaseModel):
    total_usage: int
    system_cpu_usage: int
    online_cpus: int


class MetricSample(BaseModel):
    ts: float
    cpu_percent: float
    memory_bytes: int
    net_rx_bytes: int = 0
    net_tx_bytes: int = 0


class EngineState(BaseModel):
    consecutive_high: int = 0
    consecutive_low: int = 0
    last_scale_at: float | None = None


class ScaleDecision(BaseModel):
    direction: Literal["up", "down"] | None = None
    desired: int
    reason: str
