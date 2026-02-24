from __future__ import annotations

import argparse
import sys

from alpha_v4.db import execute, fetch_one, get_connection
from alpha_v4.schema import generate_init_sql


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Apply alpha_v4 schema migrations.")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Print SQL statements without executing.",
    )
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    connection = get_connection(autocommit=False)
    try:
        execute(connection, "CREATE SCHEMA IF NOT EXISTS alpha_v4")
        execute(
            connection,
            """
            CREATE TABLE IF NOT EXISTS alpha_v4.schema_migrations (
                id text PRIMARY KEY,
                applied_at timestamptz NOT NULL DEFAULT now()
            )
            """,
        )
        existing = fetch_one(
            connection,
            "SELECT id, applied_at FROM alpha_v4.schema_migrations WHERE id = '0001_init'",
        )
        if existing:
            print("Migration 0001_init already applied.")
            connection.commit()
            return 0

        statements = generate_init_sql(connection)
        if args.dry_run:
            print("-- DRY RUN: migration statements --")
            for statement in statements:
                print(statement.strip() + ";")
            connection.rollback()
            return 0

        for statement in statements:
            execute(connection, statement)

        connection.commit()
        print("Applied migration 0001_init successfully.")
        return 0
    except Exception as exc:
        connection.rollback()
        print(f"Migration failed: {exc}", file=sys.stderr)
        return 1
    finally:
        connection.close()


if __name__ == "__main__":
    raise SystemExit(main())

