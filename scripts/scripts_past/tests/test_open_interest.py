from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_v4.open_interest import (  # noqa: E402
    CandleSnapshot,
    OpenInterestSnapshot,
    build_feature_row,
    build_candle_snapshot_from_ohlcv_rows,
    create_table_sql,
    floor_to_15m_bucket,
    parse_args,
    parse_open_interest_hist_snapshot,
    parse_open_interest_snapshot,
)


class OpenInterestTests(unittest.TestCase):
    def test_parse_open_interest_snapshot(self) -> None:
        payload = {
            "symbol": "ETHUSDT",
            "openInterest": "712345.90000000",
            "time": 1737609000000,
        }

        snapshot = parse_open_interest_snapshot(payload)

        self.assertEqual(snapshot.symbol, "ETH")
        self.assertAlmostEqual(snapshot.open_interest, 712345.9)
        self.assertEqual(
            snapshot.source_time,
            datetime.fromtimestamp(1737609000, tz=timezone.utc),
        )

    def test_build_feature_row_flags_weak_rally(self) -> None:
        oi_snapshot = OpenInterestSnapshot(
            symbol="BTC",
            open_interest=900000.0,
            source_time=datetime(2026, 2, 4, 12, 15, tzinfo=timezone.utc),
        )
        candle = CandleSnapshot(
            bucket_time=datetime(2026, 2, 4, 12, 15, tzinfo=timezone.utc),
            close_price=101.0,
            prev_close_price=100.0,
            volume=2000.0,
        )

        row = build_feature_row(oi_snapshot, candle, previous_oi=905000.0)

        self.assertAlmostEqual(row["oi_change"], -5000.0)
        self.assertAlmostEqual(row["price_change_pct"], 0.01)
        self.assertAlmostEqual(row["oi_volume_ratio"], 450.0)
        self.assertEqual(row["oi_divergence"], 1)
        self.assertEqual(row["weak_rally"], 1)
        self.assertEqual(row["weak_selloff"], 0)

    def test_build_feature_row_flags_weak_selloff(self) -> None:
        oi_snapshot = OpenInterestSnapshot(
            symbol="SOL",
            open_interest=120000.0,
            source_time=datetime(2026, 2, 4, 12, 30, tzinfo=timezone.utc),
        )
        candle = CandleSnapshot(
            bucket_time=datetime(2026, 2, 4, 12, 30, tzinfo=timezone.utc),
            close_price=98.0,
            prev_close_price=100.0,
            volume=3000.0,
        )

        row = build_feature_row(oi_snapshot, candle, previous_oi=118000.0)

        self.assertAlmostEqual(row["oi_change"], 2000.0)
        self.assertAlmostEqual(row["price_change_pct"], -0.02)
        self.assertEqual(row["oi_divergence"], 1)
        self.assertEqual(row["weak_rally"], 0)
        self.assertEqual(row["weak_selloff"], 1)

    def test_create_table_sql_targets_indicators_schema(self) -> None:
        sql = create_table_sql()
        self.assertIn("CREATE SCHEMA IF NOT EXISTS indicators", sql)
        self.assertIn("CREATE TABLE IF NOT EXISTS indicators.open_interest", sql)
        self.assertIn("PRIMARY KEY (symbol, bucket_time)", sql)
        self.assertIn("pair text", sql)

    def test_build_candle_snapshot_from_ohlcv_rows_uses_latest_closed_candle(self) -> None:
        rows = [
            {
                "bucket_time": datetime(2026, 2, 4, 12, 30, tzinfo=timezone.utc),
                "close": 102.0,
                "volume": 3456.0,
            },
            {
                "bucket_time": datetime(2026, 2, 4, 12, 15, tzinfo=timezone.utc),
                "close": 100.0,
                "volume": 3210.0,
            },
        ]

        snapshot = build_candle_snapshot_from_ohlcv_rows(rows)

        self.assertEqual(snapshot.bucket_time, rows[0]["bucket_time"])
        self.assertAlmostEqual(snapshot.close_price, 102.0)
        self.assertAlmostEqual(snapshot.prev_close_price, 100.0)
        self.assertAlmostEqual(snapshot.volume, 3456.0)

    def test_parse_args_supports_api_server_mode(self) -> None:
        args = parse_args(["--serve", "--port", "9090", "--symbols", "BTC,ETH"])
        self.assertTrue(args.serve)
        self.assertEqual(args.port, 9090)
        self.assertEqual(args.symbols, "BTC,ETH")

    def test_parse_open_interest_hist_snapshot(self) -> None:
        payload = {
            "symbol": "BTCUSDT",
            "sumOpenInterest": "1023112.0",
            "timestamp": 1767225600000,
        }
        snapshot = parse_open_interest_hist_snapshot(payload)
        self.assertEqual(snapshot.symbol, "BTC")
        self.assertAlmostEqual(snapshot.open_interest, 1023112.0)
        self.assertEqual(
            snapshot.source_time,
            datetime.fromtimestamp(1767225600, tz=timezone.utc),
        )

    def test_floor_to_15m_bucket(self) -> None:
        value = datetime(2026, 2, 4, 12, 37, 45, tzinfo=timezone.utc)
        self.assertEqual(
            floor_to_15m_bucket(value),
            datetime(2026, 2, 4, 12, 30, tzinfo=timezone.utc),
        )


if __name__ == "__main__":
    unittest.main()
