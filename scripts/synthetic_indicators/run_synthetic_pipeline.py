#!/usr/bin/env python3
"""Run synthetic indicator pipeline (isolated subsystem).

Modes:
- backfill: run indicators.fn_backfill_synthetic_indicators over a range.
- incremental: enqueue + process synthetic queue in batches.
- healthcheck: report freshness and queue status.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


DEFAULT_PAIRS = "BTC-USD,ETH-USD,SOL-USD"


def load_db_url(root: Path) -> str:
    env = {}
    for line in (root / ".env").read_text().splitlines():
        s = line.strip()
        if not s or s.startswith("#") or "=" not in s:
            continue
        k, v = s.split("=", 1)
        env[k.strip()] = v.strip().strip('"').strip("'")
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_scalar(db_url: str, sql: str) -> str:
    q = sql.strip()
    if q.endswith(";"):
        q = q[:-1]
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
    ).strip()
    return out


def psql_json(db_url: str, sql: str) -> Any:
    out = psql_scalar(db_url, sql)
    return json.loads(out) if out else {}


def parse_pairs(csv_text: str) -> list[str]:
    return [p.strip() for p in csv_text.split(",") if p.strip()]


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run synthetic indicator subsystem.")
    ap.add_argument("--mode", choices=["backfill", "incremental", "healthcheck"], required=True)
    ap.add_argument("--from", dest="from_ts", default="2026-01-22T07:15:00Z")
    ap.add_argument("--to", dest="to_ts", default="now")
    ap.add_argument("--pairs", default=DEFAULT_PAIRS)
    ap.add_argument("--batch-size", type=int, default=200)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--sleep-sec", type=float, default=0.0)
    return ap.parse_args(argv)


def run_backfill(db_url: str, from_ts: str, to_ts: str, pairs: list[str]) -> dict[str, Any]:
    arr = "{" + ",".join(f'"{p}"' for p in pairs) + "}"
    to_sql = "now()" if to_ts.lower() == "now" else f"'{to_ts}'::timestamptz"
    sql = f"""
    select jsonb_build_object(
      'backfill_calls', indicators.fn_backfill_synthetic_indicators('{from_ts}'::timestamptz, {to_sql}, '{arr}'::text[])
    )::text
    """
    return psql_json(db_url, sql)


def run_incremental(db_url: str, batch_size: int, rounds: int, sleep_sec: float) -> dict[str, Any]:
    total_enqueued = 0
    total_processed = 0
    per_round = []
    for i in range(rounds):
        enq = int(
            psql_scalar(
                db_url,
                "select indicators.fn_enqueue_synthetic_jobs(interval '4 hours')::text",
            )
            or "0"
        )
        done = int(
            psql_scalar(
                db_url,
                f"select indicators.fn_process_synthetic_jobs({int(batch_size)})::text",
            )
            or "0"
        )
        total_enqueued += enq
        total_processed += done
        per_round.append({"round": i + 1, "enqueued": enq, "processed": done})
        if sleep_sec > 0 and i < rounds - 1:
            time.sleep(sleep_sec)
    return {
        "rounds": rounds,
        "total_enqueued": total_enqueued,
        "total_processed": total_processed,
        "per_round": per_round,
    }


def run_healthcheck(db_url: str) -> dict[str, Any]:
    sql = """
    with cfg as (
      select count(*)::int as n_active
      from indicators.synthetic_indicator_configs
      where is_active
    ),
    latest as (
      select pair, max(bucket_time) as max_bucket
      from indicators.synthetic_indicator_values
      group by pair
    ),
    q as (
      select
        count(*) filter (where status='pending')::int as pending,
        count(*) filter (where status='running')::int as running,
        count(*) filter (where status='failed')::int as failed,
        count(*) filter (where status='done')::int as done
      from indicators.synthetic_job_queue
    )
    select jsonb_build_object(
      'active_configs', (select n_active from cfg),
      'latest_per_pair', (select jsonb_object_agg(pair, max_bucket) from latest),
      'queue', (select to_jsonb(q) from q)
    )::text
    """
    return psql_json(db_url, sql)


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "synthetic_indicators" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    pairs = parse_pairs(args.pairs)
    if args.mode == "backfill":
        result = run_backfill(db_url, args.from_ts, args.to_ts, pairs)
    elif args.mode == "incremental":
        result = run_incremental(db_url, args.batch_size, args.rounds, args.sleep_sec)
    else:
        result = run_healthcheck(db_url)

    payload = {
        "mode": args.mode,
        "from": args.from_ts,
        "to": args.to_ts,
        "pairs": pairs,
        "batch_size": args.batch_size,
        "rounds": args.rounds,
        "result": result,
    }

    (out_dir / "result.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "REPORT.md").write_text(
        "\n".join(
            [
                "# Synthetic Indicators Pipeline Run",
                "",
                f"Run: `{out_dir}`",
                "",
                f"mode: `{args.mode}`",
                f"pairs: `{','.join(pairs)}`",
                "",
                "```json",
                json.dumps(payload, indent=2),
                "```",
            ]
        )
        + "\n"
    )
    print(str(out_dir))


if __name__ == "__main__":
    main()
