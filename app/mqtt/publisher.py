"""JSON payloads published to the MQTT broker."""

from __future__ import annotations

from app.models import StatusResponse
from app.mqtt.discovery import lan_ipv4


def status_payload(device_id: str, snapshot: StatusResponse) -> dict:
    return {
        "device_id": device_id,
        "online": True,
        "services": [service.model_dump() for service in snapshot.services],
    }


def discovery_payload(device_id: str, api_port: int = 8000) -> dict:
    ip = lan_ipv4()
    return {
        "device_id": device_id,
        "online": True,
        "ip": ip,
        "api": f"http://{ip}:{api_port}",
        "topics": {
            "status": f"devices/{device_id}/status",
            "events": f"devices/{device_id}/events",
            "cmd": f"devices/{device_id}/cmd",
            "lwt": f"devices/{device_id}/lwt",
        },
    }
