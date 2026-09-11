"""LAN discoverability via Bonjour/mDNS.

This Mac advertises `_scaler._tcp` so the MQTT server Mac can find the device.
When MQTT_HOST is `mdns` / `auto`, this process browses `_mqtt._tcp` for the broker.
"""

from __future__ import annotations

import socket
import threading
from typing import Any

import structlog

from app.config import Settings

log = structlog.get_logger(__name__)

MQTT_SERVICE = "_mqtt._tcp.local."
SCALER_SERVICE = "_scaler._tcp.local."
MDNS_BROKER_ALIASES = frozenset({"mdns", "auto", "bonjour"})


def is_mdns_broker(host: str) -> bool:
    return host.strip().lower() in MDNS_BROKER_ALIASES


def lan_ipv4() -> str:
    probe = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        probe.connect(("8.8.8.8", 80))
        ip = probe.getsockname()[0]
    except OSError:
        ip = "127.0.0.1"
    finally:
        probe.close()
    return ip


def browse_mqtt_broker(timeout: float = 8.0) -> tuple[str, int] | None:
    """Block until an `_mqtt._tcp` service appears on the LAN, or timeout."""
    from zeroconf import ServiceBrowser, ServiceStateChange, Zeroconf

    found: dict[str, Any] = {}
    ready = threading.Event()

    def on_change(zeroconf: Zeroconf, service_type: str, name: str, state_change: ServiceStateChange) -> None:
        if state_change is not ServiceStateChange.Added:
            return
        info = zeroconf.get_service_info(service_type, name, timeout=3000)
        if info is None:
            return
        addresses = info.parsed_addresses()
        if not addresses:
            return
        found["host"] = addresses[0]
        found["port"] = int(info.port or 1883)
        ready.set()

    zeroconf = Zeroconf()
    browser = ServiceBrowser(zeroconf, MQTT_SERVICE, handlers=[on_change])
    try:
        if not ready.wait(timeout):
            log.warning("mqtt_broker_mdns_timeout", service=MQTT_SERVICE)
            return None
        return str(found["host"]), int(found["port"])
    finally:
        browser.cancel()
        zeroconf.close()


class MdnsAdvertiser:
    """Publish this orchestrator on the LAN as `_scaler._tcp`."""

    def __init__(self, settings: Settings):
        self._settings = settings
        self._zeroconf: Any = None
        self._info: Any = None

    @property
    def enabled(self) -> bool:
        return self._settings.mqtt_mdns

    def start(self) -> None:
        if not self.enabled:
            return
        from zeroconf import ServiceInfo, Zeroconf

        ip = lan_ipv4()
        device_id = self._settings.mqtt_device_id
        self._info = ServiceInfo(
            SCALER_SERVICE,
            f"{device_id}.{SCALER_SERVICE}",
            addresses=[socket.inet_aton(ip)],
            port=self._settings.advertise_port,
            properties={
                "id": device_id,
                "proto": "mqtt",
                "cmd": f"devices/{device_id}/cmd",
                "status": f"devices/{device_id}/status",
            },
        )
        try:
            self._zeroconf = Zeroconf()
            # allow_name_change avoids stalls when a stale instance still holds the name
            self._zeroconf.register_service(self._info, allow_name_change=True)
        except Exception:
            log.exception(
                "mdns_advertise_failed",
                service=SCALER_SERVICE,
                name=device_id,
                hint="orchestrator will keep running; set MQTT_MDNS=false to skip",
            )
            self.stop()
            return
        log.info(
            "mdns_advertised",
            service=SCALER_SERVICE,
            name=device_id,
            ip=ip,
            port=self._settings.advertise_port,
        )

    def stop(self) -> None:
        if self._zeroconf is None:
            return
        try:
            if self._info is not None:
                self._zeroconf.unregister_service(self._info)
        finally:
            self._zeroconf.close()
            self._zeroconf = None
            self._info = None
            log.info("mdns_unadvertised")
