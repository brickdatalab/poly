from __future__ import annotations

import datetime as dt
import json
import os
import re
import subprocess
from pathlib import Path
from typing import Any, Final


DEFAULT_PAIRS: Final[tuple[str, ...]] = ("BTC-USD", "ETH-USD", "SOL-USD")
PAIR_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9._:-]+$")
QUALIFIED_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_.]*$")
COLUMN_NAME_PATTERN: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")


def load_dotenv(dotenv_path: Path) -> None:
    if not dotenv_path.exists():
        return
    for raw in dotenv_path.read_text().splitlines():
        line = raw.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        k, v = line.split("=", 1)
        os.environ.setdefault(k.strip(), v.strip().strip("'").strip('"'))


def require_env(name: str) -> str:
    value = os.environ.get(name)
    if not value:
        raise RuntimeError(f"Missing required env var: {name}")
    return value


def parse_pairs(pairs_csv: str) -> tuple[str, ...]:
    parsed = tuple(p.strip() for p in pairs_csv.split(",") if p.strip())
    if not parsed:
        raise ValueError("No pairs provided")
    bad = [p for p in parsed if not PAIR_PATTERN.match(p)]
    if bad:
        raise ValueError(f"Invalid pair value(s): {bad}")
    return parsed


def psql_json(db_url: str, db_password: str | None, sql: str, timeout_s: int = 90) -> Any:
    env = os.environ.copy()
    if db_password:
        env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    cmd = ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql]
    try:
        out = subprocess.check_output(cmd, env=env, stderr=subprocess.STDOUT, timeout=timeout_s)
    except subprocess.TimeoutExpired as exc:
        raise RuntimeError(f"psql timed out after {timeout_s}s") from exc
    except subprocess.CalledProcessError as exc:
        msg = exc.output.decode("utf-8", errors="replace").strip()
        raise RuntimeError(f"psql failed: {msg}") from exc

    text = out.decode("utf-8", errors="replace").strip()
    if not text:
        return None
    return json.loads(text)


def quote_literal(value: str) -> str:
    return "'" + value.replace("'", "''") + "'"


def _validate_qualified_name(name: str) -> None:
    if not QUALIFIED_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid qualified table/source name: {name}")


def _validate_column_name(name: str) -> None:
    if not COLUMN_NAME_PATTERN.match(name):
        raise ValueError(f"Invalid column name: {name}")


def _pair_literal_csv(pairs: tuple[str, ...]) -> str:
    return ", ".join(quote_literal(p) for p in pairs)


def traffic_light_from_status(status: str) -> str:
    normalized = status.upper()
    if normalized == "PASS":
        return "GREEN"
    if normalized == "WARN":
        return "YELLOW"
    return "RED"


def summarize_status(rows: list[dict[str, Any]]) -> dict[str, Any]:
    total = len(rows)
    failed = sum(1 for row in rows if str(row.get("status")).upper() == "FAIL")
    warned = sum(1 for row in rows if str(row.get("status")).upper() == "WARN")
    passed = total - failed - warned
    if failed > 0:
        overall = "FAIL"
    elif warned > 0:
        overall = "WARN"
    else:
        overall = "PASS"

    return {
        "total_checks": total,
        "passed_checks": passed,
        "warn_checks": warned,
        "failed_checks": failed,
        "all_pass": failed == 0 and warned == 0,
        "overall_status": overall,
        "traffic_light": traffic_light_from_status(overall),
    }


