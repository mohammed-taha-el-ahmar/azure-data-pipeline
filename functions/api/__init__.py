"""
Azure Function (HTTP trigger): api/latest

Returns the most recent row from the weather_observations table as JSON.
Used by the frontend dashboard.
"""

import json
import logging
import os

import azure.functions as func

try:
    import pyodbc
except ImportError:
    pyodbc = None  # graceful fallback during local dev without ODBC driver


def main(req: func.HttpRequest) -> func.HttpResponse:
    logging.info("API /latest invoked")

    conn_str = os.environ.get("SQL_CONNECTION_STRING", "")

    if not conn_str or conn_str == "TODO":
        return func.HttpResponse(
            json.dumps({"error": "SQL_CONNECTION_STRING not configured"}),
            status_code=503,
            mimetype="application/json",
            headers=_cors_headers(),
        )

    if pyodbc is None:
        return func.HttpResponse(
            json.dumps({"error": "pyodbc not installed"}),
            status_code=503,
            mimetype="application/json",
            headers=_cors_headers(),
        )

    try:
        with pyodbc.connect(conn_str, timeout=10) as conn:
            cursor = conn.cursor()
            cursor.execute(
                "SELECT TOP 1 ingested_at, latitude, longitude, "
                "temperature_c, wind_speed_kmh, humidity_pct "
                "FROM weather_observations ORDER BY ingested_at DESC"
            )
            row = cursor.fetchone()

        if row is None:
            return func.HttpResponse(
                json.dumps({"error": "No observations yet"}),
                status_code=404,
                mimetype="application/json",
                headers=_cors_headers(),
            )

        payload = {
            "ingested_at": row[0].isoformat() if hasattr(row[0], "isoformat") else str(row[0]),
            "latitude": row[1],
            "longitude": row[2],
            "temperature_c": row[3],
            "wind_speed_kmh": row[4],
            "humidity_pct": row[5],
        }

        return func.HttpResponse(
            json.dumps(payload),
            status_code=200,
            mimetype="application/json",
            headers=_cors_headers(),
        )

    except Exception as exc:
        logging.exception("Failed to query Azure SQL")
        return func.HttpResponse(
            json.dumps({"error": f"Database query failed: {exc}"}),
            status_code=500,
            mimetype="application/json",
            headers=_cors_headers(),
        )


def _cors_headers() -> dict:
    """Allow the static frontend to call this API cross-origin."""
    return {
        "Access-Control-Allow-Origin": "*",
        "Access-Control-Allow-Methods": "GET, OPTIONS",
        "Access-Control-Allow-Headers": "Content-Type",
    }
