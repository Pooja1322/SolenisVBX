import time
import json
import numpy as np
import datetime
import random
from influxdb_client import Point

from utils.common import (
    load_influx_config,
    create_influx_client,
    create_influx_apis,
    safe_close_client,
    write_point,
)
from utils.logging import get_logger
from utils.mqtt_wrapper import MQTTWrapper
from utils.signal_analyzer import SignalAnalyzer

logger = get_logger("edge_backend")

class EdgeBackend:
    def __init__(self, influx_cfg_path: str = "influx_config.json"):
        # -------- Influx setup (UNCHANGED) --------
        cfg = load_influx_config(influx_cfg_path)
        self.url, self.token = cfg.get("INFLUX_URL"), cfg.get("INFLUX_TOKEN")
        self.org, self.bucket = cfg.get("INFLUX_ORG"), cfg.get("INFLUX_BUCKET")

        # Simulation Parameters
        self.sample_rate = 60000
        self.fft_size = 4096
        self.base_rpm = 1750.0
        self.current_rpm = self.base_rpm
        self.base_temp = 42.0
        self.iteration = 0

        self.client = create_influx_client(self.url, self.token, self.org)
        self.query_api, self.write_api = create_influx_apis(self.client, need_write=True)

        self.analyzer = SignalAnalyzer(
            sample_rate=self.sample_rate,
            fft_size=self.fft_size
        )

        # -------- MQTT (thin-edge / Cumulocity) --------
        self.mqtt = MQTTWrapper(
            broker="127.0.0.1",
            client_id="OnGuardVBX_Backend"
        )
        self.mqtt.connect()

    def generate_stimulated_waveform(self, is_anomaly: bool = False):
        """
        Generates a waveform that reacts to the current RPM.
        If is_anomaly is True, it simulates a bearing fault (high vibration).
        """
        duration = 1.0
        num_points = int(self.sample_rate * duration)
        t = np.linspace(0, duration, num_points, endpoint=False)
        
        # Base amplitude fluctuates slightly
        amplitude = 40 + np.random.normal(0, 2)
        noise_level = 5
        
        if is_anomaly:
            # Simulate a 4x increase in vibration and higher noise
            amplitude *= 4.5
            noise_level *= 3
        
        # Fundamental frequency based on stimulated RPM
        freq = self.current_rpm / 60.0
        
        sig = (
            amplitude * np.sin(2 * np.pi * freq * t)
            + np.random.normal(0, noise_level, num_points)
        )
        
        # If anomaly, add a high-frequency "bearing knock" component (e.g. 7.2x RPM)
        if is_anomaly:
            sig += (amplitude * 0.8) * np.sin(2 * np.pi * (freq * 7.2) * t)

        # Return downsampled for UI and full signal for processing
        return np.column_stack((t[::30], sig[::30])).tolist(), sig

    def run_generation_loop(self, sleep_sec: float = 2.0):
        logger.info("Starting Stimulated Data Loop (Influx + Cumulocity)...")
        
        try:
            while True:
                self.iteration += 1
                ts = datetime.datetime.now(datetime.timezone.utc)

                # 1. SIMULATE DRIFT (Dynamic RPM and Temp)
                # RPM drifts using a sine wave + noise
                self.current_rpm = self.base_rpm + (15 * np.sin(self.iteration / 10.0)) + np.random.uniform(-1, 1)
                # Temperature rises slowly and stabilizes
                current_temp = self.base_temp + (5 * np.sin(self.iteration / 50.0)) + np.random.uniform(-0.1, 0.1)

                # 2. TRIGGER ANOMALY (Failure State)
                # Every 40 iterations, simulate a 5-iteration "Failure Event"
                is_vibration_anomaly = (35 < (self.iteration % 40) <= 40)
                vibration_data = {}
                rpm_data = {}
                client_payload = {
                                    # Temperatures
                                    "temperature_t1": round(current_temp, 2),
                                    "temperature_t2": round(current_temp + 1.5, 2),

                                    # Speed / RPM
                                    "tachometer_rpm": round(self.current_rpm, 2),
                                    "machine_speed": round(self.current_rpm, 2),

                                    # Blade state (simulated)
                                    "blade_inserted": 1 if (self.iteration % 20 < 15) else 0
                                }

                if is_vibration_anomaly:
                    current_temp += 20.0 # Heat spike during vibration event
                    logger.warning(f"--- SIMULATING MACHINE FAILURE (Iteration {self.iteration}) ---")

                  
                # -------- Channel loop --------
                for ch in range(1, 5):
                    # Use stimulated waveform generator
                    wave_visual, raw_sig = self.generate_stimulated_waveform(is_anomaly=is_vibration_anomaly)

                    #rms = vibration_data[f"ch{ch}"]["rms"]

                    #Compute metrics FIRST
                    rms_val = round(self.analyzer.compute_rms(raw_sig), 3)
                    freq_val = round(self.current_rpm / 60.0, 2)

                    #Store in vibration_data (NOW it exists)
                    vibration_data[f"ch{ch}"] = {
                        "rms": rms_val,
                        "freq": freq_val,
                    }

                    rpm_data[f"ch{ch}"] = round(self.current_rpm, 2)

                    #Build client telemetry USING rms_val (NOT dict lookup)
                    client_payload[f"vibration_ch{ch}_total"] = rms_val
                    client_payload[f"vibration_ch{ch}_50_5khz"] = round(rms_val * 0.25, 6)
                    client_payload[f"vibration_ch{ch}_5_15khz"] = round(rms_val * 0.35, 6)
                    client_payload[f"vibration_ch{ch}_15_25khz"] = round(rms_val * 0.40, 6)
                    

                    # --- Influx: waveform & spectrum (UNCHANGED) ---
                    write_point(
                        self.write_api,
                        self.bucket,
                        Point("waveform")
                        .tag("channel", f"CH{ch}")
                        .field("data", json.dumps(wave_visual))
                        .time(ts),
                    )

                    write_point(
                        self.write_api,
                        self.bucket,
                        Point("spectrum")
                        .tag("channel", f"CH{ch}")
                        .field("data", self.analyzer.compute_fft_json(raw_sig))
                        .time(ts),
                    )

                
                # -------- CUMULOCITY TELEMETRY (DYNAMIC) --------
                # This will now show fluctuations in Cumulocity Dashboards
                self.mqtt.publish_telemetry(
                    vibration=vibration_data,
                    rpm=rpm_data,
                    temperature=round(current_temp, 2),
                )

                # STORE CLIENT TELEMETRY IN INFLUXDB 

                p_client = Point("client_telemetry").time(ts)

                for k, v in client_payload.items():
                    p_client = p_client.field(k, float(v))

                write_point(self.write_api, self.bucket, p_client)
 
                self.mqtt.publish_custom_telemetry(client_payload)

                # -------- Influx timeseries (SYNCED) --------
                p_ts = (
                    Point("timeseries")
                    .field("rpm", float(self.current_rpm))
                    .field("temperature", float(current_temp))
                    .time(ts)
                )
                write_point(self.write_api, self.bucket, p_ts)

                logger.info(
                    f"Iteration {self.iteration} | Published: RPM={self.current_rpm:.2f}, Temp={current_temp:.2f}, Anomaly={is_vibration_anomaly}"
                )

                time.sleep(sleep_sec)

        except KeyboardInterrupt:
            logger.info("Stopping edge backend...")
        finally:
            self.mqtt.disconnect()
            safe_close_client(self.client)

    #     client_payload = {
    #     "temperature_t1": 105,
    #     "temperature_t2": 106.5,
    #     "tachometer_rpm": 100,
    #     "machine_speed": 1750.3,

    #     "vibration_ch1_total": 0.419,
    #     "vibration_ch1_50_5khz": 0.053,
    #     "vibration_ch1_5_15khz": 0.147,
    #     "vibration_ch1_15_25khz": 0.221,

    #     "vibration_ch2_total": 0.838,
    #     "vibration_ch2_50_5khz": 0.106,
    #     "vibration_ch2_5_15khz": 0.294,
    #     "vibration_ch2_15_25khz": 0.442,

    #     "vibration_ch3_total": 1.257,
    #     "vibration_ch3_50_5khz": 0.159,
    #     "vibration_ch3_5_15khz": 0.441,
    #     "vibration_ch3_15_25khz": 0.663,

    #     "vibration_ch4_total": 1.676,
    #     "vibration_ch4_50_5khz": 0.212,
    #     "vibration_ch4_5_15khz": 0.588,
    #     "vibration_ch4_15_25khz": 0.884,
        
    #     "blade_inserted": 1
    # }


        # self.mqtt.publish_custom_telemetry(client_payload)



if __name__ == "__main__":
    EdgeBackend().run_generation_loop()