from __future__ import annotations

import argparse

from alpha_v4.db import get_connection
from alpha_v4.pipeline import export_predictions


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export alpha_v4 prediction results to CSV.")
    parser.add_argument(
        "--out",
        default="exports/alpha_v4_predictions.csv",
        help="Output CSV path.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    connection = get_connection(autocommit=False)
    try:
        count = export_predictions(connection, output_path=args.out)
        connection.commit()
        print(f"Exported {count} rows to {args.out}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Export failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

