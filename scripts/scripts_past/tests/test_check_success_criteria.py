from __future__ import annotations

import unittest
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import patch

import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

import check_success_criteria as checklist  # noqa: E402


class SuccessCriteriaCheckerTests(unittest.TestCase):
    def test_check_result_warn_keeps_passed_true(self) -> None:
        result = checklist.CheckResult(
            name="No data gaps (7d)",
            passed=False,
            status=checklist.CHECK_STATUS_WARN,
            details="sample",
        )
        self.assertTrue(result.passed)
        self.assertEqual(result.status, checklist.CHECK_STATUS_WARN)
        payload = result.as_dict()
        self.assertIn("status", payload)
        self.assertTrue(payload["passed"])

    def test_parse_args_defaults_to_full_profile(self) -> None:
        args = checklist.parse_args([])
        self.assertEqual(args.profile, "full")
        self.assertIsNone(args.as_of)

    def test_build_checks_core_excludes_depth_checks(self) -> None:
        as_of = datetime(2026, 2, 4, 15, 0, tzinfo=timezone.utc)
        core_names = [check.name for check in checklist.build_checks(profile="core", as_of=as_of)]
        full_names = [check.name for check in checklist.build_checks(profile="full", as_of=as_of)]
        self.assertNotIn("No data gaps (7d)", core_names)
        self.assertIn("No data gaps (7d)", full_names)
        self.assertGreater(len(full_names), len(core_names))

    def test_gap_policy_returns_warn_with_gap_details(self) -> None:
        as_of = datetime(2026, 2, 4, 15, 0, tzinfo=timezone.utc)

        def fake_fetch_one(_connection, query: str, params=None):
            if "missing_count" in query:
                return {"missing_count": 1}
            return {"missing_count": 0}

        def fake_fetch_all(_connection, _query: str, params=None):
            if params and len(params) >= 2:
                return [{"bucket_time": params[0]}]
            return [{"bucket_time": datetime(2026, 2, 4, 0, 0, tzinfo=timezone.utc)}]

        with patch.object(checklist, "fetch_one", side_effect=fake_fetch_one), patch.object(
            checklist, "fetch_all", side_effect=fake_fetch_all
        ):
            result = checklist._check_no_data_gaps_7d(connection=object(), as_of=as_of)

        self.assertEqual(result.status, checklist.CHECK_STATUS_WARN)
        self.assertTrue(result.passed)
        self.assertIn("missing=", result.details)

    def test_summarize_results_warn_is_not_fail(self) -> None:
        results = [
            checklist.CheckResult("a", True, "ok", checklist.CHECK_STATUS_PASS),
            checklist.CheckResult("b", True, "warn", checklist.CHECK_STATUS_WARN),
            checklist.CheckResult("c", False, "bad", checklist.CHECK_STATUS_FAIL),
        ]
        summary = checklist.summarize_results(results)
        self.assertEqual(summary["passed"], 2)
        self.assertEqual(summary["warnings"], 1)
        self.assertEqual(summary["failed"], 1)


if __name__ == "__main__":
    unittest.main()
