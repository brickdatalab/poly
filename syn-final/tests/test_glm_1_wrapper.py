from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

import check_inputs_glm_1 as wrapper


def test_glm_1_wrapper_runs_eth_only(monkeypatch) -> None:
    called: dict[str, object] = {}

    def fake_evaluate_indicator(indicator: str, pairs: list[str], bucket_time: str):
        called["indicator"] = indicator
        called["pairs"] = pairs
        called["bucket_time"] = bucket_time
        return {
            "indicator": indicator,
            "bucket_time_utc": bucket_time,
            "decision_time_utc": bucket_time,
            "output_path": "/tmp/ignored.json",
            "results": [],
            "signals": [],
        }

    monkeypatch.setattr(wrapper, "evaluate_indicator", fake_evaluate_indicator)
    monkeypatch.setattr(wrapper, "print_payload", lambda _: None)
    monkeypatch.setattr(wrapper, "floor_15m", lambda dt: dt)
    monkeypatch.setattr(wrapper, "iso_z", lambda _: "2026-02-14T05:15:00Z")

    rc = wrapper.main()

    assert rc == 0
    assert called["indicator"] == "GLM-1"
    assert called["pairs"] == ["ETH-USD"]

