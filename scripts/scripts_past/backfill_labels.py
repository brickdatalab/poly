from __future__ import annotations

import argparse
from datetime import timezone

import numpy as np

from alpha_v4.config import TIMEFRAMES
from alpha_v4.data_access import fetch_training_frame_all_symbols
from alpha_v4.db import get_connection, upsert_rows
from alpha_v4.features import normalize_training_dataframe

FIFTEEN_MINUTE_MAGNITUDE_BOUNDS = [0.1, 0.3, 0.5, 0.8, 1.2, 1.8, 2.5, 3.5, 5.0]
ONE_HOUR_MAGNITUDE_BOUNDS = [0.2, 0.6, 1.0, 1.5, 2.2, 3.2, 4.5, 6.0, 8.0]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Backfill alpha_v4.labels from training tables.")
    parser.add_argument("--start", default="2021-01-01", help="Inclusive start timestamp/date.")
    parser.add_argument("--end", default="2026-01-01", help="Exclusive end timestamp/date.")
    return parser.parse_args()


def magnitude_from_pct_change(pct_change: float, timeframe: str) -> int:
    bounds = (
        FIFTEEN_MINUTE_MAGNITUDE_BOUNDS
        if timeframe == "15m"
        else ONE_HOUR_MAGNITUDE_BOUNDS
    )
    absolute_change = abs(float(pct_change))
    for index, bound in enumerate(bounds, start=1):
        if absolute_change <= bound:
            return index
    return 10


def build_rows_for_timeframe(connection, timeframe: str, start: str, end: str) -> list[dict]:
    frame = fetch_training_frame_all_symbols(
        connection,
        timeframe=timeframe,
        start_date=start,
        end_date=end,
    )
    if frame.empty:
        return []

    frame = normalize_training_dataframe(frame)
    frame["bucket_time"] = frame["bucket_time"].dt.tz_convert(timezone.utc)
    frame["next_pct_change"] = frame["next_pct_change"].fillna(0.0)
    inferred_label = np.where(frame["next_pct_change"] > 0, "UP", "DOWN")
    frame["next_label"] = frame["next_label"].where(frame["next_label"].notna(), inferred_label)
    inferred_binary = np.where(frame["next_label"] == "UP", 1, 0)
    frame["next_label_binary"] = frame["next_label_binary"].where(
        frame["next_label_binary"].notna(), inferred_binary
    )

    significance_threshold = 0.05 if timeframe == "15m" else 0.15
    rows = []
    for _, row in frame.iterrows():
        pct_change = float(row["next_pct_change"])
        rows.append(
            {
                "symbol": row["symbol"],
                "bucket_time": row["bucket_time"].to_pydatetime(),
                "timeframe": timeframe,
                "label": str(row["next_label"]),
                "label_binary": int(row["next_label_binary"]),
                "pct_change": pct_change,
                "magnitude": magnitude_from_pct_change(pct_change, timeframe),
                "is_significant": int(abs(pct_change) > significance_threshold),
            }
        )
    return rows


def main() -> int:
    args = parse_args()
    connection = get_connection(autocommit=False)
    try:
        total = 0
        for timeframe in TIMEFRAMES:
            rows = build_rows_for_timeframe(connection, timeframe, args.start, args.end)
            upsert_rows(
                connection,
                "alpha_v4.labels",
                rows,
                key_columns=["symbol", "bucket_time", "timeframe"],
            )
            total += len(rows)
            print(f"{timeframe}: upserted {len(rows)} labels")
        connection.commit()
        print(f"Total upserted labels: {total}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Label backfill failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