def build_realtime_source_health_sql(
    *,
    source: str,
    table: str,
    ts_column: str,
    pairs: tuple[str, ...],
    lookback_minutes: int,
    fallback_max_lag_seconds: int = 120,
) -> str:
    if lookback_minutes <= 0:
        raise ValueError("lookback_minutes must be > 0")
    if fallback_max_lag_seconds <= 0:
        raise ValueError("fallback_max_lag_seconds must be > 0")
    _validate_qualified_name(source)
    _validate_qualified_name(table)
    _validate_column_name(ts_column)

    pair_literals = _pair_literal_csv(pairs)
    source_lit = quote_literal(source)

    return f"""
    with cfg as (
      select
        coalesce(
          (
            select extract(epoch from max_lag)::int
            from ops.pipeline_slo_config
            where source = {source_lit} and enabled
            limit 1
          ),
          {fallback_max_lag_seconds}
        )::int as max_lag_seconds,
        coalesce(
          (
            select max_missing
            from ops.pipeline_slo_config
            where source = {source_lit} and enabled
            limit 1
          ),
          0
        )::int as max_missing_minutes
    ),
    pairs as (
      select unnest(array[{pair_literals}]::text[]) as pair
    ),
    bounds as (
      select
        (date_trunc('minute', now() at time zone 'UTC') - interval '{lookback_minutes} minutes')::timestamptz as start_minute,
        date_trunc('minute', now() at time zone 'UTC')::timestamptz as end_minute
    ),
    latest as (
      select
        pair,
        max({ts_column}) as latest_ts
      from {table}
      where pair = any(array[{pair_literals}]::text[])
      group by pair
    ),
    activity as (
      select
        pair,
        count(*)::bigint as rows_in_lookback,
        count(*) filter (where {ts_column} >= now() - interval '5 minutes')::bigint as rows_last_5m
      from {table}, bounds
      where pair = any(array[{pair_literals}]::text[])
        and {ts_column} >= bounds.start_minute
        and {ts_column} < bounds.end_minute + interval '1 minute'
      group by pair
    ),
    minute_counts as (
      select
        pair,
        date_trunc('minute', {ts_column})::timestamptz as minute_ts,
        count(*)::bigint as rows_this_minute
      from {table}, bounds
      where pair = any(array[{pair_literals}]::text[])
        and {ts_column} >= bounds.start_minute
        and {ts_column} < bounds.end_minute + interval '1 minute'
      group by pair, date_trunc('minute', {ts_column})
    ),
    expected_minutes as (
      select
        p.pair,
        gs::timestamptz as minute_ts
      from pairs p
      cross join bounds b
      cross join generate_series(
        b.start_minute,
        b.end_minute - interval '1 minute',
        interval '1 minute'
      ) gs
    ),
    missing as (
      select
        e.pair,
        count(*)::bigint as missing_minutes,
        min(e.minute_ts) as first_missing_minute,
        max(e.minute_ts) as last_missing_minute
      from expected_minutes e
      left join minute_counts m
        on m.pair = e.pair
       and m.minute_ts = e.minute_ts
      where m.minute_ts is null
      group by e.pair
    ),
    minute_profile as (
      select
        pair,
        avg(rows_this_minute)::double precision as rows_per_minute,
        percentile_cont(0.5) within group (order by rows_this_minute)::double precision as median_rows_per_minute,
        min(rows_this_minute)::bigint as min_rows_per_minute,
        max(rows_this_minute)::bigint as peak_rows_per_minute
      from minute_counts
      group by pair
    )
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        {source_lit}::text as source,
        p.pair,
        l.latest_ts,
        case
          when l.latest_ts is null then null
          else extract(epoch from (now() - l.latest_ts))::bigint
        end as lag_seconds,
        cfg.max_lag_seconds,
        coalesce(a.rows_in_lookback, 0)::bigint as rows_in_lookback,
        coalesce(a.rows_last_5m, 0)::bigint as rows_last_5m,
        coalesce(mp.rows_per_minute, 0)::double precision as rows_per_minute,
        coalesce(mp.median_rows_per_minute, 0)::double precision as median_rows_per_minute,
        coalesce(mp.min_rows_per_minute, 0)::bigint as min_rows_per_minute,
        coalesce(mp.peak_rows_per_minute, 0)::bigint as peak_rows_per_minute,
        coalesce(m.missing_minutes, 0)::bigint as missing_minutes,
        m.first_missing_minute,
        m.last_missing_minute,
        cfg.max_missing_minutes,
        case
          when l.latest_ts is null then 'FAIL'
          when extract(epoch from (now() - l.latest_ts))::bigint > cfg.max_lag_seconds then 'FAIL'
          when coalesce(a.rows_in_lookback, 0) = 0 then 'FAIL'
          when coalesce(m.missing_minutes, 0) > cfg.max_missing_minutes then 'WARN'
          else 'PASS'
        end as status,
        case
          when l.latest_ts is null then 'RED'
          when extract(epoch from (now() - l.latest_ts))::bigint > cfg.max_lag_seconds then 'RED'
          when coalesce(a.rows_in_lookback, 0) = 0 then 'RED'
          when coalesce(m.missing_minutes, 0) > cfg.max_missing_minutes then 'YELLOW'
          else 'GREEN'
        end as traffic_light
      from pairs p
      cross join cfg
      left join latest l using (pair)
      left join activity a using (pair)
      left join minute_profile mp using (pair)
      left join missing m using (pair)
      order by p.pair
    ) t;
    """


