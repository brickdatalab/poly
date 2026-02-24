from __future__ import annotations

import os
import unittest
from datetime import datetime, timezone
from pathlib import Path

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import backfill_rollups_missing_only as backfill  # noqa: E402
from alpha_v4.db import get_connection  # noqa: E402


@unittest.skipUnless(
    os.getenv("RUN_DB_INTEGRATION_TESTS") == "1",
    "Set RUN_DB_INTEGRATION_TESTS=1 to run DB-backed integration checks.",
)
class BackfillRollupsMissingOnlyIntegrationTests(unittest.TestCase):
    def test_dry_run_returns_expected_report_shape(self) -> None:
        connection = get_connection(autocommit=False)
        try:
            as_of = datetime.now(timezone.utc)
            report = backfill.run_backfill(
                connection=connection,
                start=backfill.parse_iso_utc("2026-01-26T00:00:00Z"),
                as_of=as_of,
                pairs=["BTC-USD"],
                timeframes=["15m"],
                apply=False,
            )
        finally:
            connection.rollback()
            connection.close()

        self.assertIn("generated_at", report)
        self.assertIn("apply", report)
        self.assertIn("results", report)
        self.assertFalse(report["apply"])
        self.assertEqual(len(report["results"]), 1)

        row = report["results"][0]
        expected_keys = {
            "pair",
            "timeframe",
            "table_name",
            "start",
            "end",
            "expected",
            "present",
            "missing",
            "eligible",
            "inserted",
            "skipped",
        }
        self.assertEqual(expected_keys, set(row.keys()))


if __name__ == "__main__":
    unittest.main()
