from pathlib import Path


def test_open_interest_5m_cadence_migration_shape() -> None:
    path = Path("supabase/migrations/20260225_120000_open_interest_5m_cadence.sql")
    assert path.exists(), "missing migration for OI 5-minute cadence"

    sql = path.read_text().lower()
    required = [
        "update ops.pipeline_slo_config",
        "where source in ('open_interest', 'oi_features')",
        "interval '15 minutes'",
        "'oi-ingest-main'",
        "'*/5 * * * *'",
        "'oi-ingest-retry'",
        "'2-59/5 * * * *'",
        "cron.unschedule",
        "cron.schedule",
    ]

    for item in required:
        assert item in sql


def test_open_interest_health_defaults_match_5m_cadence() -> None:
    script = Path("utility-scripts/open_interest/check_open_interest_health.py").read_text().lower()
    readme = Path("utility-scripts/open_interest/README.md").read_text().lower()

    assert "fallback_max_lag_seconds=900" in script
    assert "fallback default of 900 seconds" in readme
