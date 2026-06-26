"""
Azure Function (Blob trigger): transform

Triggered when a new object lands in the ADLS Gen2 `raw/` container. Reads
the raw JSON, flattens it via shared.transform, and loads it into Azure SQL.

Note: when packaging for deployment, copy shared/ alongside this folder.
"""

import json
import logging
import os

import azure.functions as func

try:
    import pyodbc
except ImportError:
    pyodbc = None

from shared.transform import transform_record
from shared.ingest import to_raw_record


def main(myblob: func.InputStream):
    logging.info("Processing blob: %s", myblob.name)

    raw = json.loads(myblob.read())

    # ADF lands the raw API response directly (no wrapper envelope).
    # Wrap it so transform_record gets the expected format.
    if "payload" not in raw:
        raw = to_raw_record(raw)

    row = transform_record(raw)

    logging.info("Transformed row: %s", row)

    # Load into Azure SQL
    conn_str = os.environ.get("SQL_CONNECTION_STRING", "")

    if not conn_str or conn_str == "TODO":
        logging.warning(
            "SQL_CONNECTION_STRING not configured — skipping DB insert. "
            "Set the app setting to enable warehouse loading."
        )
        return

    if pyodbc is None:
        logging.error("pyodbc not installed — cannot insert into Azure SQL")
        return

    try:
        with pyodbc.connect(conn_str, timeout=15) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "INSERT INTO weather_observations "
                "(ingested_at, latitude, longitude, temperature_c, wind_speed_kmh, humidity_pct) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                row["ingested_at"],
                row["latitude"],
                row["longitude"],
                row["temperature_c"],
                row["wind_speed_kmh"],
                row["humidity_pct"],
            )
            conn.commit()
        logging.info("Row inserted into weather_observations successfully")
    except Exception:
        logging.exception("Failed to insert row into Azure SQL")
