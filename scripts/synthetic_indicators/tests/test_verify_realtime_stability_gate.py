from pathlib import Path


def test_verify_stability_gate_has_required_checks():
    text = Path("scripts/synthetic_indicators/verify_realtime_stability_gate.py").read_text().lower()
    required = [
        "raw-trades-max-lag-seconds",
        "ohlcv-1m-max-lag-seconds",
        "indicator-values-max-lag-seconds",
        "codex_signal_runtime_audit",
        "cron.job_run_details",
        "missing signal/audit coverage",
    ]
    for token in required:
        assert token in text
