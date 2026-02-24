from __future__ import annotations

import unittest
from pathlib import Path

import pandas as pd
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from alpha_v4 import features  # noqa: E402


class FeatureGuardrailTests(unittest.TestCase):
    def test_clip_slope_outliers_limits_values(self) -> None:
        frame = pd.DataFrame(
            {
                "close_slope_3": [-250.0, -100.0, 0.0, 100.0, 999.0],
                "rsi_14_slope_5": [-200.0, 40.0, 250.0, None, 0.0],
            }
        )
        features._clip_slope_outliers(frame)

        self.assertEqual(frame["close_slope_3"].min(), -100.0)
        self.assertEqual(frame["close_slope_3"].max(), 100.0)
        self.assertEqual(frame["rsi_14_slope_5"].iloc[0], -100.0)
        self.assertEqual(frame["rsi_14_slope_5"].iloc[2], 100.0)

    def test_add_slope_features_applies_clipping(self) -> None:
        frame = pd.DataFrame({"close": [1.0, 1000.0, 2000.0, 3000.0, 4000.0]})
        features._add_slope_features(frame)

        slope_columns = [column for column in frame.columns if column.endswith("_slope_3")]
        self.assertTrue(slope_columns)
        for column in slope_columns:
            max_abs = frame[column].abs().max(skipna=True)
            if pd.notna(max_abs):
                self.assertLessEqual(float(max_abs), 100.0)


if __name__ == "__main__":
    unittest.main()
