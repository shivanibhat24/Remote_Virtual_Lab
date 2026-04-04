"""
mqtt_bridge.py - Global Cloud MQTT Bridge for STM32 Lab GUI v6.0
"""

import json
import random
import string
import threading
from typing import Optional

from PyQt5.QtCore import QObject, pyqtSignal

try:
    import paho.mqtt.client as mqtt_client
    HAS_MQTT = True
except ImportError:
    HAS_MQTT = False


class MqttBridge(QObject):
    status_changed = pyqtSignal(str)
    command_received = pyqtSignal(str)
    log_event = pyqtSignal(str)

    def __init__(self, session_id: Optional[str] = None):
        super().__init__()
        self.session_id = session_id or "".join(random.choices(string.ascii_uppercase + string.digits, k=6))
        self.broker = "test.mosquitto.org"
        self.port   = 1883
        self.base_topic = f"stm32lab/{self.session_id}"
        self.client: Optional[mqtt_client.Client] = None
        self._running = False

    def set_session_id(self, new_id: str):
        """Update session ID and base topic."""
        self.session_id = new_id
        self.base_topic = f"stm32lab/{self.session_id}"

    def connect_cloud(self):
        if not HAS_MQTT:
            self.status_changed.emit("paho-mqtt not installed. Run: pip install paho-mqtt")
            return

        if self._running:
            return

        # Handle paho-mqtt version differences
        try:
            self.client = mqtt_client.Client(mqtt_client.CallbackAPIVersion.VERSION2, f"stm32_host_{self.session_id}")
        except AttributeError:
            self.client = mqtt_client.Client(f"stm32_host_{self.session_id}")
            
        self.client.on_connect = self._on_connect
        self.client.on_message = self._on_message
        self.client.on_disconnect = self._on_disconnect

        try:
            self.client.connect(self.broker, self.port, keepalive=60)
            self._running = True
            self.client.loop_start()
            self.status_changed.emit(f"Connecting to Mosquitto Cloud...")
        except Exception as e:
            self.status_changed.emit(f"Connection failed: {e}")

    def disconnect_cloud(self):
        if self._running and self.client:
            self._running = False
            self.client.loop_stop()
            self.client.disconnect()
            self.client = None
            self.status_changed.emit("Disconnected.")
            self.log_event.emit("System disconnected from cloud relay.")

    def _on_connect(self, client, userdata, flags, rc, *args):
        if rc == 0:
            self.status_changed.emit(f"ONLINE | Session ID: {self.session_id}")
            self.log_event.emit(f"Connected to Mosquitto. Subscribed to {self.base_topic}/cmds")
            client.subscribe(f"{self.base_topic}/cmds", qos=0)
        else:
            self.status_changed.emit(f"Connection refused (code {rc})")

    def _on_disconnect(self, client, userdata, rc, *args):
        if self._running:
            self.status_changed.emit("Connection lost. Reconnecting...")
            self.log_event.emit("Cloud connection dropped unexpectedly.")

    def _on_message(self, client, userdata, msg):
        try:
            payload = msg.payload.decode("utf-8")
            self.log_event.emit(f"Received Command: {payload}")
            self.command_received.emit(payload)
        except Exception as e:
            self.log_event.emit(f"Parse error on message: {e}")

    def publish_data(self, samples: list, stats: dict):
        if not self._running or not self.client:
            return
        doc = {
            "s": samples,
            "st": stats
        }
        try:
            # Publish with QoS 0 (fire and forget) for fast telemetry
            self.client.publish(f"{self.base_topic}/data", json.dumps(doc), qos=0)
        except Exception:
            pass

    @property
    def is_running(self):
        return self._running
