"""
Azure Function (Blob trigger): transform

Triggered when a new object lands in the ADLS Gen2 `raw/` container. Reads
the raw JSON, flattens it via shared.transform, and loads it into Azure SQL.

Note: when packaging for deployment, copy shared/ alongside this folder.
"""

import json
import logging

import azure.functions as func

from shared.transform import transform_record


def main(myblob: func.InputStream):
    logging.info("Processing blob: %s", myblob.name)

    raw = json.loads(myblob.read())
    row = transform_record(raw)

    # TODO: connect to Azure SQL using the SQL_CONNECTION_STRING app setting
    # (e.g. via pyodbc or pymssql) and INSERT `row` into
    # weather_observations. See shared/transform.py for the table DDL.
    logging.info("Transformed row: %s", row)
