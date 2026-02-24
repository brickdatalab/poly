from __future__ import annotations

import argparse

from alpha_v4.db import get_connection
from alpha_v4.pipeline import update_performance_log
from alpha_v4.time_utils import parse_iso_utc


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Update alpha_v4.performance_log windows.")
    parser.add_argument("--now", help="Override current UTC time (ISO-8601).")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now = parse_iso_utc(args.now)
    connection = get_connection(autocommit=False)
    try:
        rows = update_performance_log(connection, as_of=now)
        connection.commit()
        print(f"Upserted performance rows: {rows}")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Performance log update failed: {exc}")
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

