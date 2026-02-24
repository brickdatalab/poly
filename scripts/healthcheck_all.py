#!/usr/bin/env python3
"""
All-in-one pipeline healthcheck for poly.

What this checks (read-only):
1) Ingestion liveness
   - public.websocket_heartbeat (crypto-streamer)
   - public.raw_trades (executed_at freshness + activity counts)
   - indicators.ohlcv_1m (freshness + missing-minute gaps)
2) Downstream candle integrity
   - indicators.ohlcv_{5m,10m,15m,30m,45m,1h,2h,6h,12h}
     - alignment: bucket_time modulo timeframe seconds
     - continuity: lag(bucket_time) step checks in a bounded window
3) Indicators pipeline health
   - indicators.indicator_configs (active config counts by timeframe)
   - indicators.indicator_values completeness for the latest completed bucket per timeframe
   - indicators.job_queue backlog + failures
   - indicators.computation_log errors in the last N hours
   - indicators.fn_health_check() (existing DB-level smoke test)
4) Market context / order book (streamer outputs)
   - public.market_context (timestamp freshness + activity counts)
   - public.order_book_snapshots (captured_at freshness + activity counts)
5) Optional PostgREST availability check (SUPABASE_URL + SUPABASE_SERVICE_KEY)

Outputs:
- A human-readable summary printed to stdout
- A JSON report written to scripts/output/healthcheck/healthcheck_<UTC>.json

Connection:
- Uses SUPABASE_DB_URL + SUPABASE_DB_PASSWORD from .env (or environment).
  We pass password via PGPASSWORD to avoid embedding it in the connection string.
"""

from __future__ import annotations

import argparse
import dataclasses
import datetime as dt
import json
import os
import subprocess
import sys
import textwrap
import urllib.request
from pathlib import Path
from typing import Any, Final, Iterable


PAIR_ALLOWLIST: Final[tuple[str, ...]] = ("BTC-USD", "ETH-USD", "SOL-USD")


@dataclasses.dataclass(frozen=True)
class CheckResult:
    name: str
    status: str  # PASS | WARN | FAIL
    details: dict[str, Any]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def load_dotenv(dotenv_path: Path) -> None:
    """
    Load a minimal .env into process env (no shell expansion).
    Existing env vars are not overwritten.
    """
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text().splitlines():
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


def psql_json(db_url: str, db_password: str, sql: str, timeout_s: int = 45) -> Any:
    """
    Execute a SQL statement and return JSON parsed from stdout.

    We force the query to return a single JSON value via `select jsonb_agg(...)`
    in the callsites, so stdout is always valid JSON.
    """
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")

    cmd = [
        "psql",
        "-X",
        db_url,
        "-v",
        "ON_ERROR_STOP=1",
        "-q",
        "-t",
        "-A",
        "-c",
        sql,
    ]
    try:
        out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=timeout_s)
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"psql timed out after {timeout_s}s") from e
    except subprocess.CalledProcessError as e:
        msg = e.output.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"psql failed: {msg}") from e

    s = out.decode("utf-8", errors="replace").strip()
    if not s:
        return None
    return json.loads(s)


def status_from_age(age_s: float, pass_s: float, warn_s: float) -> str:
    if age_s <= pass_s:
        return "PASS"
    if age_s <= warn_s:
        return "WARN"
    return "FAIL"


def http_get_json(url: str, headers: dict[str, str], timeout_s: int = 15) -> Any:
    req = urllib.request.Request(url, headers=headers, method="GET")
    with urllib.request.urlopen(req, timeout=timeout_s) as resp:
        body = resp.read().decode("utf-8", errors="replace")
        if not body:
            return None
        return json.loads(body)


def check_db_connectivity(db_url: str, db_password: str) -> CheckResult:
    q = "select to_jsonb(array_agg(t)) from (select 1 as ok) t;"
    v = psql_json(db_url, db_password, q, timeout_s=20)
    ok = bool(v and v[0].get("ok") == 1)
    return CheckResult(
        name="db_connectivity",
        status="PASS" if ok else "FAIL",
        details={"ok": ok},
    )


