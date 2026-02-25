from __future__ import annotations

import json
from pathlib import Path


def _load_json(path: Path) -> dict:
    return json.loads(path.read_text())


def test_indicator_latency_migration_shape() -> None:
    path = Path("supabase/migrations/20260225_130000_indicator_master_health_and_latency.sql")
    assert path.exists(), "missing migration for indicator latency"

    sql = path.read_text().lower()
    required = [
        "create table if not exists ops.indicator_latency_slo_config",
        "create table if not exists ops.indicator_latency_log",
        "create or replace function ops.fn_indicator_compute_latency_snapshot",
        "create or replace function ops.fn_indicator_latency_watchdog",
        "latency_p95_breach",
        "latency_p99_breach",
        "latency_hard_fail",
        "insufficient_samples",
        "upstream_close_delay",
        "queue_backlog_pressure",
        "worker_stall",
        "query_error",
    ]
    for item in required:
        assert item in sql


def test_indicator_latency_schema_contract_file() -> None:
    path = Path("contracts/openai/indicator_compute_latency_report.schema.json")
    assert path.exists(), "missing latency schema"
    payload = _load_json(path)
    assert payload.get("strict") is True
    assert payload.get("schema", {}).get("additionalProperties") is False


def test_indicator_latency_utility_script_contract() -> None:
    script = Path("utility-scripts/indicators/check_indicator_compute_latency.py")
    assert script.exists(), "missing indicator latency utility script"

    src = script.read_text().lower()
    assert "fn_indicator_compute_latency_snapshot" in src
    assert "p95_latency_seconds" in src
    assert "p99_latency_seconds" in src
