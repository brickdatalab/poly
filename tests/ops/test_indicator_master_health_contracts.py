from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_indicator_master_health_migration_shape() -> None:
    path = Path("supabase/migrations/20260225_130000_indicator_master_health_and_latency.sql")
    assert path.exists(), "missing migration for indicator master health + latency"

    sql = path.read_text().lower()
    required = [
        "create table if not exists ops.master_indicator_registry",
        "indicator_key text primary key",
        "availability_mode text not null",
        "create or replace function ops.fn_sync_master_indicator_registry",
        "create or replace function ops.fn_indicator_master_health_snapshot",
        "no_data_in_window",
        "lag_exceeded",
        "missing_expected_bucket",
        "gap_violation",
        "duplicate_buckets",
        "misaligned_buckets",
        "dependency_stale",
        "config_count_mismatch",
        "registry_drift",
        "query_error",
        "no active column",
    ]
    for item in required:
        assert item in sql


def test_indicator_master_schema_contract_files() -> None:
    paths = [
        Path("contracts/openai/master_indicator_registry.schema.json"),
        Path("contracts/openai/indicator_health_check_input.schema.json"),
        Path("contracts/openai/indicator_health_report.schema.json"),
    ]
    for path in paths:
        assert path.exists(), f"missing schema: {path}"
        payload = _load_json(path)
        assert payload.get("strict") is True
        assert payload.get("schema", {}).get("additionalProperties") is False


def test_indicator_master_utility_script_contract() -> None:
    script = Path("utility-scripts/indicators/check_indicator_master_health.py")
    readme = Path("utility-scripts/indicators/README.md")
    assert script.exists(), "missing indicator master utility script"
    assert readme.exists(), "missing indicator utility README"

    src = script.read_text().lower()
    assert "fn_indicator_master_health_snapshot" in src
    assert "exit" in src
    assert "traffic_light" in src
