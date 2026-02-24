import importlib.util
from pathlib import Path


def _load_module():
    path = Path("scripts/synthetic_indicators/backfill_signal_runtime_audit.py").resolve()
    spec = importlib.util.spec_from_file_location("backfill_signal_runtime_audit", path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_backfill_signal_runtime_audit_args():
    mod = _load_module()
    args = mod.parse_args(
        [
            "--from",
            "2026-02-11 19:00:00+00",
            "--to",
            "2026-02-11 21:00:00+00",
            "--pairs",
            "BTC-USD,ETH-USD",
        ]
    )
    assert args.from_ts == "2026-02-11 19:00:00+00"
    assert args.to_ts == "2026-02-11 21:00:00+00"
    assert args.pairs == "BTC-USD,ETH-USD"
