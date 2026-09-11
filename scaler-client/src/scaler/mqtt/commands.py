"""Parse and dispatch MQTT command payloads."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ValidationError, model_validator

from scaler.config import TraefikConfig
from scaler.controller.control import (
    FileBackedServiceError,
    ServiceExistsError,
    UnknownServiceError,
    add_service,
    apply_manual_scale,
    remove_service,
    start_managed,
    start_service,
    stop_managed,
    stop_service,
)
from scaler.models import ScalingEvent

log = structlog.get_logger(__name__)


class CommandError(ValueError):
    pass


class MqttCommand(BaseModel):
    action: Literal["scale", "stop", "start", "add_service", "remove_service"]
    service: str | None = None
    replicas: int | None = None
    image: str | None = None
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
    traefik: TraefikConfig | None = None

    @model_validator(mode="after")
    def required_fields(self) -> MqttCommand:
        if self.action == "scale":
            if not self.service:
                raise ValueError("scale requires service")
            if self.replicas is None:
                raise ValueError("scale requires replicas")
            if self.replicas < 0:
                raise ValueError("replicas must be >= 0")
        if self.action == "add_service":
            if not self.service:
                raise ValueError("add_service requires service")
            if not self.image:
                raise ValueError("add_service requires image")
        if self.action == "remove_service" and not self.service:
            raise ValueError("remove_service requires service")
        return self

    def policy_overrides(self) -> dict[str, Any]:
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


def parse_command(raw: str | bytes) -> MqttCommand:
    if isinstance(raw, bytes):
        raw = raw.decode(errors="replace")
    try:
        data = json.loads(raw)
    except json.JSONDecodeError as exc:
        raise CommandError(f"invalid JSON: {exc}") from exc
    if not isinstance(data, dict):
        raise CommandError("command must be a JSON object")
    try:
        return MqttCommand.model_validate(data)
    except ValidationError as exc:
        raise CommandError(str(exc)) from exc


def _error_event(message: str, service: str = "") -> ScalingEvent:
    return ScalingEvent(
        ts=time.time(),
        service=service,
        action="error",
        message=message,
    )


async def dispatch_command(app: Any, command: MqttCommand) -> ScalingEvent | None:
    """Run a parsed command. Returns an error event when the command fails."""
    if command.action == "scale":
        assert command.service is not None
        assert command.replicas is not None
        try:
            await apply_manual_scale(app, command.service, command.replicas)
        except UnknownServiceError as exc:
            return _error_event(str(exc), service=command.service)
        except Exception as exc:
            log.exception("mqtt_scale_failed", service=command.service)
            return _error_event(f"scale failed: {exc}", service=command.service)
        return None
    if command.action == "stop":
        if command.service:
            try:
                await stop_service(app, command.service)
            except UnknownServiceError as exc:
                return _error_event(str(exc), service=command.service)
            except Exception as exc:
                log.exception("mqtt_stop_service_failed", service=command.service)
                return _error_event(f"stop failed: {exc}", service=command.service)
            return None
        try:
            await stop_managed(app)
        except Exception as exc:
            log.exception("mqtt_stop_failed")
            return _error_event(f"stop failed: {exc}")
        return None
    if command.action == "start":
        if command.service:
            try:
                await start_service(app, command.service)
            except UnknownServiceError as exc:
                return _error_event(str(exc), service=command.service)
            except Exception as exc:
                log.exception("mqtt_start_service_failed", service=command.service)
                return _error_event(f"start failed: {exc}", service=command.service)
            return None
        try:
            await start_managed(app)
        except Exception as exc:
            log.exception("mqtt_start_failed")
            return _error_event(f"start failed: {exc}")
        return None
    if command.action == "add_service":
        assert command.service is not None
        assert command.image is not None
        try:
            await add_service(app, command.service, command.image, **command.policy_overrides())
        except (ServiceExistsError, FileBackedServiceError) as exc:
            return _error_event(str(exc), service=command.service)
        except Exception as exc:
            log.exception("mqtt_add_service_failed", service=command.service)
            return _error_event(f"add_service failed: {exc}", service=command.service)
        return None
    if command.action == "remove_service":
        assert command.service is not None
        try:
            await remove_service(app, command.service)
        except UnknownServiceError as exc:
            return _error_event(str(exc), service=command.service)
        except FileBackedServiceError as exc:
            return _error_event(str(exc), service=command.service)
        except Exception as exc:
            log.exception("mqtt_remove_service_failed", service=command.service)
            return _error_event(f"remove_service failed: {exc}", service=command.service)
        return None
    return _error_event(f"unknown action {command.action!r}")


async def handle_raw_command(app: Any, raw: str | bytes) -> ScalingEvent | None:
    try:
        command = parse_command(raw)
    except CommandError as exc:
        return _error_event(str(exc))
    return await dispatch_command(app, command)
