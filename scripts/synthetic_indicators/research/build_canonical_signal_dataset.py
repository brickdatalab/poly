#!/usr/bin/env python3
"""Build canonical no-leak synthetic-signal dataset for BTC/ETH 15m events.

Output:
- dataset.csv.gz
- metadata.json
- availability_matrix.csv
- REPORT.md
"""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
import sys

if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from common import db_url_from_env, ensure_dir, psql_csv

START_DEFAULT = "2026-01-22T00:00:00Z"

# Minimal dependency map used only to decide whether training schema could
# reconstruct each synthetic feature without indicators schema.
TRAINING_REQUIREMENTS: dict[str, list[tuple[str, str]]] = {
    "syn_cvd_price_divergence_velocity_15m5_tplus2": [
        ("spot_15m_indicators", "cvd_50"),
        ("spot_15m_indicators", "atr_14"),
        ("spot_15m", "close"),
    ],
    "syn_window_edge_57to01_eth_nonrolling_tplus2": [
        ("spot_1m", "open"),
        ("spot_1m", "close"),
    ],
    "syn_mtf_signed_efficiency_ratio_5m12_15m8": [
        ("spot_5m", "close"),
        ("spot_15m", "close"),
    ],
    "syn_rsi_velocity_5m_3bar_z20": [
        ("spot_5m_indicators", "rsi_7"),
        ("spot_1h_indicators", "rsi_14"),
    ],
    "syn_early_impulse_liq_align_tplus2": [
        ("spot_15m", "open"),
        ("spot_1m", "close"),
        ("order_book_indicators", "imbalance"),
    ],
    "syn_oi_funding_impulse_tplus2": [
        ("spot_15m", "open"),
        ("spot_1m", "close"),
        ("oi_features", "oi_acceleration"),
    ],
    "syn_early_momentum_divergence_tplus1": [
        ("spot_1m", "close"),
        ("spot_5m_indicators", "rsi_7"),
        ("spot_5m_indicators", "macd_hist"),
        ("spot_1m_indicators", "cvd_20"),
    ],
    "syn_order_flow_accel_regime_tplus2": [
        ("spot_15m", "volume"),
        ("spot_1m", "close"),
        ("order_book_indicators", "bid_depth_25bps"),
    ],
    "syn_multitimeframe_trend_confluence_tplus2": [
        ("spot_5m_indicators", "supertrend_10_3"),
        ("spot_15m_indicators", "supertrend_10_3"),
        ("spot_15m_indicators", "ema_9"),
        ("spot_15m_indicators", "ema_21"),
        ("spot_5m", "close"),
    ],
}


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Build canonical synthetic-signal dataset")
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default="now")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--source", choices=["auto", "indicators", "training"], default="auto")
    ap.add_argument("--output-root", default="scripts/output/signal_integrity")
    return ap.parse_args()


def _to_sql_end(end_ts: str) -> str:
    return "now()" if end_ts.lower() == "now" else f"'{end_ts}'::timestamptz"


def load_active_configs(db_url: str) -> pd.DataFrame:
    rows = psql_csv(
        db_url,
        """
        select config_id, indicator_name, decision_phase, is_active
        from indicators.synthetic_indicator_configs
        where is_active
        order by config_id
        """,
    )
    return pd.DataFrame(rows)


def load_training_columns(db_url: str) -> set[tuple[str, str]]:
    rows = psql_csv(
        db_url,
        """
        select table_name, column_name
        from information_schema.columns
        where table_schema = 'training'
        """,
    )
    return {(r["table_name"], r["column_name"]) for r in rows}


def build_availability_matrix(configs: pd.DataFrame, training_cols: set[tuple[str, str]]) -> pd.DataFrame:
    recs: list[dict[str, Any]] = []
    for cfg in configs["config_id"].tolist():
        reqs = TRAINING_REQUIREMENTS.get(cfg, [])
        if not reqs:
            recs.append(
                {
                    "config_id": cfg,
                    "available_in_training": False,
                    "required_columns": "",
                    "missing_columns": "unknown_requirements",
                    "notes": "No explicit training mapping for this synthetic config",
                }
            )
            continue

        missing = [f"{t}.{c}" for (t, c) in reqs if (t, c) not in training_cols]
        recs.append(
            {
                "config_id": cfg,
                "available_in_training": len(missing) == 0,
                "required_columns": ", ".join(f"{t}.{c}" for (t, c) in reqs),
                "missing_columns": ", ".join(missing),
                "notes": "",
            }
        )
    return pd.DataFrame(recs)


