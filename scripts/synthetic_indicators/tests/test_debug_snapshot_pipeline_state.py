from pathlib import Path


def test_debug_snapshot_script_contains_required_output_keys():
    text = Path("scripts/synthetic_indicators/debug_snapshot_pipeline_state.py").read_text()
    required = [
        "captured_at_utc",
        "raw_trades_max",
        "ohlcv_1m_max",
        "ohlcv_15m_max",
        "indicator_values_max",
        "synthetic_values_max",
        "codex_signals_max",
        "cron_jobs",
        "cron_recent_runs",
        "queue_counts",
    ]
    for token in required:
        assert token in text
