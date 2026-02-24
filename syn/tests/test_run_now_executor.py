from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from run_now_executor import infer_uniform_bucket, recommend_from_triggered  # type: ignore


def test_infer_uniform_bucket_uses_previous_before_t_plus_2() -> None:
    now = datetime(2026, 2, 12, 17, 31, 0, tzinfo=timezone.utc)
    bucket = infer_uniform_bucket(now)
    assert bucket == datetime(2026, 2, 12, 17, 15, 0, tzinfo=timezone.utc)


def test_infer_uniform_bucket_uses_current_at_or_after_t_plus_2() -> None:
    now = datetime(2026, 2, 12, 17, 32, 0, tzinfo=timezone.utc)
    bucket = infer_uniform_bucket(now)
    assert bucket == datetime(2026, 2, 12, 17, 30, 0, tzinfo=timezone.utc)


def test_recommendation_prefers_majority_direction() -> None:
    triggered = [
        {"pair": "BTC-USD", "prediction": "down", "base_accuracy": 0.65, "rule_id": "a"},
        {"pair": "BTC-USD", "prediction": "down", "base_accuracy": 0.62, "rule_id": "b"},
        {"pair": "BTC-USD", "prediction": "up", "base_accuracy": 0.80, "rule_id": "c"},
    ]
    reco = recommend_from_triggered(triggered, ["BTC-USD"])
    assert reco["BTC-USD"]["recommended"] == "down"


def test_recommendation_tie_breaks_by_best_base_accuracy() -> None:
    triggered = [
        {"pair": "ETH-USD", "prediction": "down", "base_accuracy": 0.61, "rule_id": "a"},
        {"pair": "ETH-USD", "prediction": "up", "base_accuracy": 0.75, "rule_id": "b"},
    ]
    reco = recommend_from_triggered(triggered, ["ETH-USD"])
    assert reco["ETH-USD"]["recommended"] == "up"
