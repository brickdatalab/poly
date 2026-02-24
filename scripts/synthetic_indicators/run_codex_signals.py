#!/usr/bin/env python3
"""Run codex realtime signal emission pipeline.

Modes:
- incremental: enqueue and process codex signal jobs.
- healthcheck: report queue status and latest emitted signal timestamps.
"""

from __future__ import annotations

import argparse
import json
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any


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


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Run codex signal pipeline.")
    ap.add_argument("--mode", choices=["incremental", "healthcheck"], required=True)
    ap.add_argument("--lookback-minutes", type=int, default=45)
    ap.add_argument("--batch-size", type=int, default=300)
    ap.add_argument("--rounds", type=int, default=1)
    ap.add_argument("--sleep-sec", type=float, default=0.0)
    return ap.parse_args(argv)


def run_incremental(
    db_url: str, lookback_minutes: int, batch_size: int, rounds: int, sleep_sec: float
) -> dict[str, Any]:
    total_enqueued = 0
    total_processed = 0
    per_round = []
    for i in range(rounds):
        enq = int(
            psql_scalar(
                db_url,
                f"select indicators.fn_enqueue_codex_signal_jobs(interval '{int(lookback_minutes)} minutes')::text",
            )
            or "0"
        )
        done = int(
            psql_scalar(
                db_url,
                f"select indicators.fn_process_codex_signal_jobs({int(batch_size)})::text",
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
        "lookback_minutes": lookback_minutes,
        "total_enqueued": total_enqueued,
        "total_processed": total_processed,
        "per_round": per_round,
    }


def run_healthcheck(db_url: str) -> dict[str, Any]:
    sql = """
    with q as (
      select
        count(*) filter (where status='pending')::int as pending,
        count(*) filter (where status='running')::int as running,
        count(*) filter (where status='failed')::int as failed,
        count(*) filter (where status='done')::int as done
      from indicators.codex_signal_job_queue
    ),
    latest as (
      select pair, max(bucket_time) as max_bucket, max(decision_minute) as max_decision
      from indicators.codex_signals
      group by pair
    )
    select jsonb_build_object(
      'queue', (select to_jsonb(q) from q),
      'latest_per_pair', (select jsonb_object_agg(pair, jsonb_build_object('bucket_time', max_bucket, 'decision_minute', max_decision)) from latest),
      'active_rules', (select count(*)::int from indicators.codex_signal_rules where is_active)
    )::text
    """
    return psql_json(db_url, sql)


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    db_url = load_db_url(root)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "codex_signals" / run_id
    out_dir.mkdir(parents=True, exist_ok=True)

    if args.mode == "incremental":
        result = run_incremental(
            db_url,
            lookback_minutes=args.lookback_minutes,
            batch_size=args.batch_size,
            rounds=args.rounds,
            sleep_sec=args.sleep_sec,
        )
    else:
        result = run_healthcheck(db_url)

    payload = {
        "mode": args.mode,
        "lookback_minutes": args.lookback_minutes,
        "batch_size": args.batch_size,
        "rounds": args.rounds,
        "result": result,
    }

    (out_dir / "result.json").write_text(json.dumps(payload, indent=2))
    (out_dir / "REPORT.md").write_text(
        "\n".join(
            [
                "# Codex Signals Pipeline Run",
                "",
                f"Run: `{out_dir}`",
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
