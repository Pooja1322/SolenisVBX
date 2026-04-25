import json
import datetime
from typing import List, Union, Tuple, Optional
from influxdb_client import InfluxDBClient, Point
from influxdb_client.client.write_api import SYNCHRONOUS, WriteApi
from influxdb_client.client.query_api import QueryApi
from .logging import get_logger # Assuming logging.py is in utils/

logger = get_logger("influx_wrapper")

class InfluxDBWrapper:
    """
    Handles all connection, writing, and querying logic for InfluxDB.
    Separates data persistence concerns from application logic.
    """
    def __init__(self, url: str, token: str, org: str, bucket: str):
        """
        Initializes the InfluxDB client and APIs.

        Args:
            url (str): The InfluxDB URL.
            token (str): The authentication token.
            org (str): The organization name.
            bucket (str): The default bucket name.
        """
        self.url = url
        self.token = token
        self.org = org
        self.bucket = bucket
        self.client: Optional[InfluxDBClient] = None
        self.write_api: Optional[WriteApi] = None
        self.query_api: Optional[QueryApi] = None

        try:
            self.client = InfluxDBClient(url=self.url, token=self.token, org=self.org)
            self.write_api = self.client.write_api(write_options=SYNCHRONOUS)
            self.query_api = self.client.query_api()
            logger.info(f"InfluxDBClient initialized for {self.url} (Org: {self.org}, Bucket: {self.bucket})")
        except Exception as e:
            logger.error(f"Failed to initialize InfluxDBClient: {e}")
            self.client = None
            self.write_api = None
            self.query_api = None

    def close(self):
        """Closes the InfluxDB client connection."""
        if self.client:
            try:
                self.client.close()
                logger.info("InfluxDBClient closed successfully.")
            except Exception as e:
                logger.error(f"Error closing InfluxDBClient: {e}")

    def write_point(self, point: Union[Point, List[Point]]):
        """Writes a single Point or a list of Points to the configured bucket."""
        if not self.write_api:
            logger.error("Write API is not initialized. Cannot write point.")
            return

        try:
            self.write_api.write(bucket=self.bucket, record=point)
        except Exception:
            logger.exception("Failed to write point(s) to InfluxDB")

    def write_timeseries_point(self, ts: datetime.datetime, temp_val: float, rpm_val: float, rms_val: float):
        """Writes the primary timeseries data (Temp, RPM, overall RMS)."""
        # We write multiple fields in a single point for better performance and organization
        point = (
            Point("timeseries_data")
            .field("temperature", temp_val)
            .field("rpm", rpm_val)
            .field("vibration_rms", rms_val)
            .time(ts)
        )
        self.write_point(point)

    def write_spectrum(self, ts: datetime.datetime, channel: int, fft_json: str):
        """Writes the FFT spectrum (as JSON string) for a specific channel."""
        point = (
            Point(f"vibration_freq_ch{channel}_json")
            .field("spectrum", fft_json)
            .time(ts)
        )
        self.write_point(point)

    def write_waveform(self, ts: datetime.datetime, channel: int, raw_json: str):
        """Writes the raw time waveform (as JSON string) for a specific channel."""
        point = (
            Point(f"vibration_raw_ch{channel}_json")
            .field("waveform", raw_json)
            .time(ts)
        )
        self.write_point(point)

    def query(self, flux_query: str) -> List[dict]:
        """
        Executes a Flux query and returns a list of dictionaries (rows).

        Args:
            flux_query (str): The Flux query string.

        Returns:
            List[dict]: A list of dictionaries representing the query results.
        """
        if not self.query_api:
            logger.error("Query API is not initialized. Cannot execute query.")
            return []

        results = []
        try:
            tables = self.query_api.query(query=flux_query)
            for table in tables:
                for record in table.records:
                    results.append(record.values)
        except Exception:
            logger.exception("Failed to execute InfluxDB query")
            results = []

        return results