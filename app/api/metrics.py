"""Prometheus metrics for GET /metrics."""

from __future__ import annotations

from prometheus_client import CollectorRegistry, Counter, Gauge, generate_latest


class OrchestratorMetrics:
    def __init__(self) -> None:
        self.registry = CollectorRegistry()
        self.desired = Gauge(
            "scaler_replicas_desired",
            "Desired replica count",
            ["service"],
            registry=self.registry,
        )
        self.actual = Gauge(
            "scaler_replicas_actual",
            "Actual running replica count",
            ["service"],
            registry=self.registry,
        )
        self.cpu = Gauge(
            "scaler_cpu_percent",
            "Rolling average CPU percent",
            ["service"],
            registry=self.registry,
        )
        self.memory = Gauge(
            "scaler_memory_bytes",
            "Rolling average memory usage in bytes",
            ["service"],
            registry=self.registry,
        )
        self.scale_events = Counter(
            "scaler_scale_events_total",
            "Scaling decisions taken by the engine",
            ["service", "direction"],
            registry=self.registry,
        )

    def set_service(
        self,
        service: str,
        desired: int,
        actual: int,
        cpu: float | None,
        memory: float | None,
    ) -> None:
        self.desired.labels(service=service).set(desired)
        self.actual.labels(service=service).set(actual)
        if cpu is not None:
            self.cpu.labels(service=service).set(cpu)
        if memory is not None:
            self.memory.labels(service=service).set(memory)

    def inc_scale(self, service: str, direction: str) -> None:
        self.scale_events.labels(service=service, direction=direction).inc()

    def render(self) -> bytes:
        return generate_latest(self.registry)
