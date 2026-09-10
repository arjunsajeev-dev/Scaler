"""MQTT topic helpers for a single device identity."""

from __future__ import annotations


def status_topic(device_id: str) -> str:
    return f"devices/{device_id}/status"


def events_topic(device_id: str) -> str:
    return f"devices/{device_id}/events"


def lwt_topic(device_id: str) -> str:
    return f"devices/{device_id}/lwt"


def cmd_topic(device_id: str) -> str:
    return f"devices/{device_id}/cmd"


def discovery_topic(device_id: str) -> str:
    return f"devices/{device_id}/discovery"
