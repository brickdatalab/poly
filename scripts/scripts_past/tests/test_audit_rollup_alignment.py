from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import audit_rollup_alignment as audit  # noqa: E402


class AuditRollupAlignmentTests(unittest.TestCase):
    def test_defaults_exclude_continuous_execution(self) -> None:
        args = audit.parse_args([])
        self.assertEqual(args.pairs, "BTC-USD,ETH-USD,SOL-USD")
        self.assertEqual(args.timeframes, ",".join(audit.DEFAULT_TIMEFRAMES))
        self.assertIsNone(args.start)
        self.assertIsNone(args.end)

    def test_build_alignment_sql_contains_modulo_check(self) -> None:
        sql_text = audit.build_alignment_sql("indicators.ohlcv_15m", include_start=True, include_end=True)
        self.assertIn("indicators.ohlcv_15m", sql_text)
        self.assertIn("MOD(EXTRACT(EPOCH FROM bucket_time)::bigint, %s)", sql_text)
        self.assertIn("bucket_time >= %s::timestamptz", sql_text)
        self.assertIn("bucket_time <= %s::timestamptz", sql_text)

    def test_build_sample_sql_contains_alignment_filter(self) -> None:
        sql_text = audit.build_samples_sql("indicators.ohlcv_2h", include_start=False, include_end=False)
        self.assertIn("indicators.ohlcv_2h", sql_text)
        self.assertIn("MOD(EXTRACT(EPOCH FROM bucket_time)::bigint, %s) <> 0", sql_text)
        self.assertIn("LIMIT %s", sql_text)

    def test_parse_list_helpers(self) -> None:
        self.assertEqual(audit.parse_pairs("btc-usd,ETH-USD"), ["BTC-USD", "ETH-USD"])
        self.assertEqual(audit.parse_timeframes("5m,15m"), ["5m", "15m"])

    def test_result_row_marks_flagged_when_misaligned(self) -> None:
        row = audit.make_result_row(
            timeframe="15m",
            table_name="indicators.ohlcv_15m",
            pair="BTC-USD",
            step_minutes=15,
            total_rows=100,
            aligned_rows=98,
            misaligned_rows=2,
            samples=[
                datetime(2026, 2, 1, 0, 7, tzinfo=timezone.utc),
                datetime(2026, 2, 1, 1, 22, tzinfo=timezone.utc),
            ],
        )
        self.assertTrue(row["flagged"])
        self.assertEqual(row["misaligned_pct"], 2.0)
        self.assertEqual(len(row["sample_misaligned_buckets"]), 2)


if __name__ == "__main__":
    unittest.main()
