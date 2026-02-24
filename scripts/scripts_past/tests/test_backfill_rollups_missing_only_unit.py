from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backfill_rollups_missing_only as backfill  # noqa: E402


class BackfillRollupsMissingOnlyUnitTests(unittest.TestCase):
    def test_timeframe_specs_include_expected_defaults(self) -> None:
        expected = {"5m", "10m", "15m", "30m", "45m", "2h", "6h", "12h"}
        self.assertEqual(expected, set(backfill.DEFAULT_TIMEFRAMES))
        self.assertEqual(backfill.TIMEFRAME_SPECS["5m"].support_minutes, 5)
        self.assertEqual(backfill.TIMEFRAME_SPECS["12h"].support_minutes, 720)

    def test_last_closed_bucket_excludes_current(self) -> None:
        as_of = datetime(2026, 2, 4, 15, 33, tzinfo=timezone.utc)
        self.assertEqual(
            backfill.compute_last_closed_bucket(as_of, step_minutes=15),
            datetime(2026, 2, 4, 15, 15, tzinfo=timezone.utc),
        )
        self.assertEqual(
            backfill.compute_last_closed_bucket(as_of, step_minutes=120),
            datetime(2026, 2, 4, 12, 0, tzinfo=timezone.utc),
        )

    def test_expected_bucket_count(self) -> None:
        start = datetime(2026, 1, 26, 0, 0, tzinfo=timezone.utc)
        end = datetime(2026, 1, 26, 0, 20, tzinfo=timezone.utc)
        self.assertEqual(backfill.expected_bucket_count(start, end, step_minutes=5), 5)

    def test_parse_args_defaults_to_dry_run(self) -> None:
        args = backfill.parse_args(["--start", "2026-01-26T00:00:00Z"])
        self.assertTrue(args.dry_run)
        self.assertFalse(args.apply)
        self.assertEqual(args.pairs, ",".join(backfill.DEFAULT_PAIRS))
        self.assertEqual(args.timeframes, ",".join(backfill.DEFAULT_TIMEFRAMES))

    def test_default_report_path_shape(self) -> None:
        as_of = datetime(2026, 2, 4, 15, 33, tzinfo=timezone.utc)
        output = backfill.default_report_path(as_of)
        self.assertTrue(output.startswith("exports/rollup_backfill_missing_only_"))
        self.assertTrue(output.endswith(".json"))

    def test_run_backfill_dry_run_skips_insert(self) -> None:
        start = datetime(2026, 1, 26, 0, 0, tzinfo=timezone.utc)
        as_of = datetime(2026, 2, 4, 15, 33, tzinfo=timezone.utc)
        missing = [datetime(2026, 1, 26, 0, 5, tzinfo=timezone.utc)]
        eligible = [
            {
                "bucket_time": datetime(2026, 1, 26, 0, 5, tzinfo=timezone.utc),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "buy_volume": 1,
                "sell_volume": 1,
                "trade_count": 1,
            }
        ]
        with patch.object(backfill, "fetch_present_count", return_value=1), patch.object(
            backfill, "fetch_missing_buckets", return_value=missing
        ), patch.object(backfill, "fetch_eligible_rollups", return_value=eligible), patch.object(
            backfill, "insert_rollups", return_value=99
        ) as insert_mock:
            report = backfill.run_backfill(
                connection=object(),
                start=start,
                as_of=as_of,
                pairs=["BTC-USD"],
                timeframes=["5m"],
                apply=False,
            )
        self.assertEqual(report["results"][0]["inserted"], 0)
        self.assertEqual(report["results"][0]["missing"], 1)
        self.assertEqual(report["results"][0]["eligible"], 1)
        self.assertEqual(report["results"][0]["skipped"], 0)
        insert_mock.assert_not_called()

    def test_run_backfill_apply_calls_insert(self) -> None:
        start = datetime(2026, 1, 26, 0, 0, tzinfo=timezone.utc)
        as_of = datetime(2026, 2, 4, 15, 33, tzinfo=timezone.utc)
        eligible = [
            {
                "bucket_time": datetime(2026, 1, 26, 0, 5, tzinfo=timezone.utc),
                "open": 1,
                "high": 1,
                "low": 1,
                "close": 1,
                "volume": 1,
                "buy_volume": 1,
                "sell_volume": 1,
                "trade_count": 1,
            }
        ]
        with patch.object(backfill, "fetch_present_count", return_value=1), patch.object(
            backfill, "fetch_missing_buckets", return_value=[eligible[0]["bucket_time"]]
        ), patch.object(backfill, "fetch_eligible_rollups", return_value=eligible), patch.object(
            backfill, "insert_rollups", return_value=1
        ) as insert_mock:
            report = backfill.run_backfill(
                connection=object(),
                start=start,
                as_of=as_of,
                pairs=["BTC-USD"],
                timeframes=["5m"],
                apply=True,
            )
        self.assertEqual(report["results"][0]["inserted"], 1)
        insert_mock.assert_called_once()


if __name__ == "__main__":
    unittest.main()
