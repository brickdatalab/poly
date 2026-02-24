#!/usr/bin/env python3
"""Correlate synthetic indicator values to next 15m outcome direction.

For each (pair, synthetic indicator), this script searches threshold rules:
- value >= threshold
- value <= threshold

It reports the strongest UP and DOWN directional rules over quarter-hour events
(:00/:15/:30/:45) from a given time range.
"""

from __future__ import annotations

import argparse
import csv
import json
import os
import subprocess
from concurrent.futures import ProcessPoolExecutor
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np


START_DEFAULT = "2026-01-22T00:00:00Z"


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


def fetch_dataset(db_url: str, start_ts: str, end_ts: str) -> list[dict[str, str]]:
    to_sql = "now()" if end_ts.lower() == "now" else f"'{end_ts}'::timestamptz"
    sql = f"""
    with event_labels as (
      select
        o0.pair,
        o0.bucket_time,
        o0.open as event_open,
        o14.close as event_close,
        case
          when o14.close > o0.open then 'up'
          when o14.close < o0.open then 'down'
          else 'flat'
        end as outcome
      from indicators.ohlcv_1m o0
      join indicators.ohlcv_1m o14
        on o14.pair = o0.pair
       and o14.bucket_time = o0.bucket_time + interval '14 minutes'
      where extract(minute from o0.bucket_time)::int in (0, 15, 30, 45)
        and o0.bucket_time >= '{start_ts}'::timestamptz
        and o0.bucket_time <= {to_sql}
    )
    select
      s.pair,
      s.config_id,
      s.bucket_time,
      s.v1::double precision as value,
      e.outcome,
      e.event_open::double precision as event_open,
      e.event_close::double precision as event_close
    from indicators.synthetic_indicator_values s
    join indicators.synthetic_indicator_configs c
      on c.config_id = s.config_id and c.is_active
    join event_labels e
      on e.pair = s.pair
     and e.bucket_time = s.bucket_time
    where s.bucket_time >= '{start_ts}'::timestamptz
      and s.bucket_time <= {to_sql}
      and s.v1 is not null
      and e.outcome in ('up', 'down')
    order by s.pair, s.config_id, s.bucket_time
    """
    return psql_csv(db_url, sql)


@dataclass(frozen=True)
class RuleResult:
    side: str
    operator: str
    threshold: float
    support_n: int
    support_pct: float
    wins: int
    precision: float
    lift_vs_base: float


