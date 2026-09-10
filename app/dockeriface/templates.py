"""Container template rendering: names, Traefik labels, resource limits."""

from __future__ import annotations

from app.config import ServicePolicy
from app.dockeriface.labels import LABEL_INDEX, LABEL_MANAGED, LABEL_SERVICE, MANAGED_VALUE


def replica_name(service: str, index: int) -> str:
    return f"orch-{service}-{index}"


def render_labels(policy: ServicePolicy, index: int) -> dict[str, str]:
    labels = {
        LABEL_SERVICE: policy.name,
        LABEL_MANAGED: MANAGED_VALUE,
        LABEL_INDEX: str(index),
    }
    if policy.traefik.enabled:
        router = policy.name
        labels.update(
            {
                "traefik.enable": "true",
                f"traefik.http.routers.{router}.rule": policy.traefik.rule,
                f"traefik.http.routers.{router}.entrypoints": policy.traefik.entrypoint,
                f"traefik.http.services.{router}.loadbalancer.server.port": str(
                    policy.container_port
                ),
            }
        )
        if policy.traefik.strip_prefix:
            mw = f"{router}-strip"
            labels[f"traefik.http.middlewares.{mw}.stripprefix.prefixes"] = (
                policy.traefik.strip_prefix
            )
            labels[f"traefik.http.routers.{router}.middlewares"] = mw
    return labels


def nano_cpus(cpu_limit: float) -> int:
    return int(cpu_limit * 1_000_000_000)
