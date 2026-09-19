"""MQTT transport boundary; live broker use is explicit."""

from __future__ import annotations


class OfflineMqttTransport:
    connected = False

    def publish(self, topic, payload, qos=1, retain=False):
        raise RuntimeError("MQTT transport is offline")

    def close(self):
        pass


class FakeMqttTransport:
    def __init__(self):
        self.connected = True
        self.published = []

    def publish(self, topic, payload, qos=1, retain=False):
        self.published.append((topic, payload, qos, retain))
        return len(self.published)

    def close(self):
        self.connected = False


class PahoMqttTransport:
    def __init__(self, host="127.0.0.1", port=1883, client_id="mtos-mc", username=None, password=None, on_message=None):
        try:
            import paho.mqtt.client as mqtt
        except ImportError as error:
            raise RuntimeError("paho-mqtt is required for live MC operation") from error
        self.connected = False
        self.client = mqtt.Client(mqtt.CallbackAPIVersion.VERSION2, client_id=client_id, clean_session=True)
        if username:
            self.client.username_pw_set(username, password)
        self.client.on_connect = self._connected
        self.client.on_disconnect = self._disconnected
        self.client.on_message = lambda client, userdata, message: on_message(message.topic, message.payload) if on_message else None
        self.client.connect(host, port, keepalive=15)
        self.client.loop_start()

    def _connected(self, client, userdata, flags, reason_code, properties):
        self.connected = reason_code == 0
        if self.connected:
            client.subscribe("mtos/v1/nodes/+/events", qos=1)
            client.subscribe("mtos/v1/nodes/+/availability", qos=1)
            client.subscribe("mtos/v1/nodes/+/status", qos=1)

    def _disconnected(self, client, userdata, flags, reason_code, properties):
        self.connected = False

    def publish(self, topic, payload, qos=1, retain=False):
        if not self.connected:
            raise RuntimeError("MQTT broker is disconnected")
        result = self.client.publish(topic, payload, qos=qos, retain=retain)
        if result.rc != 0:
            raise RuntimeError(f"MQTT publish failed: {result.rc}")
        return result.mid

    def close(self):
        self.client.loop_stop()
        self.client.disconnect()
