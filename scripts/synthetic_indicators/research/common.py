from __future__ import annotations

import csv
import os
import subprocess
from pathlib import Path
from typing import Any


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


def db_url_from_env(root: Path) -> str:
    env = load_env(root)
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_csv(db_url: str, sql: str) -> list[dict[str, str]]:
    out = subprocess.check_output(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-A",
            "-F",
            ",",
            "--csv",
            "-c",
            sql,
        ],
        text=True,
    )
    return list(csv.DictReader(out.splitlines()))


def psql_scalar(db_url: str, sql: str) -> str:
    q = sql.strip().rstrip(";")
    out = subprocess.check_output(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-t",
            "-A",
            "-c",
            q,
        ],
        text=True,
    )
    return out.strip()


def psql_exec(db_url: str, sql: str) -> None:
    subprocess.check_call(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-c",
            sql,
        ]
    )


def to_sql_array(values: list[str]) -> str:
    joined = ", ".join(f"'{v}'" for v in values)
    return f"array[{joined}]"


def pct(val: float) -> str:
    return f"{val * 100:.4f}%"


def ensure_dir(path: Path) -> Path:
    path.mkdir(parents=True, exist_ok=True)
    return path
