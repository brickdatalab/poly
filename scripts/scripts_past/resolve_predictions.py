from __future__ import annotations

import argparse

from alpha_v4.db import get_connection
from alpha_v4.pipeline import resolve_due_predictions
from alpha_v4.time_utils import parse_iso_utc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Resolve due alpha_v4 predictions.")
    parser.add_argument("--now", help="Override current UTC time (ISO-8601).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = parse_iso_utc(args.now)
    connection = get_connection(autocommit=False)
    try:
        resolved = resolve_due_predictions(connection, as_of=now)
        connection.commit()
        print(f"Resolved predictions: {resolved}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Resolve failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

