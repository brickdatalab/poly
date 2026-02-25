"""
fast_db.py — process-level boot for backfill_v2.

Import this module FIRST in any script that should use psycopg2 persistent
connections instead of psql subprocess per query.

Sets DB_QUERY_DRIVER=psycopg2 in the running process environment.
Does NOT modify engine.py. Does NOT affect any other running process.
"""
from __future__ import annotations

import os
import sys
from pathlib import Path

# Must be set before engine.py executes any _db_query_driver() calls.
# engine._db_query_driver() reads os.environ at call time, so this is enough.
os.environ["DB_QUERY_DRIVER"] = "psycopg2"
os.environ.setdefault("DB_POOL_MAX_CONN", "32")  # pool for up to 16 thread workers
os.environ.setdefault("DB_FAIL_OPEN", "0")        # hard-fail on DB errors in backfill

# Ensure engine.py is importable from the scripts/ parent directory
_SCRIPTS_DIR = Path(__file__).resolve().parents[1]
if str(_SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(_SCRIPTS_DIR))

from engine import build_db_url, load_env  # noqa: E402


def get_db_url() -> str:
    """Return the Supabase DB URL built from .env (transaction pooler, port 6543)."""
    project_root = Path(__file__).resolve().parents[3]
    env = load_env(project_root)
    return build_db_url(env)


def verify_psycopg2(db_url: str | None = None) -> None:
    """
    Verify psycopg2 can open a real connection and run a query.
    Raises on failure — call at startup to fail fast rather than silently
    falling back to psql subprocess.
    """
    import psycopg2
    url = db_url or get_db_url()
    conn = psycopg2.connect(url, connect_timeout=5)
    conn.autocommit = True
    with conn.cursor() as cur:
        cur.execute("SELECT 1")
        result = cur.fetchone()
        assert result is not None and result[0] == 1, "Unexpected result from psycopg2 test query"
    conn.close()
