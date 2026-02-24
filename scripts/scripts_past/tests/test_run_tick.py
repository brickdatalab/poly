from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import run_tick  # noqa: E402


class RunTickCatchUpTests(unittest.TestCase):
    def test_missing_current_event_predictions_true_when_rows_missing(self) -> None:
        now = datetime(2026, 2, 4, 19, 7, tzinfo=timezone.utc)
        with patch.object(run_tick, "fetch_one", return_value={"row_count": 0}):
            self.assertTrue(
                run_tick._missing_current_event_predictions(object(), timeframe="15m", now=now)
            )

    def test_missing_current_event_predictions_false_when_complete(self) -> None:
        now = datetime(2026, 2, 4, 19, 7, tzinfo=timezone.utc)
        with patch.object(run_tick, "fetch_one", return_value={"row_count": 3}):
            self.assertFalse(
                run_tick._missing_current_event_predictions(object(), timeframe="15m", now=now)
            )

    def test_missing_current_event_predictions_respects_grace_window(self) -> None:
        now = datetime(2026, 2, 4, 19, 0, tzinfo=timezone.utc)
        with patch.object(run_tick, "fetch_one", return_value={"row_count": 0}) as mocked:
            result = run_tick._missing_current_event_predictions(
                object(), timeframe="15m", now=now
            )
        self.assertFalse(result)
        mocked.assert_not_called()

    def test_frames_to_run_includes_catchup_timeframe(self) -> None:
        now = datetime(2026, 2, 4, 19, 7, tzinfo=timezone.utc)

        def fake_fetch_one(_connection, _query: str, params=None):
            timeframe = params[0]
            if timeframe == "15m":
                return {"row_count": 0}
            return {"row_count": 3}

        with patch.object(run_tick, "fetch_one", side_effect=fake_fetch_one):
            frames = run_tick._frames_to_run(object(), now=now, force=False)
        self.assertEqual(frames, ["15m"])

    def test_frames_to_run_force_returns_all_timeframes(self) -> None:
        now = datetime(2026, 2, 4, 19, 7, tzinfo=timezone.utc)
        frames = run_tick._frames_to_run(object(), now=now, force=True)
        self.assertEqual(frames, ["15m", "1h"])


if __name__ == "__main__":
    unittest.main()