def check_heartbeats(db_url: str, db_password: str) -> CheckResult:
    q = """
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select id, service_name, last_heartbeat, status, error_message, updated_at
      from public.websocket_heartbeat
      order by id
    ) t;
    """
    rows = psql_json(db_url, db_password, q)
    now = utc_now()

    # Known current shape: only crypto-streamer is recorded here, but we don't assume that long-term.
    by_service: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        by_service[r["service_name"]] = r

    crypto = by_service.get("crypto-streamer")
    if not crypto:
        return CheckResult(
            name="websocket_heartbeat",
            status="FAIL",
            details={"reason": "missing crypto-streamer row", "rows": rows},
        )

    last = dt.datetime.fromisoformat(str(crypto["last_heartbeat"]).replace("Z", "+00:00"))
    age_s = (now - last).total_seconds()
    hb_status = status_from_age(age_s, pass_s=120, warn_s=300)

    # Non-empty error_message is a strong signal of churn (duplicates, insert errors, etc.)
    err = (crypto.get("error_message") or "").strip()
    status = hb_status
    if err and status == "PASS":
        status = "WARN"

    return CheckResult(
        name="websocket_heartbeat",
        status=status,
        details={
            "services": sorted(by_service.keys()),
            "crypto_streamer": {
                "status": crypto.get("status"),
                "age_seconds": round(age_s, 3),
                "error_message_present": bool(err),
            },
        },
    )


def check_raw_trades_freshness(db_url: str, db_password: str, window_minutes: int) -> CheckResult:
    q = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        pair,
        max(executed_at) as max_executed_at,
        count(*) filter (where executed_at > now() - interval '{window_minutes} minutes') as n_recent
      from public.raw_trades
      where pair = any(array{list(PAIR_ALLOWLIST)}::text[])
      group by pair
      order by pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q)
    now = utc_now()

    worst = "PASS"
    per_pair: dict[str, Any] = {}
    for r in rows or []:
        pair = r["pair"]
        max_ts = dt.datetime.fromisoformat(str(r["max_executed_at"]).replace("Z", "+00:00"))
        age_s = (now - max_ts).total_seconds()
        st = status_from_age(age_s, pass_s=120, warn_s=300)
        n_recent = int(r["n_recent"])
        if n_recent == 0:
            st = "FAIL"
        per_pair[pair] = {"age_seconds": round(age_s, 3), "n_recent": n_recent, "status": st}
        if st == "FAIL":
            worst = "FAIL"
        elif st == "WARN" and worst != "FAIL":
            worst = "WARN"

    # If a pair is missing entirely, fail.
    missing_pairs = [p for p in PAIR_ALLOWLIST if p not in per_pair]
    if missing_pairs:
        worst = "FAIL"

    return CheckResult(
        name="raw_trades_freshness",
        status=worst,
        details={"window_minutes": window_minutes, "missing_pairs": missing_pairs, "pairs": per_pair},
    )


def check_market_context(db_url: str, db_password: str, window_minutes: int) -> CheckResult:
    q = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        pair,
        max(timestamp) as max_timestamp,
        count(*) filter (where timestamp > now() - interval '{window_minutes} minutes') as n_recent
      from public.market_context
      where pair = any(array{list(PAIR_ALLOWLIST)}::text[])
      group by pair
      order by pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q)
    now = utc_now()

    worst = "PASS"
    per_pair: dict[str, Any] = {}
    for r in rows or []:
        pair = r["pair"]
        max_ts = dt.datetime.fromisoformat(str(r["max_timestamp"]).replace("Z", "+00:00"))
        age_s = (now - max_ts).total_seconds()
        st = status_from_age(age_s, pass_s=60, warn_s=300)
        n_recent = int(r["n_recent"])
        if n_recent == 0:
            st = "FAIL"
        per_pair[pair] = {"age_seconds": round(age_s, 3), "n_recent": n_recent, "status": st}
        if st == "FAIL":
            worst = "FAIL"
        elif st == "WARN" and worst != "FAIL":
            worst = "WARN"

    missing_pairs = [p for p in PAIR_ALLOWLIST if p not in per_pair]
    if missing_pairs:
        worst = "FAIL"

    return CheckResult(
        name="market_context_freshness",
        status=worst,
        details={"window_minutes": window_minutes, "missing_pairs": missing_pairs, "pairs": per_pair},
    )


