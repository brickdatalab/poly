#!/usr/bin/env python3
"""Verify PostgREST exposed schema config contains required schemas.

This is a drift guardrail for `pgrst.db_schemas` on the `authenticator` role.
It fails non-zero when required schemas are missing.
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
from pathlib import Path


def load_env(root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env_file = root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def build_db_url(env: dict[str, str]) -> str:
    direct = (env.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return direct
    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    password = (env.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit("Missing DB config: set SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD")
    host = supabase_url.replace("https://", "").replace("http://", "").split("/")[0]
    ref = host.split(".")[0]
    return f"postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres"


def psql_scalar(db_url: str, sql: str) -> str:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-t", "-A", "-c", sql.strip().rstrip(";")],
        text=True,
    )
    return out.strip()


def parse_schemas(raw: str) -> list[str]:
    if not raw:
        return []
    return [x.strip() for x in raw.split(",") if x.strip()]


def main() -> int:
    ap = argparse.ArgumentParser(description="Check required schemas are present in authenticator pgrst.db_schemas")
    ap.add_argument(
        "--required",
        default=os.environ.get("REQUIRED_PGRST_SCHEMAS", "public,indicators"),
        help="Comma-separated required schemas (default: public,indicators)",
    )
    args = ap.parse_args()

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    raw = psql_scalar(
        db_url,
        """
        select coalesce(
          (
            select substring(conf from '^pgrst\\.db_schemas=(.*)$')
            from unnest(coalesce(r.rolconfig, array[]::text[])) conf
            where conf like 'pgrst.db_schemas=%'
            limit 1
          ),
          ''
        )
        from pg_roles r
        where r.rolname = 'authenticator'
        """,
    )
    current = parse_schemas(raw)
    required = [x.strip() for x in args.required.split(",") if x.strip()]
    current_set = set(current)
    missing = [s for s in required if s not in current_set]

    report = {
        "ok": not missing,
        "required": required,
        "current": current,
        "missing": missing,
    }
    print(json.dumps(report, indent=2))
    return 0 if not missing else 1


if __name__ == "__main__":
    raise SystemExit(main())