def build_open_interest_health_sql(
    *,
    source: str,
    table: str,
    ts_column: str,
    pairs: tuple[str, ...],
    lookback_hours: int,
    step_seconds: int = 900,
    fallback_max_lag_seconds: int = 2700,
) -> str:
    if lookback_hours <= 0:
        raise ValueError("lookback_hours must be > 0")
    if step_seconds <= 0:
        raise ValueError("step_seconds must be > 0")
    if fallback_max_lag_seconds <= 0:
        raise ValueError("fallback_max_lag_seconds must be > 0")
    _validate_qualified_name(source)
    _validate_qualified_name(table)
    _validate_column_name(ts_column)

    pair_literals = _pair_literal_csv(pairs)
    source_lit = quote_literal(source)

    return f"""
    with cfg as (
      select
        coalesce(
          (
            select extract(epoch from max_lag)::int
            from ops.pipeline_slo_config
            where source = {source_lit} and enabled
            limit 1
          ),
          {fallback_max_lag_seconds}
        )::int as max_lag_seconds,
        coalesce(
          (
            select max_missing
            from ops.pipeline_slo_config
            where source = {source_lit} and enabled
            limit 1
          ),
          0
        )::int as max_missing_buckets
    ),
    pairs as (
      select unnest(array[{pair_literals}]::text[]) as pair
    ),
    bounds_raw as (
      select
        (date_trunc('minute', now() at time zone 'UTC') - interval '{lookback_hours} hours')::timestamptz as start_ts,
        date_trunc('minute', now() at time zone 'UTC')::timestamptz as end_ts
    ),
    bounds as (
      select
        to_timestamp(floor(extract(epoch from start_ts) / {step_seconds}) * {step_seconds})::timestamptz as start_aligned,
        to_timestamp(floor(extract(epoch from end_ts) / {step_seconds}) * {step_seconds})::timestamptz as end_aligned
      from bounds_raw
    ),
    latest as (
      select
        pair,
        max({ts_column}) as latest_ts
      from {table}
      where pair = any(array[{pair_literals}]::text[])
      group by pair
    ),
    actual_raw as (
      select
        pair,
        {ts_column} as bucket_time,
        to_timestamp(floor(extract(epoch from {ts_column}) / {step_seconds}) * {step_seconds})::timestamptz as bucket_aligned
      from {table}, bounds
      where pair = any(array[{pair_literals}]::text[])
        and {ts_column} >= bounds.start_aligned - interval '1 second' * {step_seconds}
        and {ts_column} < bounds.end_aligned + interval '1 second' * {step_seconds}
    ),
    actual_window as (
      select
        pair,
        bucket_time,
        bucket_aligned
      from actual_raw, bounds
      where bucket_aligned >= bounds.start_aligned
        and bucket_aligned < bounds.end_aligned
    ),
    actual_distinct as (
      select distinct pair, bucket_aligned as bucket_time
      from actual_window
    ),
    expected as (
      select
        p.pair,
        gs::timestamptz as bucket_time
      from pairs p
      cross join bounds b
      cross join generate_series(
        b.start_aligned,
        b.end_aligned - interval '1 second' * {step_seconds},
        interval '1 second' * {step_seconds}
      ) gs
    ),
    expected_counts as (
      select pair, count(*)::bigint as expected_rows
      from expected
      group by pair
    ),
    actual_counts as (
      select pair, count(*)::bigint as actual_distinct_rows
      from actual_distinct
      group by pair
    ),
    lookback_rows as (
      select pair, count(*)::bigint as rows_in_lookback
      from actual_window
      group by pair
    ),
    missing as (
      select
        e.pair,
        count(*)::bigint as missing_buckets,
        min(e.bucket_time) as first_missing_bucket,
        max(e.bucket_time) as last_missing_bucket
      from expected e
      left join actual_distinct a
        on a.pair = e.pair
       and a.bucket_time = e.bucket_time
      where a.bucket_time is null
      group by e.pair
    ),
    duplicate_stats as (
      select
        pair,
        greatest(count(*) - count(distinct bucket_aligned), 0)::bigint as duplicate_rows
      from actual_window
      group by pair
    ),
    misaligned_stats as (
      select
        pair,
        sum(case when bucket_time = bucket_aligned then 0 else 1 end)::bigint as misaligned_rows
      from actual_window
      group by pair
    ),
    gap_stats as (
      select
        pair,
        sum(
          case
            when prev_bucket_time is null then 0
            when bucket_time - prev_bucket_time = interval '1 second' * {step_seconds} then 0
            else 1
          end
        )::bigint as gap_violations
      from (
        select
          pair,
          bucket_time,
          lag(bucket_time) over (partition by pair order by bucket_time) as prev_bucket_time
        from actual_distinct
      ) s
      group by pair
    )
    select to_jsonb(coalesce(jsonb_agg(t), '[]'::jsonb))
    from (
      select
        {source_lit}::text as source,
        p.pair,
        l.latest_ts,
        case
          when l.latest_ts is null then null
          else extract(epoch from (now() - l.latest_ts))::bigint
        end as lag_seconds,
        cfg.max_lag_seconds,
        {step_seconds}::int as step_seconds,
        coalesce(ec.expected_rows, 0)::bigint as expected_rows,
        coalesce(ac.actual_distinct_rows, 0)::bigint as actual_distinct_rows,
        coalesce(lb.rows_in_lookback, 0)::bigint as rows_in_lookback,
        coalesce(m.missing_buckets, 0)::bigint as missing_buckets,
        m.first_missing_bucket,
        m.last_missing_bucket,
        coalesce(ds.duplicate_rows, 0)::bigint as duplicate_rows,
        coalesce(ms.misaligned_rows, 0)::bigint as misaligned_rows,
        coalesce(gs.gap_violations, 0)::bigint as gap_violations,
        cfg.max_missing_buckets,
        case
          when l.latest_ts is null then 'FAIL'
          when extract(epoch from (now() - l.latest_ts))::bigint > cfg.max_lag_seconds then 'FAIL'
          when coalesce(lb.rows_in_lookback, 0) = 0 then 'FAIL'
          when coalesce(m.missing_buckets, 0) > cfg.max_missing_buckets then 'WARN'
          when coalesce(ds.duplicate_rows, 0) > 0 then 'WARN'
          when coalesce(ms.misaligned_rows, 0) > 0 then 'WARN'
          when coalesce(gs.gap_violations, 0) > 0 then 'WARN'
          else 'PASS'
        end as status,
        case
          when l.latest_ts is null then 'RED'
          when extract(epoch from (now() - l.latest_ts))::bigint > cfg.max_lag_seconds then 'RED'
          when coalesce(lb.rows_in_lookback, 0) = 0 then 'RED'
          when coalesce(m.missing_buckets, 0) > cfg.max_missing_buckets then 'YELLOW'
          when coalesce(ds.duplicate_rows, 0) > 0 then 'YELLOW'
          when coalesce(ms.misaligned_rows, 0) > 0 then 'YELLOW'
          when coalesce(gs.gap_violations, 0) > 0 then 'YELLOW'
          else 'GREEN'
        end as traffic_light
      from pairs p
      cross join cfg
      left join latest l using (pair)
      left join expected_counts ec using (pair)
      left join actual_counts ac using (pair)
      left join lookback_rows lb using (pair)
      left join missing m using (pair)
      left join duplicate_stats ds using (pair)
      left join misaligned_stats ms using (pair)
      left join gap_stats gs using (pair)
      order by p.pair
    ) t;
    """


