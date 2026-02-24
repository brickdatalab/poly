from pathlib import Path


def test_raw_trade_freshness_watchdog_migration_contains_expected_bits():
    sql = Path(
        "supabase/migrations/20260211_211000_add_raw_trade_freshness_watchdog.sql"
    ).read_text().lower()

    required = [
        "create or replace function indicators.fn_raw_trades_freshness_watchdog",
        "raw-trades-freshness-watchdog",
        "cron.schedule",
        "select indicators.fn_raw_trades_freshness_watchdog",
        "net.http_post",
        "signal-pipeline-277919876041.us-central1.run.app/run",
    ]
    for token in required:
        assert token in sql
