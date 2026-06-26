#!/usr/bin/env python3
"""
Local pipeline runner — simulates the full Azure pipeline on your machine.

    Ingest (Open-Meteo API)
        → Land (local .data/raw/ directory, simulates ADLS Gen2)
        → Transform (shared.transform)
        → Load (SQLite, simulates Azure SQL)
        → Query (prints latest rows, simulates the API Function)

Usage:
    uv run scripts/run_local_pipeline.py              # single run
    uv run scripts/run_local_pipeline.py --loop 30    # repeat every 30s
    uv run scripts/run_local_pipeline.py --query      # just query existing data

No Azure credentials, no Docker, no external services required.
"""

import argparse
import json
import os
import sqlite3
import sys
import time
from pathlib import Path

# Ensure the project root is on sys.path so shared/ is importable
PROJECT_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(PROJECT_ROOT))

from shared.ingest import fetch_data, raw_object_key, to_raw_record  # noqa: E402
from shared.transform import WAREHOUSE_TABLE_DDL, transform_record  # noqa: E402

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------
DATA_DIR = PROJECT_ROOT / ".data"
RAW_DIR = DATA_DIR / "raw"
DB_PATH = DATA_DIR / "warehouse.db"


# ---------------------------------------------------------------------------
# Pipeline stages
# ---------------------------------------------------------------------------


def stage_ingest() -> dict:
    """Stage 1: Fetch data from the source API."""
    print("  [1/4] 📡 Fetching from Open-Meteo API…")
    payload = fetch_data()
    record = to_raw_record(payload)
    print(f"        Temperature: {payload.get('current', {}).get('temperature_2m')}°C")
    return record


def stage_land(record: dict) -> Path:
    """Stage 2: Write raw record to local filesystem (simulates ADLS)."""
    key = raw_object_key(prefix="raw")
    file_path = DATA_DIR / key
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(json.dumps(record, indent=2))
    print(f"  [2/4] 💾 Landed → .data/{key}")
    return file_path


def stage_transform(file_path: Path) -> dict:
    """Stage 3: Read raw file and transform (simulates Azure Function blob trigger)."""
    raw = json.loads(file_path.read_text())
    row = transform_record(raw)
    print(f"  [3/4] ⚙️  Transformed → {row['temperature_c']}°C, {row['wind_speed_kmh']} km/h, {row['humidity_pct']}%")
    return row


def stage_load(row: dict) -> None:
    """Stage 4: Insert row into SQLite (simulates Azure SQL insert)."""
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(DB_PATH)
    conn.execute(WAREHOUSE_TABLE_DDL)
    conn.execute(
        "INSERT INTO weather_observations "
        "(ingested_at, latitude, longitude, temperature_c, wind_speed_kmh, humidity_pct) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (
            row["ingested_at"],
            row["latitude"],
            row["longitude"],
            row["temperature_c"],
            row["wind_speed_kmh"],
            row["humidity_pct"],
        ),
    )
    conn.commit()
    count = conn.execute("SELECT COUNT(*) FROM weather_observations").fetchone()[0]
    conn.close()
    print(f"  [4/4] 🗄️  Loaded into SQLite ({count} total rows)")


# ---------------------------------------------------------------------------
# Query (simulates the HTTP API Function)
# ---------------------------------------------------------------------------


def query_latest(n: int = 5) -> None:
    """Print the latest N rows from the local warehouse."""
    if not DB_PATH.exists():
        print("  ⚠️  No local warehouse yet — run the pipeline first.")
        return

    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    rows = conn.execute(
        "SELECT * FROM weather_observations ORDER BY ingested_at DESC LIMIT ?",
        (n,),
    ).fetchall()
    conn.close()

    if not rows:
        print("  ⚠️  Table is empty.")
        return

    print(f"\n  📊 Latest {len(rows)} observation(s):")
    print(f"  {'─' * 72}")
    print(f"  {'ingested_at':<28} {'lat':>7} {'lon':>7} {'temp °C':>8} {'wind km/h':>10} {'hum %':>6}")
    print(f"  {'─' * 72}")
    for r in rows:
        print(
            f"  {r['ingested_at']:<28} "
            f"{r['latitude']:>7.2f} "
            f"{r['longitude']:>7.2f} "
            f"{r['temperature_c']:>8.1f} "
            f"{r['wind_speed_kmh']:>10.1f} "
            f"{r['humidity_pct']:>6.0f}"
        )
    print()


# ---------------------------------------------------------------------------
# Orchestrator
# ---------------------------------------------------------------------------


def run_pipeline() -> None:
    """Execute the full local pipeline once."""
    print("\n─── Pipeline run ───────────────────────────────────────")
    record = stage_ingest()
    file_path = stage_land(record)
    row = stage_transform(file_path)
    stage_load(row)
    print("─── Done ───────────────────────────────────────────────\n")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run the Azure data pipeline locally (SQLite instead of Azure SQL)"
    )
    parser.add_argument(
        "--loop",
        type=int,
        metavar="SEC",
        help="Re-run the pipeline every SEC seconds (Ctrl+C to stop)",
    )
    parser.add_argument(
        "--query",
        action="store_true",
        help="Only query the local warehouse (don't run the pipeline)",
    )
    parser.add_argument(
        "--reset",
        action="store_true",
        help="Delete local data and start fresh",
    )
    parser.add_argument(
        "-n",
        type=int,
        default=5,
        help="Number of rows to display in query mode (default: 5)",
    )
    args = parser.parse_args()

    if args.reset:
        import shutil

        if DATA_DIR.exists():
            shutil.rmtree(DATA_DIR)
            print("  🗑️  Cleared .data/ directory")
        return

    if args.query:
        query_latest(args.n)
        return

    if args.loop:
        print(f"  🔁 Looping every {args.loop}s (Ctrl+C to stop)")
        try:
            while True:
                run_pipeline()
                query_latest(1)
                time.sleep(args.loop)
        except KeyboardInterrupt:
            print("\n  ⏹️  Stopped.")
    else:
        run_pipeline()
        query_latest(args.n)


if __name__ == "__main__":
    main()
