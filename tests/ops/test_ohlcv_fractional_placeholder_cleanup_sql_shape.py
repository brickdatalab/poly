from pathlib import Path


def test_ohlcv_fractional_placeholder_cleanup_migration_shape() -> None:
    path = Path("supabase/migrations/20260225_110000_ohlcv_fractional_placeholder_cleanup.sql")
    assert path.exists(), "missing migration for OHLCV fractional placeholder cleanup"

    sql = path.read_text().lower()
    required = [
        "create or replace function ops.fn_cleanup_ohlcv_1m_fractional_placeholders",
        "delete from indicators.ohlcv_1m",
        "bucket_time <> date_trunc('minute', bucket_time)",
        "coalesce(volume, 0) = 0",
        "coalesce(trade_count, 0) = 0",
        "create or replace function ops.fn_repair_ohlcv_issue3",
        "ops.fn_repair_ohlcv_chain",
        "continuity_rows_inserted",
    ]

    for item in required:
        assert item in sql
