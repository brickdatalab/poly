from pathlib import Path


def test_ops_pipeline_supervisor_sql_contains_required_objects() -> None:
    sql = Path("supabase/migrations/20260224_170000_ops_pipeline_supervisor.sql").read_text()
    required = [
        "create schema if not exists ops",
        "create table if not exists ops.pipeline_slo_config",
        "create table if not exists ops.pipeline_runtime_config",
        "create table if not exists ops.pipeline_action_cooldowns",
        "create table if not exists ops.pipeline_health_log",
        "create table if not exists ops.pipeline_action_log",
        "create table if not exists ops.pipeline_incident_log",
        "create or replace function ops.fn_pipeline_health_snapshot",
        "create or replace function ops.fn_pipeline_supervisor_tick",
        "create or replace function ops.fn_run_recovery_window",
        "create or replace function ops.fn_repair_ohlcv_1m_continuity",
        "date_trunc('minute', p_start)",
        "date_trunc('minute', p_end)",
        "create or replace function ops.fn_repair_ohlcv_chain",
        "create or replace function ops.fn_pipeline_health_watchdog",
        "'pipeline-supervisor-tick'",
        "'pipeline-health-watchdog'",
        "'run-indicator-worker-backstop'",
        "'oi-ingest-main'",
        "'oi-ingest-retry'",
        "'oi-reconcile'",
    ]

    lowered = sql.lower()
    for item in required:
        assert item.lower() in lowered
