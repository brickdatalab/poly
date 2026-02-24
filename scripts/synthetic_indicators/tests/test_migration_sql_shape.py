from pathlib import Path


def test_migration_contains_required_tables_and_comments():
    sql = Path("supabase/migrations/20260211_150000_create_synthetic_indicator_tables.sql").read_text()
    required = [
        "create table if not exists indicators.synthetic_indicator_configs",
        "create table if not exists indicators.synthetic_indicator_values",
        "create table if not exists indicators.synthetic_job_queue",
        "comment on table indicators.synthetic_indicator_configs",
        "comment on table indicators.synthetic_indicator_values",
        "comment on column indicators.synthetic_indicator_values.v1",
        "unique (pair, bucket_time, config_id)",
    ]
    for r in required:
        assert r.lower() in sql.lower()