def print_rows(
    rows: list[dict[str, Any]],
    *,
    source_label: str,
    tldr: bool,
    key_fields: tuple[str, ...],
) -> None:
    if tldr:
        non_pass = [row for row in rows if str(row.get("status")).upper() != "PASS"]
        if not non_pass:
            print(f"[{source_label}] no failures/warnings")
            return
        print(f"[{source_label}] non-pass rows")
        for row in non_pass:
            parts = [f"{field}={row.get(field)}" for field in key_fields]
            print(f"- {row.get('pair')}: status={row.get('status')} light={row.get('traffic_light')} " + " ".join(parts))
        return

    print(f"[{source_label}]")
    for row in rows:
        parts = [f"{field}={row.get(field)}" for field in key_fields]
        print(f"{row.get('status'):4} {row.get('pair'):8} light={row.get('traffic_light'):6} " + " ".join(parts))


def build_output_payload(
    *,
    source: str,
    pairs: tuple[str, ...],
    window: dict[str, Any],
    rows: list[dict[str, Any]],
    meta: dict[str, Any] | None = None,
) -> dict[str, Any]:
    now = dt.datetime.now(dt.UTC).replace(microsecond=0).isoformat().replace("+00:00", "Z")
    summary = summarize_status(rows)
    return {
        "generated_at_utc": now,
        "source": source,
        "pairs": list(pairs),
        "window": window,
        "summary": summary,
        "meta": meta or {},
        "rows": rows,
    }