def check_order_book(db_url: str, db_password: str, window_minutes: int) -> CheckResult:
    q = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        pair,
        max(captured_at) as max_captured_at,
        count(*) filter (where captured_at > now() - interval '{window_minutes} minutes') as n_recent
      from public.order_book_snapshots
      where pair = any(array{list(PAIR_ALLOWLIST)}::text[])
      group by pair
      order by pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q)
    now = utc_now()

    worst = "PASS"
    per_pair: dict[str, Any] = {}
    for r in rows or []:
        pair = r["pair"]
        max_ts = dt.datetime.fromisoformat(str(r["max_captured_at"]).replace("Z", "+00:00"))
        age_s = (now - max_ts).total_seconds()
        st = status_from_age(age_s, pass_s=60, warn_s=300)
        n_recent = int(r["n_recent"])
        if n_recent == 0:
            st = "FAIL"
        per_pair[pair] = {"age_seconds": round(age_s, 3), "n_recent": n_recent, "status": st}
        if st == "FAIL":
            worst = "FAIL"
        elif st == "WARN" and worst != "FAIL":
            worst = "WARN"

    missing_pairs = [p for p in PAIR_ALLOWLIST if p not in per_pair]
    if missing_pairs:
        worst = "FAIL"

    return CheckResult(
        name="order_book_freshness",
        status=worst,
        details={"window_minutes": window_minutes, "missing_pairs": missing_pairs, "pairs": per_pair},
    )


def check_ohlcv_1m_freshness(db_url: str, db_password: str) -> CheckResult:
    q = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select pair, max(bucket_time) as max_bucket_time
      from indicators.ohlcv_1m
      where pair = any(array{list(PAIR_ALLOWLIST)}::text[])
      group by pair
      order by pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q)
    now = utc_now()

    worst = "PASS"
    per_pair: dict[str, Any] = {}
    for r in rows or []:
        pair = r["pair"]
        max_ts = dt.datetime.fromisoformat(str(r["max_bucket_time"]).replace("Z", "+00:00"))
        age_s = (now - max_ts).total_seconds()
        # bucket_time is minute start, so "freshness" naturally lags wall clock.
        st = status_from_age(age_s, pass_s=180, warn_s=600)
        per_pair[pair] = {"age_seconds": round(age_s, 3), "status": st}
        if st == "FAIL":
            worst = "FAIL"
        elif st == "WARN" and worst != "FAIL":
            worst = "WARN"

    missing_pairs = [p for p in PAIR_ALLOWLIST if p not in per_pair]
    if missing_pairs:
        worst = "FAIL"

    return CheckResult(
        name="ohlcv_1m_freshness",
        status=worst,
        details={"missing_pairs": missing_pairs, "pairs": per_pair},
    )


