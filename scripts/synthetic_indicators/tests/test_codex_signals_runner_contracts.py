from pathlib import Path


def test_codex_runner_references_codex_queue_functions_only():
    text = Path("scripts/synthetic_indicators/run_codex_signals.py").read_text()
    assert "fn_enqueue_codex_signal_jobs" in text
    assert "fn_process_codex_signal_jobs" in text
    assert "fn_backfill" not in text.lower()
