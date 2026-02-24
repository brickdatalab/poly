#!/usr/bin/env python3
"""
Compare training vs indicators 15m feature distributions (read-only).

Why:
- We are NOT changing indicators schema or semantics.
- To reduce training-serving skew, we create RT-aligned datasets in training.
- This script checks coverage and basic distribution sanity between:
  - training.rt_features_15m_from_unified_v1 (historical features; may differ in math/source)
  - indicators.v_model_15m (serving features; authoritative)
  - training.rt_features_from_indicators_15m_v1 (snapshot of serving features inside training)

Outputs:
- JSON report written to scripts/output/compare_training_vs_indicators_15m_<UTC>.json

Connection:
- Uses SUPABASE_DB_URL + SUPABASE_DB_PASSWORD (either env vars or local .env).
  We pass password via PGPASSWORD to avoid embedding it in the connection string.
"""

from __future__ import annotations

import datetime as dt
import json
import os
import subprocess
from pathlib import Path
from typing import Any, Final


FEATURES_V1: Final[list[str]] = [
    "open",
    "high",
    "low",
    "close",
    "volume",
    "ema_9",
    "ema_21",
    "ema_50",
    "sma_20",
    "sma_50",
    "rsi_7",
    "rsi_14",
    "rsi_21",
    "macd_line",
    "macd_signal",
    "cci_20",
    "mfi_14",
    "momentum_10",
    "roc_12",
    "adx_14",
    "atr_14",
    "atr_21",
    "cmf_20",
    "cvd_50",
    "cvd_100",
    "vwap_50",
    "vwap_96",
    "keltner_upper",
    "keltner_middle",
    "keltner_lower",
    "pivot",
    "pivot_r1",
    "pivot_s1",
]


def utc_now() -> dt.datetime:
    return dt.datetime.now(dt.UTC)


def load_dotenv(dotenv_path: Path) -> None:
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


def psql_json(db_url: str, db_password: str, sql: str, timeout_s: int = 90) -> Any:
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
    except subprocess.CalledProcessError as e:
        raise RuntimeError(e.output.decode("utf-8", errors="replace")) from e
    except subprocess.TimeoutExpired as e:
        raise RuntimeError(f"psql timed out after {timeout_s}s") from e

    s = out.decode("utf-8", errors="replace").strip()
    if not s:
        return None
    return json.loads(s)


def stats_sql(source_name: str, from_clause: str, where_clause: str) -> str:
    # We compute simple stats per feature and return a JSON array of rows.
    unions: list[str] = []
    for col in FEATURES_V1:
        unions.append(
            f"""
            select
              '{source_name}'::text as source,
              '{col}'::text as feature,
              count(*)::bigint as n,
              count(*) filter (where {col} is null)::bigint as n_null,
              avg({col}::float8) as mean,
              stddev_samp({col}::float8) as stddev,
              min({col}::float8) as min,
              percentile_cont(0.5) within group (order by {col}::float8) as p50,
              percentile_cont(0.9) within group (order by {col}::float8) as p90,
              percentile_cont(0.99) within group (order by {col}::float8) as p99,
              max({col}::float8) as max
            {from_clause}
            {where_clause}
            """
        )
    return (
        "with rows as (\n"
        + "\nunion all\n".join(unions)
        + "\n)\nselect coalesce(jsonb_agg(to_jsonb(rows) order by feature), '[]'::jsonb) from rows;\n"
    )


def coverage_sql() -> str:
    return """
with ind as (
  select pair, bucket_time
  from indicators.v_model_15m
  where pair in ('BTC-USD','ETH-USD','SOL-USD')
),
unified as (
  select (symbol || '-USD')::text as pair, open_time as bucket_time
  from training.unified_15m
  where symbol in ('BTC','ETH','SOL')
),
joined as (
  select i.pair, i.bucket_time
  from ind i
  join unified u using (pair, bucket_time)
)
select jsonb_build_object(
  'indicators_rows', (select count(*) from ind),
  'training_unified_rows', (select count(*) from unified),
  'joined_rows', (select count(*) from joined),
  'overlap_min_ts', (select min(bucket_time) from joined),
  'overlap_max_ts', (select max(bucket_time) from joined)
);
"""


def main() -> None:
    load_dotenv(Path(__file__).resolve().parents[1] / ".env")
    db_url = require_env("SUPABASE_DB_URL")
    db_password = require_env("SUPABASE_DB_PASSWORD")

    # Overlap window chosen where both training.unified_15m and indicators.v_model_15m exist.
    overlap_start = "2026-01-22 07:00:00+00"
    overlap_end = "2026-02-01 16:00:00+00"

    report: dict[str, Any] = {
        "generated_at_utc": utc_now().isoformat(),
        "overlap_window": {"start": overlap_start, "end": overlap_end},
        "features_v1": FEATURES_V1,
    }

    report["coverage"] = psql_json(db_url, db_password, coverage_sql())

    where_overlap_ind = (
        "where pair in ('BTC-USD','ETH-USD','SOL-USD')\n"
        f"  and bucket_time >= '{overlap_start}'::timestamptz\n"
        f"  and bucket_time <  '{overlap_end}'::timestamptz"
    )
    where_overlap_unified = (
        "where pair in ('BTC-USD','ETH-USD','SOL-USD')\n"
        f"  and bucket_time >= '{overlap_start}'::timestamptz\n"
        f"  and bucket_time <  '{overlap_end}'::timestamptz"
    )

    report["stats"] = {
        "indicators_v_model_15m": psql_json(
            db_url,
            db_password,
            stats_sql(
                "indicators.v_model_15m",
                "from indicators.v_model_15m",
                where_overlap_ind,
            ),
        ),
        "training_rt_features_15m_from_unified_v1": psql_json(
            db_url,
            db_password,
            stats_sql(
                "training.rt_features_15m_from_unified_v1",
                "from training.rt_features_15m_from_unified_v1",
                where_overlap_unified,
            ),
        ),
        "training_rt_features_from_indicators_15m_v1": psql_json(
            db_url,
            db_password,
            stats_sql(
                "training.rt_features_from_indicators_15m_v1",
                "from training.rt_features_from_indicators_15m_v1",
                where_overlap_ind,
            ),
        ),
    }

    out_dir = Path(__file__).resolve().parents[1] / "scripts" / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / f"compare_training_vs_indicators_15m_{utc_now().strftime('%Y%m%dT%H%M%SZ')}.json"
    out_path.write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")
    print(str(out_path))


if __name__ == "__main__":
    main()
