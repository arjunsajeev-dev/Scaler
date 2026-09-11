"""Optional MQTT bridge: one client for the whole orchestrator host."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import structlog

from app.api.events import EventBus
from app.config import Settings
from app.core.control import status_snapshot
from app.models import ScalingEvent
from app.mqtt.commands import handle_raw_command
from app.mqtt.discovery import browse_mqtt_broker, is_mdns_broker
from app.mqtt.publisher import discovery_payload, offline_status_payload, status_payload
from app.mqtt.topics import cmd_topic, discovery_topic, events_topic, lwt_topic, status_topic

log = structlog.get_logger(__name__)

_MAX_BACKOFF = 30.0
_LWT_OFFLINE = "offline"
_LWT_ONLINE = "online"


class NullMqttBridge:
    """Used when MQTT_HOST is empty so lifespan/tick stay unchanged."""

    enabled = False
    connected = False

    async def start(self) -> None:
        return None

    async def stop(self) -> None:
        return None

    async def publish_status(self) -> None:
        return None

    async def publish_offline(self) -> None:
        return None


class MqttBridge:
    enabled = True

    def __init__(self, settings: Settings, app: Any, events: EventBus):
        self._settings = settings
        self._app = app
        self._events = events
        self._stop = asyncio.Event()
        self._out: asyncio.Queue[tuple[str, str, bool]] = asyncio.Queue(maxsize=200)
        self._task: asyncio.Task[None] | None = None
        self._event_task: asyncio.Task[None] | None = None
        self._device_id = settings.mqtt_device_id
        self._connected = False

    @property
    def connected(self) -> bool:
        return self._connected

    async def start(self) -> None:
        self._stop.clear()
        self._task = asyncio.create_task(self._run(), name="mqtt-bridge")
        self._event_task = asyncio.create_task(self._forward_events(), name="mqtt-events")
        log.info(
            "mqtt_bridge_started",
            host=self._settings.mqtt_host,
            port=self._settings.mqtt_port,
            device_id=self._device_id,
        )

    async def stop(self) -> None:
        # Give the outbox a moment to flush offline/status before tearing down.
        if not self._out.empty():
            try:
                await asyncio.wait_for(self._out.join(), timeout=2.0)
            except TimeoutError:
                log.warning("mqtt_outbox_flush_timeout")
        self._stop.set()
        for task in (self._task, self._event_task):
            if task is None:
                continue
            task.cancel()
            try:
                await task
            except asyncio.CancelledError:
                pass
        self._task = None
        self._event_task = None
        log.info("mqtt_bridge_stopped")

    async def _resolve_broker(self) -> tuple[str | None, int]:
        host = self._settings.mqtt_host.strip()
        if is_mdns_broker(host):
            found = await asyncio.to_thread(browse_mqtt_broker, 8.0)
            if found is None:
                return None, self._settings.mqtt_port
            return found
        return host, self._settings.mqtt_port

    async def publish_status(self) -> None:
        snapshot = await status_snapshot(self._app)
        payload = json.dumps(status_payload(self._device_id, snapshot))
        await self._enqueue(status_topic(self._device_id), payload, retain=True)

    async def publish_offline(self) -> None:
        await self._enqueue(lwt_topic(self._device_id), _LWT_OFFLINE, retain=True)
        await self._enqueue(
            status_topic(self._device_id),
            json.dumps(offline_status_payload(self._device_id)),
            retain=True,
        )
        await self._enqueue(
            discovery_topic(self._device_id),
            json.dumps({"device_id": self._device_id, "device-status": "offline"}),
            retain=True,
        )

    async def _enqueue(self, topic: str, payload: str, retain: bool) -> None:
        try:
            self._out.put_nowait((topic, payload, retain))
        except asyncio.QueueFull:
            try:
                self._out.get_nowait()
                self._out.task_done()
            except asyncio.QueueEmpty:
                pass
            try:
                self._out.put_nowait((topic, payload, retain))
            except asyncio.QueueFull:
                log.warning("mqtt_outbox_full", topic=topic)

    async def _forward_events(self) -> None:
        queue = self._events.subscribe()
        try:
            while not self._stop.is_set():
                event: ScalingEvent = await queue.get()
                await self._enqueue(
                    events_topic(self._device_id),
                    json.dumps(event.model_dump()),
                    retain=False,
                )
        finally:
            self._events.unsubscribe(queue)

    async def _run(self) -> None:
        import aiomqtt

        backoff = 1.0
        while not self._stop.is_set():
            try:
                host, port = await self._resolve_broker()
                if host is None:
                    raise ConnectionError("mqtt broker not found via mDNS")
                will = aiomqtt.Will(
                    topic=lwt_topic(self._device_id),
                    payload=_LWT_OFFLINE,
                    qos=1,
                    retain=True,
                )
                kwargs: dict[str, Any] = {
                    "hostname": host,
                    "port": port,
                    "identifier": self._device_id,
                    "will": will,
                }
                if self._settings.mqtt_username:
                    kwargs["username"] = self._settings.mqtt_username
                    kwargs["password"] = self._settings.mqtt_password or None
                async with aiomqtt.Client(**kwargs) as client:
                    backoff = 1.0
                    await client.publish(
                        lwt_topic(self._device_id), _LWT_ONLINE, qos=1, retain=True
                    )
                    await client.publish(
                        discovery_topic(self._device_id),
                        json.dumps(
                            discovery_payload(
                                self._device_id, self._settings.advertise_port
                            )
                        ),
                        qos=1,
                        retain=True,
                    )
                    await client.subscribe(cmd_topic(self._device_id))
                    log.info("mqtt_connected", host=host, port=port)
                    self._connected = True
                    try:
                        await self.publish_status()
                        await self._pump(client)
                    finally:
                        self._connected = False
            except asyncio.CancelledError:
                self._connected = False
                raise
            except Exception:
                self._connected = False
                log.exception("mqtt_disconnected", retry_in=backoff)
                try:
                    await asyncio.wait_for(self._stop.wait(), timeout=backoff)
                except TimeoutError:
                    pass
                backoff = min(backoff * 2, _MAX_BACKOFF)

    async def _pump(self, client: Any) -> None:
        incoming = asyncio.create_task(self._listen(client), name="mqtt-listen")
        outgoing = asyncio.create_task(self._flush(client), name="mqtt-flush")
        stopper = asyncio.create_task(self._stop.wait(), name="mqtt-stop")
        try:
            done, pending = await asyncio.wait(
                {incoming, outgoing, stopper},
                return_when=asyncio.FIRST_COMPLETED,
            )
            for task in pending:
                task.cancel()
            for task in done:
                if task is stopper or task.cancelled():
                    continue
                exc = task.exception()
                if exc is not None:
                    raise exc
        finally:
            for task in (incoming, outgoing, stopper):
                task.cancel()
            await asyncio.gather(incoming, outgoing, stopper, return_exceptions=True)

    async def _listen(self, client: Any) -> None:
        async for message in client.messages:
            payload = message.payload
            event = await handle_raw_command(self._app, payload)
            if event is not None:
                await self._enqueue(
                    events_topic(self._device_id),
                    json.dumps(event.model_dump()),
                    retain=False,
                )

    async def _flush(self, client: Any) -> None:
        while True:
            topic, payload, retain = await self._out.get()
            await client.publish(topic, payload, retain=retain)
            self._out.task_done()


def create_mqtt_bridge(settings: Settings, app: Any, events: EventBus) -> MqttBridge | NullMqttBridge:
    if not settings.mqtt_enabled:
        log.info("mqtt_disabled")
        return NullMqttBridge()
    return MqttBridge(settings, app, events)
