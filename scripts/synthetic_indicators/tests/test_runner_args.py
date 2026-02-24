import importlib.util
from pathlib import Path


def _load_runner_module():
    runner_path = Path("scripts/synthetic_indicators/run_synthetic_pipeline.py").resolve()
    spec = importlib.util.spec_from_file_location("run_synthetic_pipeline", runner_path)
    module = importlib.util.module_from_spec(spec)
    assert spec and spec.loader
    spec.loader.exec_module(module)
    return module


def test_runner_accepts_backfill_and_incremental_modes():
    runner = _load_runner_module()
    args = runner.parse_args([
        "--mode",
        "backfill",
        "--from",
        "2026-01-22T07:15:00Z",
        "--to",
        "2026-02-11T00:00:00Z",
    ])
    assert args.mode == "backfill"

    args2 = runner.parse_args(["--mode", "incremental", "--batch-size", "50", "--rounds", "2"])
    assert args2.mode == "incremental"
    assert args2.batch_size == 50
    assert args2.rounds == 2
