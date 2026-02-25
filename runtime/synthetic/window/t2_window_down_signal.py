#!/usr/bin/env python3
from __future__ import annotations

import json
import os
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

PAIRS: tuple[str, str] = ("ETH-USD", "BTC-USD")

DOWN_THRESHOLDS: dict[str, list[tuple[float, float]]] = {
    "ETH-USD": [
        (0.25, -0.0639929141611394),
        (0.5, -0.1319448140475830),
        (0.75, -0.1998967139340260),
        (1.0, -0.2678486138204690),
        (1.5, -0.4037524135933560),
        (2.0, -0.5396562133662420),
        (3.0, -0.8114638129120160),
        (4.0, -1.0832714124577900),
    ],
    "BTC-USD": [
        (0.25, -0.0507027516930629),
        (0.5, -0.1047732397575640),
        (0.75, -0.1588437278220660),
        (1.0, -0.2129142158865670),
        (1.5, -0.3210551920155700),
        (2.0, -0.4291961681445730),
        (3.0, -0.6454781204025780),
        (4.0, -0.8617600726605840),
    ],
}

MIN_SIGMA: dict[str, float] = {
    "ETH-USD": 0.25,
    "BTC-USD": 0.75,
}


def floor_to_quarter_hour(dt: datetime) -> datetime:
    if dt.tzinfo is None:
        raise ValueError("dt must be timezone-aware")
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def quote(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def load_env(project_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env_file = project_root / ".env"
    if env_file.exists():
        for line in env_file.read_text().splitlines():
            s = line.strip()
            if not s or s.startswith("#") or "=" not in s:
                continue
            k, v = s.split("=", 1)
            env[k.strip()] = v.strip().strip('"').strip("'")
    return env


def normalize_pooler_url(db_url: str, env: dict[str, str]) -> str:
    pool_mode = (env.get("SUPABASE_POOL_MODE") or "transaction").strip().lower()
    if pool_mode == "session":
        return db_url
    pool_port = (env.get("SUPABASE_POOLER_PORT") or "6543").strip()
    if "pooler.supabase.com:5432" in db_url and pool_port.isdigit():
        return db_url.replace("pooler.supabase.com:5432", f"pooler.supabase.com:{pool_port}", 1)
    return db_url


def build_db_url(env: dict[str, str]) -> str:
    direct = (env.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return normalize_pooler_url(direct, env)
    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    password = (env.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit("Missing DB config: set SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD")
    host = supabase_url.replace("https://", "").replace("http://", "").split("/")[0]
    ref = host.split(".")[0]
    built = f"postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres"
    return normalize_pooler_url(built, env)


def psql_json(db_url: str, sql: str) -> list[dict[str, Any]]:
    wrapped = f"select coalesce(json_agg(t), '[]'::json)::text from ({sql.strip().rstrip(';')}) t"
    env = dict(os.environ)
    env.setdefault("PGCONNECT_TIMEOUT", "5")
    env.setdefault("PGOPTIONS", "-c statement_timeout=8000")
    cmd = ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-t", "-c", wrapped]
    attempts = 3
    fail_open = (os.environ.get("DB_FAIL_OPEN") or "1").strip().lower() not in {"0", "false", "no", "off"}
    for attempt in range(1, attempts + 1):
        proc = subprocess.run(cmd, text=True, env=env, capture_output=True)
        if proc.returncode == 0:
            out = proc.stdout.strip()
            if not out:
                return []
            return json.loads(out)
        err = (proc.stderr or "")
        retryable = ("Max client connections reached" in err) or ("MaxClientsInSessionMode" in err)
        if retryable and attempt < attempts:
            time.sleep(0.15 * attempt)
            continue
        if fail_open:
            return []
        raise subprocess.CalledProcessError(proc.returncode, cmd, output=proc.stdout, stderr=proc.stderr)
    return []


def fetch_window_pct_diffs(db_url: str, bucket: datetime) -> dict[str, float | None]:
    bucket_iso = iso_z(bucket)
    sql = f"""
with pairs(pair) as (
  values ({quote(PAIRS[0])}), ({quote(PAIRS[1])})
),
open_rows as (
  select pair, open::float8 as open_px
  from indicators.ohlcv_1m
  where bucket_time = {quote(bucket_iso)}::timestamptz - interval '3 minutes'
    and pair in ({quote(PAIRS[0])}, {quote(PAIRS[1])})
),
close_rows as (
  select pair, close::float8 as close_px
  from indicators.ohlcv_1m
  where bucket_time = {quote(bucket_iso)}::timestamptz + interval '1 minute'
    and pair in ({quote(PAIRS[0])}, {quote(PAIRS[1])})
)
select
  p.pair,
  case
    when o.open_px is null or c.close_px is null then null::float8
    else ((c.close_px - o.open_px) / nullif(o.open_px, 0.0)) * 100.0
  end as pct_diff
from pairs p
left join open_rows o on o.pair = p.pair
left join close_rows c on c.pair = p.pair
order by p.pair
"""
    rows = psql_json(db_url, sql)
    result: dict[str, float | None] = {pair: None for pair in PAIRS}
    for row in rows:
        pair = row.get("pair")
        if pair not in result:
            continue
        pct = row.get("pct_diff")
        result[pair] = float(pct) if pct is not None else None
    return result


def best_down_sigma(pair: str, pct_diff: float | None) -> float | None:
    if pct_diff is None:
        return None
    min_sigma = MIN_SIGMA[pair]
    best: float | None = None
    for sigma, threshold in DOWN_THRESHOLDS[pair]:
        if sigma < min_sigma:
            continue
        if pct_diff < threshold:
            best = sigma
    return best


def render_lines(values: dict[str, float | None]) -> list[str]:
    lines: list[str] = []
    for pair in PAIRS:
        sigma = values.get(pair)
        if sigma is None:
            lines.append(f"{pair}: none")
        else:
            lines.append(f"{pair}: +{sigma:.2f}σ")
    return lines


def main() -> int:
    now = datetime.now(timezone.utc)
    bucket = floor_to_quarter_hour(now)
    project_root = Path(__file__).resolve().parents[3]
    env = load_env(project_root)
    db_url = build_db_url(env)

    pct_diffs = fetch_window_pct_diffs(db_url, bucket)
    sigmas = {pair: best_down_sigma(pair, pct_diffs.get(pair)) for pair in PAIRS}
    for line in render_lines(sigmas):
        print(line)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