def _best_rule_for_side(
    side: str,
    x: np.ndarray,
    y_is_up: np.ndarray,
    min_count: int,
) -> RuleResult | None:
    n = x.size
    if n == 0:
        return None
    y_side = y_is_up if side == "up" else ~y_is_up
    base_rate = float(np.mean(y_side))

    order = np.argsort(x, kind="mergesort")
    xs = x[order]
    ys = y_side[order].astype(np.int64)

    uniq, first_idx, counts = np.unique(xs, return_index=True, return_counts=True)
    last_idx = first_idx + counts - 1

    prefix = np.cumsum(ys)
    total = int(prefix[-1])

    best: RuleResult | None = None

    # <= threshold
    n_le = last_idx + 1
    wins_le = prefix[last_idx]
    for i, t in enumerate(uniq):
        cnt = int(n_le[i])
        if cnt < min_count:
            continue
        wins = int(wins_le[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleResult(
            side=side,
            operator="<=",
            threshold=float(t),
            support_n=cnt,
            support_pct=cnt / n,
            wins=wins,
            precision=prec,
            lift_vs_base=(prec - base_rate),
        )
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    # >= threshold
    # wins_ge = total - prefix[first_idx-1]
    wins_before_first = np.where(first_idx > 0, prefix[first_idx - 1], 0)
    n_ge = n - first_idx
    wins_ge = total - wins_before_first
    for i, t in enumerate(uniq):
        cnt = int(n_ge[i])
        if cnt < min_count:
            continue
        wins = int(wins_ge[i])
        prec = wins / cnt if cnt else 0.0
        cand = RuleResult(
            side=side,
            operator=">=",
            threshold=float(t),
            support_n=cnt,
            support_pct=cnt / n,
            wins=wins,
            precision=prec,
            lift_vs_base=(prec - base_rate),
        )
        if (best is None) or (cand.precision > best.precision) or (
            np.isclose(cand.precision, best.precision) and cand.support_n > best.support_n
        ):
            best = cand

    return best


def analyze_group(task: tuple[str, str, list[tuple[float, str]], float, int]) -> dict[str, Any]:
    pair, config_id, rows, min_support_pct, min_support_n = task
    x = np.array([v for v, _ in rows], dtype=np.float64)
    y_up = np.array([o == "up" for _, o in rows], dtype=bool)
    n = x.size
    if n == 0:
        return {"pair": pair, "config_id": config_id, "n_total": 0}

    min_count = max(min_support_n, int(np.ceil(n * min_support_pct)))
    base_up = float(np.mean(y_up))
    base_down = 1.0 - base_up

    best_up = _best_rule_for_side("up", x, y_up, min_count)
    best_down = _best_rule_for_side("down", x, y_up, min_count)

    def rr_to_dict(rr: RuleResult | None) -> dict[str, Any] | None:
        if rr is None:
            return None
        return {
            "side": rr.side,
            "operator": rr.operator,
            "threshold": rr.threshold,
            "support_n": rr.support_n,
            "support_pct": rr.support_pct,
            "wins": rr.wins,
            "precision": rr.precision,
            "lift_vs_base": rr.lift_vs_base,
        }

    return {
        "pair": pair,
        "config_id": config_id,
        "n_total": int(n),
        "min_support_n_used": int(min_count),
        "base_up_rate": base_up,
        "base_down_rate": base_down,
        "best_up_rule": rr_to_dict(best_up),
        "best_down_rule": rr_to_dict(best_down),
    }


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Analyze synthetic indicator threshold correlation.")
    ap.add_argument("--start", default=START_DEFAULT, help="Inclusive UTC start timestamp.")
    ap.add_argument("--end", default="now", help="Inclusive UTC end timestamp or 'now'.")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD", help="Comma-separated pairs.")
    ap.add_argument("--min-support-pct", type=float, default=0.02, help="Min support fraction per rule.")
    ap.add_argument("--min-support-n", type=int, default=30, help="Absolute min support per rule.")
    ap.add_argument("--workers", type=int, default=max(2, (os.cpu_count() or 8) - 1))
    return ap.parse_args()


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = env.get("SUPABASE_DB_URL")
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")

    allowed_pairs = {p.strip() for p in args.pairs.split(",") if p.strip()}
    raw = fetch_dataset(db_url, args.start, args.end)
    raw = [r for r in raw if r["pair"] in allowed_pairs]
    if not raw:
        raise SystemExit("No rows returned for requested range/pairs.")

    grouped: dict[tuple[str, str], list[tuple[float, str]]] = {}
    for r in raw:
        key = (r["pair"], r["config_id"])
        grouped.setdefault(key, []).append((float(r["value"]), r["outcome"]))

    tasks = [
        (pair, config_id, rows, args.min_support_pct, args.min_support_n)
        for (pair, config_id), rows in grouped.items()
    ]

    with ProcessPoolExecutor(max_workers=args.workers) as ex:
        results = list(ex.map(analyze_group, tasks))

    # Sort for deterministic output.
    results.sort(key=lambda x: (x["pair"], x["config_id"]))

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = root / "scripts" / "output" / "synthetic_indicators" / f"correlation_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    payload = {
        "generated_at_utc": datetime.now(timezone.utc).isoformat(),
        "start": args.start,
        "end": args.end,
        "pairs": sorted(allowed_pairs),
        "min_support_pct": args.min_support_pct,
        "min_support_n": args.min_support_n,
        "workers": args.workers,
        "group_count": len(results),
        "results": results,
    }
    (out_dir / "results.json").write_text(json.dumps(payload, indent=2))

    lines = [
        "# Synthetic Indicator -> 15m Outcome Correlation",
        "",
        f"Range: `{args.start}` to `{args.end}`",
        f"Pairs: `{','.join(sorted(allowed_pairs))}`",
        f"Min support: `{args.min_support_pct:.2%}` and `n >= {args.min_support_n}` (whichever is larger per group)",
        "",
    ]
    for r in results:
        lines.append(f"## {r['pair']} / {r['config_id']}")
        lines.append(f"- n_total: **{r['n_total']}**")
        lines.append(f"- base up/down: **{r['base_up_rate']:.2%} / {r['base_down_rate']:.2%}**")
        up = r.get("best_up_rule")
        dn = r.get("best_down_rule")
        if up:
            lines.append(
                f"- best UP rule: `value {up['operator']} {up['threshold']:.6f}` -> "
                f"UP **{up['precision']:.2%}** (support {up['support_n']} / {up['support_pct']:.2%})"
            )
        if dn:
            lines.append(
                f"- best DOWN rule: `value {dn['operator']} {dn['threshold']:.6f}` -> "
                f"DOWN **{dn['precision']:.2%}** (support {dn['support_n']} / {dn['support_pct']:.2%})"
            )
        lines.append("")

    (out_dir / "REPORT.md").write_text("\n".join(lines).rstrip() + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()

