from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any


ROOT = Path("/Users/vitolo/Desktop/projects/poly")
DOTENV = ROOT / ".env"


def load_dotenv(dotenv_path: Path = DOTENV) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        k = k.strip()
        v = v.strip().strip("'").strip('"')
        os.environ.setdefault(k, v)


def require_env(name: str) -> str:
    v = os.environ.get(name)
    if not v:
        raise RuntimeError(f"Missing required env var: {name}")
    return v


def _project_ref_from_supabase_url(supabase_url: str) -> str:
    # Expected: https://<project-ref>.supabase.co
    s = supabase_url.strip()
    s = s.removeprefix("https://").removeprefix("http://")
    host = s.split("/", 1)[0]
    project_ref = host.split(".", 1)[0]
    if not project_ref or project_ref == "localhost":
        raise RuntimeError(f"Could not parse Supabase project ref from SUPABASE_URL={supabase_url!r}")
    return project_ref


def build_db_url() -> str:
    # Prefer an explicit DB url if present (without password embedded).
    db_url = os.environ.get("SUPABASE_DB_URL")
    if db_url:
        return db_url

    supabase_url = require_env("SUPABASE_URL")
    project_ref = _project_ref_from_supabase_url(supabase_url)

    # Supabase Postgres endpoint.
    # We intentionally avoid embedding the password; we pass it via PGPASSWORD.
    host = f"db.{project_ref}.supabase.co"
    user = os.environ.get("SUPABASE_DB_USER", "postgres")
    dbname = os.environ.get("SUPABASE_DB_NAME", "postgres")
    port = os.environ.get("SUPABASE_DB_PORT", "5432")
    return f"postgresql://{user}@{host}:{port}/{dbname}"


@dataclass(frozen=True)
class PsqlSettings:
    statement_timeout_s: int = 600
    work_mem_mb: int = 256
    max_parallel_workers_per_gather: int = 4


def psql_json(
    *,
    sql: str,
    settings: PsqlSettings,
    timeout_s: int | None = None,
) -> Any:
    load_dotenv(DOTENV)
    db_url = build_db_url()
    db_password = require_env("SUPABASE_DB_PASSWORD")

    # Tune per session to leverage Supabase CPU/memory and keep the analysis fast.
    # Use session-level SET (not SET LOCAL) since each psql invocation is its own session.
    prefix = (
        f"set statement_timeout = '{settings.statement_timeout_s}s';\n"
        f"set work_mem = '{settings.work_mem_mb}MB';\n"
        f"set max_parallel_workers_per_gather = {settings.max_parallel_workers_per_gather};\n"
        "set jit = on;\n"
    )
    full_sql = prefix + "\n" + sql.strip() + "\n"

    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")

    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", full_sql]
    ts = timeout_s if timeout_s is not None else max(settings.statement_timeout_s + 30, 90)
    try:
        out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=ts)
    except subprocess.CalledProcessError as e:
        msg = e.output.decode("utf-8", errors="replace")
        # Do not chain the CalledProcessError: it contains the full command,
        # which may include secrets if SUPABASE_DB_URL embeds a password.
        raise RuntimeError(msg)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"psql timed out after {ts}s") from e

    s = out.decode("utf-8", errors="replace").strip()
    if not s:
        return None
    try:
        return json.loads(s)
    except json.JSONDecodeError as e:
        # Keep output for debugging; never include secrets (psql shouldn't echo them).
        raise RuntimeError(f"Expected JSON from psql, got:\n{s[:4000]}") from e


def psql_text(
    *,
    sql: str,
    settings: PsqlSettings,
    timeout_s: int | None = None,
) -> str:
    load_dotenv(DOTENV)
    db_url = build_db_url()
    db_password = require_env("SUPABASE_DB_PASSWORD")

    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    prefix = (
        f"set statement_timeout = '{settings.statement_timeout_s}s';\n"
        f"set work_mem = '{settings.work_mem_mb}MB';\n"
        f"set max_parallel_workers_per_gather = {settings.max_parallel_workers_per_gather};\n"
        "set jit = on;\n"
    )
    full_sql = prefix + "\n" + sql.strip() + "\n"
    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", full_sql]
    ts = timeout_s if timeout_s is not None else max(settings.statement_timeout_s + 30, 90)
    try:
        out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=ts)
    except subprocess.CalledProcessError as e:
        msg = e.output.decode("utf-8", errors="replace")
        raise RuntimeError(msg)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"psql timed out after {ts}s") from e
    return out.decode("utf-8", errors="replace").strip()
