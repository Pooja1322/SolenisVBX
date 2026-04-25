# utils/common.py
import os
import json
import logging
from typing import Optional, Tuple
from pathlib import Path

import numpy as np
import math
from scipy.fft import rfft, rfftfreq
from scipy.signal.windows import hann

from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi

# Use a specific logger name to prevent infinite recursion if logging.py depends on this.
logger = logging.getLogger("utils.common") 
# Assuming utils/logging.py is available and configured separately in the environment

# ---------------- Config loader ----------------
def load_influx_config(path: str = "influx_config.json") -> dict:
    cfg = {}
    # Env vars take precedence
    env_keys = ["INFLUX_URL", "INFLUX_TOKEN", "INFLUX_ORG", "INFLUX_BUCKET"]
    if any(os.getenv(k) for k in env_keys):
        cfg = {k: os.getenv(k) for k in env_keys if os.getenv(k)}
        logger.info("Loaded Influx config from environment variables")
        return cfg

    p = Path(path)
    if p.exists():
        try:
            cfg = json.loads(p.read_text(encoding="utf-8"))
            logger.info("Loaded Influx config from %s", path)
        except Exception as e:
            logger.exception("Failed to load influx_config.json: %s", e)
    else:
        logger.warning("%s not found. Using defaults/env.", path)
    
    # Ensure all keys are present, even if empty string
    return {
        "INFLUX_URL": cfg.get("INFLUX_URL", "http://localhost:8086"),
        "INFLUX_TOKEN": cfg.get("INFLUX_TOKEN", ""),
        "INFLUX_ORG": cfg.get("INFLUX_ORG", "TechMahindra"),
        "INFLUX_BUCKET": cfg.get("INFLUX_BUCKET", "TechroomB2"),
    }

def load_json_file(path: str) -> dict:
    """Safely loads a JSON file."""
    try:
        p = Path(path)
        if p.exists():
            return json.loads(p.read_text(encoding="utf-8"))
        else:
            logger.warning("JSON file not found: %s", path)
            return {}
    except Exception:
        logger.exception("Error loading JSON file: %s", path)
        return {}

# ---------------- InfluxDB Client Handlers ----------------
def create_influx_client(url: str, token: str, org: str) -> Optional[InfluxDBClient]:
    """Initializes and returns the InfluxDB client."""
    if not token:
        logger.error("INFLUX_TOKEN is empty. Cannot connect to InfluxDB.")
        return None
    try:
        client = InfluxDBClient(url=url, token=token, org=org, timeout=15000)
        # Optional: Check connection health
        # client.health().message 
        logger.info("Successfully created InfluxDB client for %s", url)
        return client
    except Exception:
        logger.exception("Failed to create InfluxDB client.")
        return None

def create_influx_apis(client: Optional[InfluxDBClient], need_write: bool = True) -> Tuple[Optional[object], Optional[object]]:
    """Creates the Query and Write APIs from the client."""
    if not client:
        return None, None
        
    query_api = client.query_api()
    write_api = client.write_api(write_options=SYNCHRONOUS) if need_write else None
    
    return query_api, write_api

def safe_close_client(client: Optional[InfluxDBClient]):
    """Safely closes the InfluxDB client."""
    if client:
        try:
            client.close()
            logger.info("InfluxDB client closed.")
        except Exception:
            logger.exception("Error closing InfluxDB client.")

def write_point(write_api: Optional[WriteApi], bucket: str, point: Point):
    """Safely writes a single Point to InfluxDB."""
    if not write_api:
        logger.error("Write API is not initialized. Cannot write point.")
        return
    try:
        write_api.write(bucket=bucket, record=point)
        # logger.debug("Wrote point: %s", point.to_line_protocol())
    except Exception:
        logger.exception("Failed to write point to InfluxDB.")

# ---------------- FFT helper ----------------
def compute_fft_json(
    signal: np.ndarray,
    sample_rate: int,
    fft_size: int,
    max_freq: int = 27000,
    out_points: int = 512
) -> str:
    """
    Compute one-sided FFT, filter up to max_freq, downsample to out_points,
    and return JSON string list [[freq, amplitude], ...].
    (This function was already correct in the previous version.)
    """
    signal = np.asarray(signal)
    if signal.size == 0:
        return "[]"

    # Ensure signal length == fft_size (truncate or pad)
    if signal.size != fft_size:
        if signal.size > fft_size:
            s = signal[:fft_size]
        else:
            s = np.zeros(fft_size)
            s[: signal.size] = signal
    else:
        s = signal

    windowed = s * hann(len(s))
    yf = rfft(windowed)
    xf = rfftfreq(len(s), 1 / sample_rate)
    mag = (2.0 / len(s)) * np.abs(yf)

    # Filter by max frequency
    max_index = np.searchsorted(xf, max_freq)
    xf_filtered = xf[:max_index]
    mag_filtered = mag[:max_index]

    # Downsample using simple binning/decimation
    if len(xf_filtered) > out_points:
        step = len(xf_filtered) // out_points
        xf_downsampled = xf_filtered[::step][:out_points]
        mag_downsampled = mag_filtered[::step][:out_points]
    else:
        xf_downsampled = xf_filtered
        mag_downsampled = mag_filtered

    # Combine and convert to list of [freq, amplitude] pairs
    result = np.column_stack((xf_downsampled, mag_downsampled)).tolist()

    return json.dumps(result)