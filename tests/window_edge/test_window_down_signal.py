from __future__ import annotations

import importlib.util
import sys
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

SCRIPT_PATH = ROOT / "scripts" / "window_edge" / "window_down_signal.py"
SPEC = importlib.util.spec_from_file_location("window_down_signal", SCRIPT_PATH)
assert SPEC and SPEC.loader
window_down_signal = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(window_down_signal)


def test_floor_to_quarter_hour_utc() -> None:
    now = datetime(2026, 2, 13, 17, 2, 10, tzinfo=timezone.utc)
    got = window_down_signal.floor_to_quarter_hour(now)
    assert got == datetime(2026, 2, 13, 17, 0, 0, tzinfo=timezone.utc)


def test_best_down_sigma_eth_respects_min_sigma() -> None:
    got = window_down_signal.best_down_sigma("ETH-USD", -0.20)
    assert got == 0.75


def test_best_down_sigma_btc_respects_min_sigma() -> None:
    got = window_down_signal.best_down_sigma("BTC-USD", -0.30)
    assert got == 1.0


def test_best_down_sigma_returns_none_when_not_passing_threshold() -> None:
    got = window_down_signal.best_down_sigma("BTC-USD", -0.10)
    assert got is None


def test_render_lines_order_and_format() -> None:
    payload = {"ETH-USD": 0.75, "BTC-USD": None}
    lines = window_down_signal.render_lines(payload)
    assert lines == ["ETH-USD: +0.75σ", "BTC-USD: none"]
