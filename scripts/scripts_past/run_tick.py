from __future__ import annotations

import argparse
import json
from datetime import timedelta, timezone

from alpha_v4.config import SYMBOLS, TIMEFRAMES
from alpha_v4.db import fetch_one, get_connection
from alpha_v4.pipeline import export_predictions, generate_prediction, resolve_due_predictions, update_performance_log
from alpha_v4.time_utils import due_timeframes, event_timing, parse_iso_utc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Run one alpha_v4 pipeline tick.")
    parser.add_argument("--now", help="Override current UTC time (ISO-8601).")
    parser.add_argument(
        "--force",
        action="store_true",
        help="Run both timeframes regardless of schedule alignment.",
    )
    parser.add_argument(
        "--skip-export",
        action="store_true",
        help="Skip CSV export at the end of the tick.",
    )
    parser.add_argument(
        "--export-out",
        default="exports/alpha_v4_predictions.csv",
        help="CSV export path when export is enabled.",
    )
    return parser.parse_args()


def _missing_current_event_predictions(connection, timeframe: str, now) -> bool:
    timing = event_timing(now, timeframe)
    grace_start = timing.event_start + timedelta(minutes=1)
    if now < grace_start or now >= timing.event_end:
        return False
    row = fetch_one(
        connection,
        """
        SELECT COUNT(*)::int AS row_count
        FROM alpha_v4.predictions
        WHERE timeframe = %s
          AND event_start = %s
        """,
        (timeframe, timing.event_start),
    )
    return int(row["row_count"] or 0) < len(SYMBOLS)


def _frames_to_run(connection, now, force: bool) -> list[str]:
    if force:
        return list(TIMEFRAMES)
    frames = due_timeframes(now, force=False)
    for timeframe in TIMEFRAMES:
        if timeframe in frames:
            continue
        if _missing_current_event_predictions(connection, timeframe=timeframe, now=now):
            frames.append(timeframe)
    return frames


def main() -> int:
    args = parse_args()
    now = parse_iso_utc(args.now).astimezone(timezone.utc).replace(second=0, microsecond=0)
    connection = get_connection(autocommit=False)
    try:
        frames_to_run = _frames_to_run(connection, now, force=args.force)
        if not frames_to_run:
            print("No due or catch-up timeframes at this timestamp. Use --force to run manually.")
            return 0

        generated = []
        for timeframe in frames_to_run:
            timing = event_timing(now, timeframe)
            for symbol in SYMBOLS:
                generated_row = generate_prediction(
                    connection,
                    symbol=symbol,
                    timeframe=timeframe,
                    event_start=timing.event_start,
                    event_end=timing.event_end,
                    feature_time=timing.feature_time,
                    now=now,
                )
                generated.append(
                    {
                        "symbol": symbol,
                        "timeframe": timeframe,
                        "event_start": timing.event_start.isoformat(),
                        "event_end": timing.event_end.isoformat(),
                        "prediction": generated_row["prediction"],
                        "confidence_tier": generated_row["confidence_tier"],
                        "ensemble_probability": generated_row["ensemble_probability"],
                    }
                )

        resolved = resolve_due_predictions(connection, as_of=now)
        perf_rows = update_performance_log(connection, as_of=now)
        exported_rows = None
        if not args.skip_export:
            exported_rows = export_predictions(connection, output_path=args.export_out)

        connection.commit()
        result = {
            "run_at": now.isoformat(),
            "generated": generated,
            "resolved_count": resolved,
            "performance_rows_upserted": perf_rows,
            "exported_rows": exported_rows,
        }
        print(json.dumps(result, indent=2))
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Tick failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())
