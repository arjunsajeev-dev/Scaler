from app.config import Settings
from app.mqtt.client import NullMqttBridge, create_mqtt_bridge
from app.mqtt.discovery import is_mdns_broker
from app.mqtt.publisher import discovery_payload
from app.mqtt.topics import cmd_topic, discovery_topic, events_topic, lwt_topic, status_topic


def test_topics_include_device_id():
    device = "scaler-hw-01"
    assert status_topic(device) == "devices/scaler-hw-01/status"
    assert events_topic(device) == "devices/scaler-hw-01/events"
    assert lwt_topic(device) == "devices/scaler-hw-01/lwt"
    assert cmd_topic(device) == "devices/scaler-hw-01/cmd"
    assert discovery_topic(device) == "devices/scaler-hw-01/discovery"


def test_mqtt_disabled_when_host_empty():
    settings = Settings(mqtt_host="")
    assert settings.mqtt_enabled is False
    bridge = create_mqtt_bridge(settings, app=None, events=None)
    assert isinstance(bridge, NullMqttBridge)


def test_mdns_host_enables_mqtt_client():
    settings = Settings(mqtt_host="mdns")
    assert settings.mqtt_enabled is True
    assert is_mdns_broker("mdns")
    assert is_mdns_broker("auto")
    assert not is_mdns_broker("")
    assert not is_mdns_broker("192.168.1.10")


def test_discovery_payload_has_topics():
    payload = discovery_payload("scaler-hw-01", api_port=8000)
    assert payload["device_id"] == "scaler-hw-01"
    assert payload["topics"]["cmd"] == "devices/scaler-hw-01/cmd"
    assert payload["api"].endswith(":8000")
