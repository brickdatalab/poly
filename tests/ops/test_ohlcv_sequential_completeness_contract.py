from __future__ import annotations

import importlib.util
import sys
from pathlib import Path
from types import ModuleType


def _load_module() -> ModuleType:
    path = Path("utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py").resolve()
    spec = importlib.util.spec_from_file_location("check_ohlcv_sequential_completeness", path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load check_ohlcv_sequential_completeness module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_timeframe_specs_include_12h() -> None:
    mod = _load_module()
    assert ("12h", 43200) in mod.TIMEFRAME_SPECS


def test_build_timeframe_sql_contains_required_integrity_checks() -> None:
    mod = _load_module()
    sql = mod.build_timeframe_sql(
        schema="indicators",
        timeframe="12h",
        step_seconds=43200,
        pairs=("BTC-USD", "ETH-USD"),
        days=5,
    ).lower()

    required = [
        "generate_series",
        "left join actual_distinct",
        "missing_rows",
        "duplicate_rows",
        "misaligned_rows",
        "gap_violations",
        "indicators.ohlcv_12h",
    ]
    for item in required:
        assert item in sql


def test_build_timeframe_sql_excludes_partial_leading_bucket() -> None:
    mod = _load_module()
    sql = mod.build_timeframe_sql(
        schema="indicators",
        timeframe="5m",
        step_seconds=300,
        pairs=("BTC-USD",),
        days=5,
    ).lower()

    required = [
        "window_start",
        "when start_ts = start_aligned then start_aligned",
        "else start_aligned + interval '1 second' * 300",
        "bucket_aligned >= window_bounds.window_start",
    ]
    for item in required:
        assert item in sql


def test_legacy_wrapper_points_to_canonical_location() -> None:
    wrapper = Path("scripts/ops/check_ohlcv_sequential_completeness.py").read_text()
    assert '"utility-scripts"' in wrapper
    assert '"ohlcv"' in wrapper
