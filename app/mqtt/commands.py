"""Parse and dispatch MQTT command payloads."""

from __future__ import annotations

import json
import time
from typing import Any, Literal

import structlog
from pydantic import BaseModel, ValidationError, model_validator

from app.core.control import (
    UnknownServiceError,
    apply_manual_scale,
    start_managed,
    stop_managed,
)
from app.models import ScalingEvent

log = structlog.get_logger(__name__)


class CommandError(ValueError):
    pass


class MqttCommand(BaseModel):
    action: Literal["scale", "stop", "start"]
    service: str | None = None
    replicas: int | None = None

    @model_validator(mode="after")
    def scale_fields(self) -> MqttCommand:
        if self.action == "scale":
            if not self.service:
                raise ValueError("scale requires service")
            if self.replicas is None:
                raise ValueError("scale requires replicas")
            if self.replicas < 0:
                raise ValueError("replicas must be >= 0")
        return self


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
        try:
            await stop_managed(app)
        except Exception as exc:
            log.exception("mqtt_stop_failed")
            return _error_event(f"stop failed: {exc}")
        return None
    if command.action == "start":
        try:
            await start_managed(app)
        except Exception as exc:
            log.exception("mqtt_start_failed")
            return _error_event(f"start failed: {exc}")
        return None
    return _error_event(f"unknown action {command.action!r}")


async def handle_raw_command(app: Any, raw: str | bytes) -> ScalingEvent | None:
    try:
        command = parse_command(raw)
    except CommandError as exc:
        return _error_event(str(exc))
    return await dispatch_command(app, command)