def check_ohlcv_1m_gaps(db_url: str, db_password: str, window_hours: int) -> CheckResult:
    # Use generate_series for a bounded anti-join. For 24h, this is tiny.
    q = f"""
    with bounds as (
      select
        date_trunc('minute', now() - interval '{window_hours} hours') as start_ts,
        date_trunc('minute', now()) as end_ts
    ),
    expected as (
      select p.pair, gs as bucket_time
      from (select unnest(array{list(PAIR_ALLOWLIST)}::text[]) as pair) p
      cross join bounds b
      cross join generate_series(b.start_ts, b.end_ts - interval '1 minute', interval '1 minute') gs
    ),
    actual as (
      select pair, bucket_time
      from indicators.ohlcv_1m
      where bucket_time >= (select start_ts from bounds)
        and bucket_time < (select end_ts from bounds)
        and pair = any(array{list(PAIR_ALLOWLIST)}::text[])
    )
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select e.pair, count(*) as missing_minutes
      from expected e
      left join actual a using (pair, bucket_time)
      where a.bucket_time is null
      group by e.pair
      order by e.pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q, timeout_s=60)

    worst = "PASS"
    per_pair: dict[str, Any] = {}
    for r in rows or []:
        m = int(r["missing_minutes"])
        st = "PASS" if m == 0 else "FAIL"
        per_pair[r["pair"]] = {"missing_minutes": m, "status": st}
        if st == "FAIL":
            worst = "FAIL"

    return CheckResult(
        name="ohlcv_1m_gaps",
        status=worst,
        details={"window_hours": window_hours, "pairs": per_pair},
    )


def check_rollups_alignment_and_gaps(db_url: str, db_password: str, window_hours: int) -> CheckResult:
    # We use a single query that unions timeframe-specific checks to reduce roundtrips.
    # Continuity uses lag(bucket_time) != step in a bounded window.
    timeframe_map: list[tuple[str, int]] = [
        ("5m", 300),
        ("10m", 600),
        ("15m", 900),
        ("30m", 1800),
        ("45m", 2700),
        ("1h", 3600),
        ("2h", 7200),
        ("6h", 21600),
        ("12h", 43200),
    ]

    unions: list[str] = []
    for tf, step in timeframe_map:
        table = f"indicators.ohlcv_{tf}"
        unions.append(
            textwrap.dedent(
                f"""
                select
                  '{tf}'::text as timeframe,
                  pair,
                  sum(case when mod(extract(epoch from bucket_time)::bigint, {step}) = 0 then 0 else 1 end)::bigint as misaligned_rows,
                  sum(case when prev_bucket_time is null then 0
                           when bucket_time - prev_bucket_time = interval '1 second' * {step} then 0
                           else 1 end)::bigint as gap_violations
                from (
                  select
                    pair,
                    bucket_time,
                    lag(bucket_time) over (partition by pair order by bucket_time) as prev_bucket_time
                  from {table}
                  where pair = any(array{list(PAIR_ALLOWLIST)}::text[])
                    and bucket_time >= date_trunc('minute', now() - interval '{window_hours} hours')
                    and bucket_time < date_trunc('minute', now())
                ) s
                group by pair
                """
            ).strip()
        )

    union_sql = "\n      union all\n      ".join(unions)
    q = f"""
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      {union_sql}
      order by timeframe, pair
    ) t;
    """
    rows = psql_json(db_url, db_password, q, timeout_s=60)

    worst = "PASS"
    by_tf: dict[str, dict[str, Any]] = {}
    for r in rows or []:
        tf = r["timeframe"]
        pair = r["pair"]
        mis = int(r["misaligned_rows"])
        gaps = int(r["gap_violations"])
        st = "PASS" if (mis == 0 and gaps == 0) else "FAIL"
        by_tf.setdefault(tf, {})[pair] = {"misaligned_rows": mis, "gap_violations": gaps, "status": st}
        if st == "FAIL":
            worst = "FAIL"

    return CheckResult(
        name="ohlcv_rollups_alignment_and_gaps",
        status=worst,
        details={"window_hours": window_hours, "timeframes": by_tf},
    )


def check_indicator_pipeline(db_url: str, db_password: str) -> CheckResult:
    # Active configs by timeframe
    q_cfg = """
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select timeframe, count(*) as active_configs
      from indicators.indicator_configs
      where is_active
      group by timeframe
      order by timeframe
    ) t;
    """
    cfg_rows = psql_json(db_url, db_password, q_cfg)
    expected_by_tf = {r["timeframe"]: int(r["active_configs"]) for r in (cfg_rows or [])}

    # Latest COMPLETED bucket per timeframe (use ohlcv tables as the clock)
    # Then verify indicator_values has exactly N rows for that bucket/pair/timeframe.
    # We consider "completed" as bucket_time <= now() - step for that timeframe.
    tf_steps = {"1m": 60, "5m": 300, "15m": 900, "30m": 1800, "1h": 3600, "2h": 7200}
    unions: list[str] = []
    for tf, step in tf_steps.items():
        table = f"indicators.ohlcv_{tf}"
        unions.append(
            textwrap.dedent(
                f"""
                select
                  '{tf}'::text as timeframe,
                  pair,
                  (
                    select max(bucket_time)
                    from {table}
                    where pair = p.pair
                      and bucket_time <= date_trunc('minute', now()) - interval '1 second' * {step}
                  ) as completed_bucket_time
                from (select unnest(array{list(PAIR_ALLOWLIST)}::text[]) as pair) p
                """
            ).strip()
        )

    union_completed_sql = "\n      union all\n      ".join(unions)
    q_completed = f"""
    with completed as (
      {union_completed_sql}
    ),
    counts as (
      select
        c.timeframe,
        c.pair,
        c.completed_bucket_time,
        count(ic.config_id)::bigint as indicator_rows
      from completed c
      left join indicators.indicator_values iv
        on iv.pair = c.pair
       and iv.bucket_time = c.completed_bucket_time
      left join indicators.indicator_configs ic
        on ic.config_id = iv.config_id
       and ic.is_active
       and ic.timeframe = c.timeframe
      group by 1,2,3
    )
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select timeframe, pair, completed_bucket_time, indicator_rows
      from counts
      order by timeframe, pair
    ) t;
    """
    counts_rows = psql_json(db_url, db_password, q_completed, timeout_s=90)

    # job_queue + computation_log errors
    q_jobs = """
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select status, count(*)::bigint as n
      from indicators.job_queue
      group by status
      order by status
    ) t;
    """
    job_rows = psql_json(db_url, db_password, q_jobs)

    q_log = """
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select status, count(*)::bigint as n
      from indicators.computation_log
      where created_at > now() - interval '6 hours'
      group by status
      order by status
    ) t;
    """
    log_rows = psql_json(db_url, db_password, q_log)

    q_fn = "select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb)) from (select * from indicators.fn_health_check()) t;"
    fn_rows = psql_json(db_url, db_password, q_fn)

    worst = "PASS"
    completeness: list[dict[str, Any]] = []
    for r in counts_rows or []:
        tf = r["timeframe"]
        pair = r["pair"]
        completed_bucket_time = r["completed_bucket_time"]
        actual = int(r["indicator_rows"])
        expected = expected_by_tf.get(tf)
        # Some timeframes may have 0 configs (not expected, but keep robust).
        ok = expected is not None and completed_bucket_time is not None and actual == expected
        st = "PASS" if ok else "FAIL"
        if st == "FAIL":
            worst = "FAIL"
        completeness.append(
            {
                "timeframe": tf,
                "pair": pair,
                "completed_bucket_time": completed_bucket_time,
                "expected_rows": expected,
                "actual_rows": actual,
                "status": st,
            }
        )

    # job failures or computation failures are WARN (pipeline still live but needs attention).
    job_by_status = {r["status"]: int(r["n"]) for r in (job_rows or [])}
    log_by_status = {r["status"]: int(r["n"]) for r in (log_rows or [])}
    failed_jobs = job_by_status.get("failed", 0)
    if failed_jobs > 0 and worst == "PASS":
        worst = "WARN"

    # fn_health_check is a helpful extra signal; if it reports any non-green, WARN/FAIL.
    fn_bad = [r for r in (fn_rows or []) if str(r.get("health")) not in ("✅",)]
    if fn_bad:
        worst = "WARN" if worst == "PASS" else worst

    return CheckResult(
        name="indicator_pipeline",
        status=worst,
        details={
            "active_configs_by_timeframe": expected_by_tf,
            "completeness_latest_completed": completeness,
            "job_queue_by_status": job_by_status,
            "computation_log_last_6h": log_by_status,
            "fn_health_check": fn_rows,
        },
    )


def check_postgrest(supabase_url: str, service_key: str) -> CheckResult:
    # Lightweight sanity call: read 1 row from websocket_heartbeat.
    url = supabase_url.rstrip("/") + "/rest/v1/websocket_heartbeat?select=id&limit=1"
    headers = {"apikey": service_key, "authorization": f"Bearer {service_key}"}
    try:
        data = http_get_json(url, headers=headers, timeout_s=10)
        ok = isinstance(data, list)
        return CheckResult(
            name="postgrest_http",
            status="PASS" if ok else "WARN",
            details={"url": "/rest/v1/websocket_heartbeat?select=id&limit=1", "ok": ok},
        )
    except Exception as e:  # noqa: BLE001 - best-effort check
        return CheckResult(
            name="postgrest_http",
            status="WARN",
            details={"url": "/rest/v1/websocket_heartbeat?select=id&limit=1", "error": str(e)},
        )


def summarize(results: Iterable[CheckResult]) -> str:
    lines: list[str] = []
    worst = "PASS"
    for r in results:
        if r.status == "FAIL":
            worst = "FAIL"
        elif r.status == "WARN" and worst != "FAIL":
            worst = "WARN"
        lines.append(f"{r.status:<4} {r.name}")
        if r.status != "PASS":
            # Keep this short; the full details are in the JSON report.
            if r.name == "websocket_heartbeat":
                cs = r.details.get("crypto_streamer", {})
                lines.append(
                    f"     crypto-streamer age_s={cs.get('age_seconds')} "
                    f"status={cs.get('status')} error={cs.get('error_message_present')}"
                )
            elif r.name == "indicator_pipeline":
                jq = r.details.get("job_queue_by_status", {})
                lines.append(f"     job_queue failed={jq.get('failed', 0)} running={jq.get('running', 0)}")
            elif r.name == "postgrest_http":
                lines.append(f"     {r.details}")
    lines.append("")
    lines.append(f"OVERALL: {worst}")
    return "\n".join(lines)


def main() -> int:
    parser = argparse.ArgumentParser(description="poly healthcheck (read-only)")
    parser.add_argument("--window-hours", type=int, default=24, help="window for candle gap checks")
    parser.add_argument("--recent-minutes", type=int, default=5, help="activity window for recent counts")
    parser.add_argument("--no-http", action="store_true", help="skip PostgREST HTTP check")
    args = parser.parse_args()

    load_dotenv(Path("/Users/vitolo/Desktop/projects/poly/.env"))

    db_url = require_env("SUPABASE_DB_URL")
    db_password = require_env("SUPABASE_DB_PASSWORD")

    results: list[CheckResult] = []
    results.append(check_db_connectivity(db_url, db_password))
    results.append(check_heartbeats(db_url, db_password))
    results.append(check_raw_trades_freshness(db_url, db_password, window_minutes=args.recent_minutes))
    results.append(check_market_context(db_url, db_password, window_minutes=args.recent_minutes))
    results.append(check_order_book(db_url, db_password, window_minutes=args.recent_minutes))
    results.append(check_ohlcv_1m_freshness(db_url, db_password))
    results.append(check_ohlcv_1m_gaps(db_url, db_password, window_hours=args.window_hours))
    results.append(check_rollups_alignment_and_gaps(db_url, db_password, window_hours=args.window_hours))
    results.append(check_indicator_pipeline(db_url, db_password))

    if not args.no_http:
        supabase_url = os.environ.get("SUPABASE_URL")
        service_key = os.environ.get("SUPABASE_SERVICE_KEY") or os.environ.get("SUPBASE_SERVICE_KEY")
        if supabase_url and service_key:
            results.append(check_postgrest(supabase_url, service_key))
        else:
            results.append(
                CheckResult(
                    name="postgrest_http",
                    status="WARN",
                    details={"reason": "SUPABASE_URL or SUPABASE_SERVICE_KEY missing; skipped"},
                )
            )

    # Write report
    ts = utc_now().strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path("/Users/vitolo/Desktop/projects/poly/scripts/output/healthcheck")
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"healthcheck_{ts}.json"

    report = {
        "generated_at_utc": ts,
        "args": vars(args),
        "results": [dataclasses.asdict(r) for r in results],
    }
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n")

    print(summarize(results))
    print("")
    print(f"Report: {out_path}")

    # Exit non-zero on FAIL
    overall = "PASS"
    for r in results:
        if r.status == "FAIL":
            overall = "FAIL"
            break
        if r.status == "WARN":
            overall = "WARN"
    if overall == "FAIL":
        return 2
    if overall == "WARN":
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