def fetch_indicators_canonical_dataset(
    db_url: str,
    start_ts: str,
    end_ts: str,
    pairs: list[str],
) -> pd.DataFrame:
    pair_sql = ", ".join(f"'{p}'" for p in pairs)
    sql = f"""
    with labels as (
      select
        o.pair,
        o.bucket_time,
        o.open::float8 as event_open,
        o.close::float8 as event_close,
        ((o.close - o.open) / nullif(o.open, 0))::float8 as event_return,
        case
          when o.close > o.open then 'up'
          when o.close < o.open then 'down'
          else 'flat'
        end as outcome
      from indicators.ohlcv_15m o
      where o.pair in ({pair_sql})
        and o.bucket_time >= '{start_ts}'::timestamptz
        and o.bucket_time <= {_to_sql_end(end_ts)}
        and extract(second from o.bucket_time) = 0
        and extract(minute from o.bucket_time)::int in (0, 15, 30, 45)
    )
    select
      s.pair,
      s.bucket_time,
      s.config_id,
      c.decision_phase,
      s.v1::float8 as value,
      s.v2::float8,
      s.v3::float8,
      s.v4::float8,
      s.v5::float8,
      s.source_time,
      s.computed_at,
      l.event_open,
      l.event_close,
      l.event_return,
      l.outcome,
      atr.v1::float8 as atr_14_15m,
      ema9.v1::float8 as ema_9_15m,
      ema21.v1::float8 as ema_21_15m,
      ob.spread_pct::float8 as spread_pct,
      ob.imbalance::float8 as imbalance,
      oif.funding_oi_pressure::float8 as funding_oi_pressure,
      oif.oi_acceleration::float8 as oi_acceleration
    from indicators.synthetic_indicator_values s
    join indicators.synthetic_indicator_configs c
      on c.config_id = s.config_id
    join labels l
      on l.pair = s.pair
     and l.bucket_time = s.bucket_time
    left join indicators.indicator_values atr
      on atr.pair = s.pair and atr.bucket_time = s.bucket_time and atr.config_id = 'atr_14_15m'
    left join indicators.indicator_values ema9
      on ema9.pair = s.pair and ema9.bucket_time = s.bucket_time and ema9.config_id = 'ema_9_15m'
    left join indicators.indicator_values ema21
      on ema21.pair = s.pair and ema21.bucket_time = s.bucket_time and ema21.config_id = 'ema_21_15m'
    left join lateral (
      select ob1.spread_pct, ob1.imbalance
      from indicators.order_book_indicators ob1
      where ob1.pair = s.pair
        and ob1.captured_at <= s.bucket_time + interval '2 minutes'
      order by ob1.captured_at desc
      limit 1
    ) ob on true
    left join indicators.oi_features oif
      on oif.pair = s.pair and oif.bucket_time = s.bucket_time
    where c.is_active
      and s.pair in ({pair_sql})
      and l.outcome in ('up','down')
      and s.v1 is not null
    order by s.pair, s.config_id, s.bucket_time
    """
    rows = psql_csv(db_url, sql)
    df = pd.DataFrame(rows)
    if df.empty:
        return df

    float_cols = [
        "value",
        "v2",
        "v3",
        "v4",
        "v5",
        "event_open",
        "event_close",
        "event_return",
        "atr_14_15m",
        "ema_9_15m",
        "ema_21_15m",
        "spread_pct",
        "imbalance",
        "funding_oi_pressure",
        "oi_acceleration",
    ]
    for c in float_cols:
        if c in df.columns:
            df[c] = pd.to_numeric(df[c], errors="coerce")

    for c in ["bucket_time", "source_time", "computed_at"]:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")

    df["is_up"] = (df["outcome"] == "up").astype(bool)
    phase_to_minutes = {"t_plus_1m": 1, "t_plus_2m": 2}
    df["decision_minute_offset"] = df["decision_phase"].map(phase_to_minutes).fillna(0).astype(int)
    df["decision_deadline"] = df["bucket_time"] + pd.to_timedelta(df["decision_minute_offset"], unit="m")
    df["source_time_valid"] = df["source_time"].isna() | (df["source_time"] <= df["decision_deadline"])
    return df


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[3]
    db_url = db_url_from_env(root)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = ensure_dir(root / args.output_root / run_id)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    cfg = load_active_configs(db_url)
    train_cols = load_training_columns(db_url)
    availability = build_availability_matrix(cfg, train_cols)

    source_used = args.source
    if args.source == "auto":
        source_used = "training" if availability["available_in_training"].all() else "indicators"

    if source_used != "indicators":
        # Training reconstruction is intentionally not auto-generated yet;
        # we hard-fallback to indicators to keep production research deterministic.
        source_used = "indicators"

    df = fetch_indicators_canonical_dataset(db_url, args.start, args.end, pairs)

    data_path = out_dir / "dataset.csv.gz"
    avail_path = out_dir / "availability_matrix.csv"
    meta_path = out_dir / "metadata.json"
    report_path = out_dir / "REPORT.md"

    df.to_csv(data_path, index=False, compression="gzip")
    availability.to_csv(avail_path, index=False)

    meta = {
        "run_id": run_id,
        "start": args.start,
        "end": args.end,
        "pairs": pairs,
        "source_requested": args.source,
        "source_used": source_used,
        "rows": int(len(df)),
        "configs": sorted(df["config_id"].dropna().unique().tolist()) if not df.empty else [],
        "source_time_valid_pct": float(df["source_time_valid"].mean()) if not df.empty else None,
    }
    meta_path.write_text(json.dumps(meta, indent=2))

    by_cfg_pair = (
        df.groupby(["pair", "config_id"], as_index=False)
        .size()
        .rename(columns={"size": "rows"})
        .sort_values(["pair", "config_id"])
    ) if not df.empty else pd.DataFrame(columns=["pair", "config_id", "rows"])

    report_lines = [
        "# Canonical Signal Dataset",
        "",
        f"Run ID: `{run_id}`",
        f"Source requested: `{args.source}`",
        f"Source used: `{source_used}`",
        f"Rows: `{len(df)}`",
        f"Configs: `{df['config_id'].nunique() if not df.empty else 0}`",
        f"Source-time validity: `{(df['source_time_valid'].mean()*100):.2f}%`" if not df.empty else "Source-time validity: `n/a`",
        "",
        "## Rows by Pair/Config",
        "",
    ]

    if by_cfg_pair.empty:
        report_lines.append("No rows returned.")
    else:
        report_lines.append("| Pair | Config | Rows |")
        report_lines.append("|---|---|---:|")
        for r in by_cfg_pair.to_dict(orient="records"):
            report_lines.append(f"| {r['pair']} | {r['config_id']} | {r['rows']} |")

    report_lines += [
        "",
        "## Files",
        "",
        f"- `{data_path}`",
        f"- `{avail_path}`",
        f"- `{meta_path}`",
    ]

    report_path.write_text("\n".join(report_lines) + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
