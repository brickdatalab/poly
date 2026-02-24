from pathlib import Path


def test_runner_references_synthetic_functions_only():
    text = Path("scripts/synthetic_indicators/run_synthetic_pipeline.py").read_text()
    assert "fn_backfill_synthetic_indicators" in text
    assert "fn_enqueue_synthetic_jobs" in text
    assert "fn_process_synthetic_jobs" in text
    assert "indicators.job_queue" not in text
