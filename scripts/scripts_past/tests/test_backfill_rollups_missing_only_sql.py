from __future__ import annotations

import unittest
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backfill_rollups_missing_only as backfill  # noqa: E402


class BackfillRollupsMissingOnlySqlTests(unittest.TestCase):
    def test_missing_buckets_sql_uses_expected_series(self) -> None:
        sql_text = backfill.build_missing_buckets_sql("indicators.ohlcv_15m")
        self.assertIn("generate_series", sql_text)
        self.assertIn("LEFT JOIN", sql_text)
        self.assertIn("WHERE actual.bucket_time IS NULL", sql_text)
        self.assertIn("indicators.ohlcv_15m", sql_text)

    def test_eligible_rollup_sql_requires_full_1m_support(self) -> None:
        sql_text = backfill.build_eligible_rollup_sql(step_minutes=15)
        self.assertIn("COUNT(src.bucket_time)::int AS support_count", sql_text)
        self.assertIn("src.bucket_time < missing.bucket_time + interval '15 minutes'", sql_text)
        self.assertIn("ARRAY_AGG(src.open ORDER BY src.bucket_time ASC)", sql_text)
        self.assertIn("SUM(src.trade_count)::int", sql_text)

    def test_insert_sql_is_missing_only(self) -> None:
        sql_text = backfill.build_insert_sql("indicators.ohlcv_15m")
        self.assertIn("ON CONFLICT (pair, bucket_time) DO NOTHING", sql_text)
        self.assertNotIn("DO UPDATE", sql_text)
        self.assertIn("INSERT INTO indicators.ohlcv_15m", sql_text)


if __name__ == "__main__":
    unittest.main()
