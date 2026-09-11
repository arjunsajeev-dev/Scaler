"""Live service policy map: YAML baseline plus Redis overlay for dynamic services."""

from __future__ import annotations

from typing import Any

from app.config import ServicePolicy, TraefikConfig, load_services_file
from app.store.redis_store import RedisStore


class PolicyRegistry:
    """Mutable policy dict shared by the HTTP app and tick loop."""

    def __init__(self, file_names: set[str], policies: dict[str, ServicePolicy]):
        self.file_names = set(file_names)
        self.policies = policies

    def is_file_backed(self, name: str) -> bool:
        return name in self.file_names

    def is_dynamic(self, name: str) -> bool:
        return name in self.policies and name not in self.file_names


def default_traefik(name: str) -> TraefikConfig:
    prefix = f"/{name}"
    return TraefikConfig(
        enabled=True,
        rule=f"PathPrefix(`{prefix}`)",
        entrypoint="web",
        strip_prefix=prefix,
    )


def build_policy(name: str, image: str, **overrides: Any) -> ServicePolicy:
    data: dict[str, Any] = {"name": name, "image": image}
    for key, value in overrides.items():
        if value is not None:
            data[key] = value
    if "traefik" not in data:
        data["traefik"] = default_traefik(name)
    return ServicePolicy.model_validate(data)


async def load_live_policies(
    services_path, store: RedisStore
) -> tuple[dict[str, ServicePolicy], PolicyRegistry]:
    _, file_policies = load_services_file(services_path)
    policies = dict(file_policies)
    for name, policy in (await store.get_dynamic_policies()).items():
        if name not in file_policies:
            policies[name] = policy
    registry = PolicyRegistry(file_names=set(file_policies), policies=policies)
    return policies, registry
