import json
import logging
import paho.mqtt.client as mqtt
from typing import Dict, Any

logger = logging.getLogger(__name__)
logger.setLevel(logging.INFO)


class MQTTWrapper:
    """
    MQTT wrapper for publishing telemetry to Cumulocity via thin-edge.io.
    Fully thin-edge compatible (flat numeric measurements).
    """

    def __init__(
        self,
        broker: str = "localhost",
        port: int = 1883,
        client_id: str = None,
        keepalive: int = 60,
    ):
        self.broker = broker
        self.port = port
        self.keepalive = keepalive

        self.client = mqtt.Client(client_id=client_id)
        self.client.on_connect = self._on_connect
        self.client.on_disconnect = self._on_disconnect

        self.connected = False

    # --------------------
    # MQTT lifecycle
    # --------------------
    def _on_connect(self, client, userdata, flags, rc):
        if rc == 0:
            self.connected = True
            logger.info("MQTT connected successfully")
        else:
            logger.error(f"MQTT connection failed with code {rc}")

    def _on_disconnect(self, client, userdata, rc):
        self.connected = False
        logger.warning("MQTT disconnected")

    def connect(self):
        try:
            self.client.connect(self.broker, self.port, self.keepalive)
            self.client.loop_start()
        except Exception as e:
            logger.exception(f"MQTT connect error: {e}")
            raise

    def disconnect(self):
        try:
            self.client.loop_stop()
            self.client.disconnect()
        except Exception as e:
            logger.exception(f"MQTT disconnect error: {e}")

    def publish(self, topic: str, payload: Dict[str, Any]):
        if not self.connected:
            logger.warning("MQTT not connected, reconnecting")
            self.connect()

        try:
            message = json.dumps(payload)
            result = self.client.publish(topic, message, qos=0)
            if result.rc != mqtt.MQTT_ERR_SUCCESS:
                logger.error(f"Publish failed to {topic}, rc={result.rc}")
            else:
                logger.info(f"Published to {topic}: {message}")
        except Exception as e:
            logger.exception(f"MQTT publish error: {e}")

    # =========================================================
    # thin-edge Telemetry (CORRECT FORMAT)
    # =========================================================
    def publish_telemetry(
        self,
        vibration: Dict[str, Dict[str, float]],
        rpm: Dict[str, float],
        temperature: float,
    ):
        """
        Publishes telemetry in a STRICT thin-edge compatible format.

        Example input:

        vibration = {
          "ch1": {"rms": 2.1, "freq": 120},
          "ch2": {"rms": 2.3, "freq": 118}
        }

        rpm = {
            "ch1": 1450,
            "ch2": 1460
        }

        temperature = 38.6
        """

        # -----------------------------------------------------
        # IMPORTANT:
        # - Flat JSON
        # - Numeric values ONLY
        # - No units
        # - No nested objects
        # -----------------------------------------------------
        payload: Dict[str, Any] = {
            "temperature": temperature
        }

        # RPM (flat numeric values)
        for ch, value in rpm.items():
            payload[f"rpm_{ch}"] = value

        # Vibration (flat numeric values)
        for ch, values in vibration.items():
            payload[f"vibration_{ch}_rms"] = values.get("rms")
            #payload[f"vibration_{ch}_freq"] = values.get("freq")

        topic = "tedge/measurements"
        self.publish(topic, payload)

    def publish_custom_telemetry(self, payload: Dict[str, Any]):
        """
        Publish client-defined flat telemetry directly to Cumulocity
        without modifying existing telemetry structure.
        """
        # Optional safety check
        for k, v in payload.items():
            if not isinstance(v, (int, float)):
                raise ValueError(f"Invalid value for {k}: thin-edge allows only numeric values")

        topic = "tedge/measurements"
        self.publish(topic, payload)
