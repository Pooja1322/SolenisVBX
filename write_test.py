# write_test.py  -- corrected to write numeric values
import time
import json
from influxdb_client import InfluxDBClient, Point

INFLUX_URL = "http://localhost:8086"
INFLUX_TOKEN = "5wpWVUxmTIeUyBiQd0jR2B0fWSKWixGHUcpWWbZ5sLVGhAleHO5CRdXVUL1V9outsAxvugvLIc58sCLVchL1Pg=="
INFLUX_ORG = "TechMahindra"
INFLUX_BUCKET = "TechroomB2"

def write_test_point():
    client = None
    write_api = None
    try:
        client = InfluxDBClient(url=INFLUX_URL, token=INFLUX_TOKEN, org=INFLUX_ORG)
        write_api = client.write_api()  # use defaults
        
        # Test values (numeric floats, NOT JSON strings)
        temp_value = 55.0  # example: 55 °C
        rpm_value = 1450.0  # example: 1450 RPM

        p = Point("timeseries_data").tag("src", "write_test") \
            .field("temperature", temp_value) \
            .field("rpm", rpm_value) # Changed to write 'rpm' as a numeric field
        
        # Also write the legacy 'rms' field as a float for safety/compatibility
        p.field("rms", 0.75)

        write_api.write(bucket=INFLUX_BUCKET, org=INFLUX_ORG, record=p)
        print(f"Successfully wrote test point: Temp={temp_value}, RPM={rpm_value}")

        # ensure flush and close to avoid "cannot schedule new futures after interpreter shutdown"
        try:
            write_api.close()
        except Exception:
            pass
        try:
            client.close()
        except Exception:
            pass
            
    except Exception as e:
        print(f"Error writing test point to InfluxDB: {e}")
        if write_api:
            try: write_api.close()
            except Exception: pass
        if client:
            try: client.close()
            except Exception: pass


if __name__ == "__main__":
    write_test_point()