import importlib.util
from pathlib import Path


def _load_module():
    path = Path("scripts/synthetic_indicators/recover_realtime_gap.py").resolve()
    spec = importlib.util.spec_from_file_location("recover_realtime_gap", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_recover_realtime_gap_accepts_expected_args():
    mod = _load_module()
    args = mod.parse_args(
        [
            "--max-lag-seconds",
            "120",
            "--pairs",
            "BTC-USD,ETH-USD",
            "--indicator-lookback-minutes",
            "45",
            "--ohlcv-lookback-hours",
            "2",
            "--dry-run",
        ]
    )
    assert args.max_lag_seconds == 120
    assert args.pairs == "BTC-USD,ETH-USD"
    assert args.indicator_lookback_minutes == 45
    assert args.ohlcv_lookback_hours == 2
    assert args.dry_run is True
