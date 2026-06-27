"""Smoke tests for shared ingestion and transform logic.

These tests run entirely offline (no Azure credentials, no live API call)
and validate that the cloud-agnostic shared/ modules behave correctly.
"""

import json
from datetime import datetime

import pytest

from shared.ingest import fetch_data, raw_object_key, to_raw_record
from shared.transform import WAREHOUSE_TABLE_DDL, transform_record

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

SAMPLE_PAYLOAD = {
    "latitude": 48.8566,
    "longitude": 2.3522,
    "current": {
        "temperature_2m": 21.4,
        "wind_speed_10m": 14.2,
        "relative_humidity_2m": 58,
    },
}

SAMPLE_RAW_RECORD = {
    "ingested_at": "2026-06-23T14:00:00+00:00",
    "source": "open-meteo",
    "payload": SAMPLE_PAYLOAD,
}


# ---------------------------------------------------------------------------
# shared.ingest
# ---------------------------------------------------------------------------


class TestToRawRecord:
    def test_wraps_payload(self):
        record = to_raw_record(SAMPLE_PAYLOAD)
        assert record["payload"] == SAMPLE_PAYLOAD

    def test_source_field(self):
        record = to_raw_record(SAMPLE_PAYLOAD)
        assert record["source"] == "open-meteo"

    def test_ingested_at_is_iso_utc(self):
        record = to_raw_record(SAMPLE_PAYLOAD)
        # Must be parseable as an ISO-8601 datetime
        dt = datetime.fromisoformat(record["ingested_at"])
        assert dt.tzinfo is not None, "ingested_at must be timezone-aware"

    def test_returns_dict(self):
        assert isinstance(to_raw_record(SAMPLE_PAYLOAD), dict)


class TestRawObjectKey:
    def test_starts_with_raw_prefix(self):
        key = raw_object_key()
        assert key.startswith("raw/")

    def test_custom_prefix(self):
        key = raw_object_key(prefix="landing")
        assert key.startswith("landing/")

    def test_contains_year_month_day_partitions(self):
        key = raw_object_key()
        assert "year=" in key
        assert "month=" in key
        assert "day=" in key

    def test_ends_with_json(self):
        key = raw_object_key()
        assert key.endswith(".json")

    def test_key_is_unique_across_calls(self):
        """Two successive calls should produce different keys (timestamp differs)."""
        import time

        k1 = raw_object_key()
        time.sleep(0.01)
        k2 = raw_object_key()
        assert k1 != k2


# ---------------------------------------------------------------------------
# shared.transform
# ---------------------------------------------------------------------------


class TestTransformRecord:
    def test_returns_expected_keys(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        expected_keys = {
            "ingested_at",
            "latitude",
            "longitude",
            "temperature_c",
            "wind_speed_kmh",
            "humidity_pct",
        }
        assert set(row.keys()) == expected_keys

    def test_latitude_longitude_pass_through(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        assert row["latitude"] == pytest.approx(48.8566)
        assert row["longitude"] == pytest.approx(2.3522)

    def test_temperature_mapped_correctly(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        assert row["temperature_c"] == pytest.approx(21.4)

    def test_wind_speed_mapped_correctly(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        assert row["wind_speed_kmh"] == pytest.approx(14.2)

    def test_humidity_mapped_correctly(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        assert row["humidity_pct"] == 58

    def test_ingested_at_preserved(self):
        row = transform_record(SAMPLE_RAW_RECORD)
        assert row["ingested_at"] == "2026-06-23T14:00:00+00:00"

    def test_missing_current_fields_return_none(self):
        sparse = {
            "ingested_at": "2026-06-23T14:00:00+00:00",
            "source": "open-meteo",
            "payload": {"latitude": 0.0, "longitude": 0.0, "current": {}},
        }
        row = transform_record(sparse)
        assert row["temperature_c"] is None
        assert row["wind_speed_kmh"] is None
        assert row["humidity_pct"] is None

    def test_missing_current_block_returns_none(self):
        sparse = {
            "ingested_at": "2026-06-23T14:00:00+00:00",
            "source": "open-meteo",
            "payload": {"latitude": 0.0, "longitude": 0.0},
        }
        row = transform_record(sparse)
        assert row["temperature_c"] is None

    def test_roundtrip_via_json(self):
        """Transformed row must survive a JSON serialise / deserialise round-trip."""
        row = transform_record(SAMPLE_RAW_RECORD)
        reloaded = json.loads(json.dumps(row))
        assert reloaded["temperature_c"] == pytest.approx(21.4)


class TestWarehouseTableDDL:
    def test_ddl_contains_table_name(self):
        assert "weather_observations" in WAREHOUSE_TABLE_DDL

    def test_ddl_contains_required_columns(self):
        for col in (
            "ingested_at",
            "latitude",
            "longitude",
            "temperature_c",
            "wind_speed_kmh",
            "humidity_pct",
        ):
            assert col in WAREHOUSE_TABLE_DDL, f"Column '{col}' missing from DDL"


# ---------------------------------------------------------------------------
# Azure Function handler (fully offline — azure.functions mocked)
# ---------------------------------------------------------------------------


class TestAzureFunctionTransform:
    """Smoke test: the Function main() must not raise given a valid blob."""

    def _make_mock_blob(self, raw_record: dict):
        """Return a minimal mock that satisfies func.InputStream protocol."""

        class MockBlob:
            def __init__(self, data: bytes):
                self._data = data
                self.name = "raw/year=2026/month=06/day=23/test.json"

            def read(self) -> bytes:
                return self._data

        return MockBlob(json.dumps(raw_record).encode())

    def test_main_does_not_raise(self, monkeypatch):
        """main() should run without error when the TODO SQL insert is absent."""
        # Patch azure.functions so the module can be imported without the SDK
        import sys
        import types

        af_mock = types.ModuleType("azure.functions")

        class _InputStream:
            pass

        af_mock.InputStream = _InputStream
        sys.modules.setdefault("azure", types.ModuleType("azure"))
        sys.modules["azure.functions"] = af_mock

        # Re-import after patching
        if "functions.transform" in sys.modules:
            del sys.modules["functions.transform"]

        from functions.transform import main  # noqa: PLC0415

        blob = self._make_mock_blob(SAMPLE_RAW_RECORD)
        # main() only logs when SQL TODO is not implemented — must not raise
        main(blob)

    def test_transform_record_called_with_correct_payload(self):
        """Integration: to_raw_record → transform_record pipeline produces a valid row."""
        raw = to_raw_record(SAMPLE_PAYLOAD)
        row = transform_record(raw)
        assert row["latitude"] == pytest.approx(48.8566)
        assert row["temperature_c"] == pytest.approx(21.4)


# ---------------------------------------------------------------------------
# Live API smoke test (skipped in CI unless RUN_LIVE_TESTS=1 is set)
# ---------------------------------------------------------------------------


@pytest.mark.skipif(
    not __import__("os").getenv("RUN_LIVE_TESTS"),
    reason="Live API tests skipped — set RUN_LIVE_TESTS=1 to enable",
)
class TestLiveIngest:
    def test_fetch_data_returns_current_block(self):
        payload = fetch_data()
        assert "current" in payload, "Open-Meteo response missing 'current' block"
        assert "temperature_2m" in payload["current"]

    def test_full_pipeline_live(self):
        raw = to_raw_record(fetch_data())
        row = transform_record(raw)
        assert row["latitude"] is not None
        assert row["temperature_c"] is not None
