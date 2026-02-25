from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _module_path() -> Path:
    return Path("utility-scripts/source_health/common.py").resolve()


def _load_module() -> ModuleType:
    path = _module_path()
    spec = importlib.util.spec_from_file_location("source_health_common", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load source_health common module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_shared_source_health_module_exists() -> None:
    assert _module_path().exists()


def test_build_realtime_source_sql_uses_slo_config_and_continuity() -> None:
    mod = _load_module()
    sql = mod.build_realtime_source_health_sql(
        source="market_context",
        table="public.market_context",
        ts_column="timestamp",
        pairs=("BTC-USD", "ETH-USD"),
        lookback_minutes=180,
    ).lower()

    required = [
        "ops.pipeline_slo_config",
        "market_context",
        "generate_series",
        "missing_minutes",
        "lag_seconds",
        "rows_per_minute",
        "public.market_context",
    ]
    for item in required:
        assert item in sql


def test_build_open_interest_sql_uses_step_and_gap_checks() -> None:
    mod = _load_module()
    sql = mod.build_open_interest_health_sql(
        source="open_interest",
        table="indicators.open_interest",
        ts_column="bucket_time",
        pairs=("BTC-USD", "ETH-USD"),
        lookback_hours=72,
        step_seconds=900,
    ).lower()

    required = [
        "ops.pipeline_slo_config",
        "open_interest",
        "generate_series",
        "missing_buckets",
        "gap_violations",
        "misaligned_rows",
        "duplicate_rows",
        "indicators.open_interest",
    ]
    for item in required:
        assert item in sql


def test_dataset_utility_scripts_exist() -> None:
    expected = (
        Path("utility-scripts/market_context/check_market_context_health.py"),
        Path("utility-scripts/order_book/check_order_book_snapshots_health.py"),
        Path("utility-scripts/open_interest/check_open_interest_health.py"),
    )
    for path in expected:
        assert path.exists(), f"Missing utility script: {path}"
