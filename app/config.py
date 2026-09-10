"""Orchestrator settings and per-service scaling policy."""

from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any

import yaml
from pydantic import BaseModel, Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict

ROOT = Path(__file__).resolve().parent.parent


class TraefikConfig(BaseModel):
    enabled: bool = True
    rule: str = "PathPrefix(`/demo`)"
    entrypoint: str = "web"
    strip_prefix: str | None = "/demo"


class ServicePolicy(BaseModel):
    name: str
    image: str
    min_replicas: int = Field(default=1, ge=0)
    max_replicas: int = Field(default=5, ge=1)
    scale_up_cpu: float = 80.0
    scale_down_cpu: float = 30.0
    scale_up_ticks: int = 3
    scale_down_ticks: int = 5
    cooldown_seconds: float = 30.0
    container_port: int = 8000
    cpu_limit: float = 0.5
    memory_limit: str = "128m"
    command: list[str] | None = None
    traefik: TraefikConfig = Field(default_factory=TraefikConfig)

    @field_validator("max_replicas")
    @classmethod
    def max_gte_min(cls, v: int, info) -> int:
        min_r = info.data.get("min_replicas", 0)
        if v < min_r:
            raise ValueError("max_replicas must be >= min_replicas")
        return v


class ServicesFile(BaseModel):
    tick_interval_seconds: float = 5.0
    drain_seconds: float = 5.0
    stop_timeout_seconds: int = 30
    metrics_window: int = 5
    docker_network: str = "scaler"
    services: dict[str, dict[str, Any]]


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=str(ROOT / ".env"),
        env_file_encoding="utf-8",
        extra="ignore",
    )

    redis_url: str = "redis://127.0.0.1:6379/0"
    docker_host: str = "tcp://127.0.0.1:2375"
    docker_network: str = "scaler"
    services_config: Path = Path("config/services.yml")
    log_level: str = "INFO"
    docker_concurrency: int = 8
    mqtt_host: str = ""
    mqtt_port: int = 1883
    mqtt_device_id: str = "scaler-hw-01"
    mqtt_username: str = ""
    mqtt_password: str = ""
    mqtt_mdns: bool = True
    mqtt_advertise_port: int = 8000

    def services_path(self) -> Path:
        path = self.services_config
        if not path.is_absolute():
            path = ROOT / path
        return path

    @property
    def mqtt_enabled(self) -> bool:
        return bool(self.mqtt_host.strip())


def load_services_file(path: Path) -> tuple[ServicesFile, dict[str, ServicePolicy]]:
    raw = yaml.safe_load(path.read_text()) or {}
    file_cfg = ServicesFile.model_validate(raw)
    policies: dict[str, ServicePolicy] = {}
    for name, spec in file_cfg.services.items():
        policies[name] = ServicePolicy(name=name, **spec)
    return file_cfg, policies


@lru_cache
def get_settings() -> Settings:
    return Settings()


@lru_cache
def get_policies() -> dict[str, ServicePolicy]:
    settings = get_settings()
    _, policies = load_services_file(settings.services_path())
    return policies


@lru_cache
def get_runtime_file() -> ServicesFile:
    settings = get_settings()
    file_cfg, _ = load_services_file(settings.services_path())
    return file_cfg
