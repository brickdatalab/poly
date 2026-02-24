#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import subprocess
from datetime import datetime, timedelta, timezone
from io import StringIO
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

from engine import build_db_url, load_env, table


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Backtest OB_Imbalance_Acceleration_3p and OI_Price_Divergence_4h.")
    ap.add_argument("--as-of", default="2026-02-16T14:45:00Z", help="UTC end timestamp (inclusive)")
    ap.add_argument("--days", type=int, default=17, help="Lookback days")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD", help="Comma-separated pairs")
    return ap.parse_args()


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def psql_copy_df(db_url: str, sql: str) -> pd.DataFrame:
    copy_sql = "\\copy (" + sql.strip().rstrip(";") + ") TO STDOUT WITH CSV HEADER"
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-c", copy_sql],
        text=True,
    )
    return pd.read_csv(StringIO(out))


def asof_join_pairwise(
    left: pd.DataFrame,
    right: pd.DataFrame,
    *,
    pairs: list[str],
    left_on: str,
    right_on: str,
    cols: list[str],
) -> pd.DataFrame:
    chunks: list[pd.DataFrame] = []
    for pair in pairs:
        l = left[left["pair"] == pair].sort_values(left_on)
        r = right[right["pair"] == pair].sort_values(right_on)
        if l.empty:
            continue
        if r.empty:
            miss = l.copy()
            for c in cols:
                miss[c] = np.nan
            chunks.append(miss)
            continue
        m = pd.merge_asof(l, r[[right_on] + cols], left_on=left_on, right_on=right_on, direction="backward")
        if right_on != left_on and right_on in m.columns:
            m = m.drop(columns=[right_on])
        chunks.append(m)
    if not chunks:
        return left.copy()
    return pd.concat(chunks, ignore_index=True)


def summarize(df: pd.DataFrame, indicator: str, pairs: list[str]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for pair in pairs + ["COMBINED"]:
        d = df if pair == "COMBINED" else df[df["pair"] == pair]
        events = int(len(d))
        ready = int(d["ready"].sum())
        fired = d[d["pred"] != "none"]
        triggered = int(len(fired))
        correct = int((((fired["pred"] == "up") & (fired["outcome_up"] == 1)) | ((fired["pred"] == "down") & (fired["outcome_up"] == 0))).sum())
        acc = (100.0 * correct / triggered) if triggered else None
        coverage = (100.0 * triggered / events) if events else None
        rows.append(
            {
                "indicator": indicator,
                "pair": pair,
                "events": events,
                "ready": ready,
                "triggered": triggered,
                "correct": correct,
                "accuracy_pct": round(acc, 4) if acc is not None else None,
                "coverage_pct": round(coverage, 4) if coverage is not None else None,
                "up_triggers": int((fired["pred"] == "up").sum()),
                "down_triggers": int((fired["pred"] == "down").sum()),
            }
        )
    return pd.DataFrame(rows)


def main() -> int:
    args = parse_args()
    as_of = parse_dt(args.as_of)
    start = as_of - timedelta(days=int(args.days))
    fetch_start = start - timedelta(days=1)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    pair_sql = ",".join(f"'{p}'" for p in pairs)

    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    events = psql_copy_df(
        db_url,
        f"""
        select pair, bucket_time, open, close
        from indicators.ohlcv_15m
        where pair in ({pair_sql})
          and bucket_time >= '{start.strftime('%Y-%m-%d %H:%M:%S+00')}'
          and bucket_time <= '{as_of.strftime('%Y-%m-%d %H:%M:%S+00')}'
        order by pair, bucket_time
        """,
    )
    ob = psql_copy_df(
        db_url,
        f"""
        select pair, captured_at, imbalance, bid_slope, ask_slope, depth_ratio
        from indicators.order_book_indicators
        where pair in ({pair_sql})
          and captured_at >= '{fetch_start.strftime('%Y-%m-%d %H:%M:%S+00')}'
          and captured_at <= '{as_of.strftime('%Y-%m-%d %H:%M:%S+00')}'
        order by pair, captured_at
        """,
    )
    iv_mom = psql_copy_df(
        db_url,
        f"""
        select pair, bucket_time, v1 as momentum_10_15m
        from indicators.indicator_values
        where pair in ({pair_sql})
          and config_id = 'momentum_10_15m'
          and bucket_time >= '{fetch_start.strftime('%Y-%m-%d %H:%M:%S+00')}'
          and bucket_time <= '{as_of.strftime('%Y-%m-%d %H:%M:%S+00')}'
        order by pair, bucket_time
        """,
    )
    oi = psql_copy_df(
        db_url,
        f"""
        select pair, bucket_time, oi_roc_4h, price_oi_corr_16
        from indicators.oi_features
        where pair in ({pair_sql})
          and bucket_time >= '{fetch_start.strftime('%Y-%m-%d %H:%M:%S+00')}'
          and bucket_time <= '{as_of.strftime('%Y-%m-%d %H:%M:%S+00')}'
        order by pair, bucket_time
        """,
    )

    for df, tcol in [(events, "bucket_time"), (ob, "captured_at"), (iv_mom, "bucket_time"), (oi, "bucket_time")]:
        df[tcol] = pd.to_datetime(df[tcol], utc=True, format="mixed", errors="coerce")

    events["open"] = pd.to_numeric(events["open"], errors="coerce")
    events["close"] = pd.to_numeric(events["close"], errors="coerce")
    events = events.dropna(subset=["pair", "bucket_time", "open", "close"])
    events = events[events["close"] != events["open"]].copy()
    events["outcome_up"] = (events["close"] > events["open"]).astype(int)

    for c in ["imbalance", "bid_slope", "ask_slope", "depth_ratio"]:
        ob[c] = pd.to_numeric(ob[c], errors="coerce")
    for c in ["momentum_10_15m"]:
        iv_mom[c] = pd.to_numeric(iv_mom[c], errors="coerce")
    for c in ["oi_roc_4h", "price_oi_corr_16"]:
        oi[c] = pd.to_numeric(oi[c], errors="coerce")

    # OB indicator features
    ob_base = events[["pair", "bucket_time", "outcome_up"]].copy()
    ob_base["t_plus_1m"] = ob_base["bucket_time"] + pd.Timedelta(minutes=1)
    ob_base["t_minus_2m"] = ob_base["bucket_time"] - pd.Timedelta(minutes=2)

    now_join = asof_join_pairwise(ob_base, ob, pairs=pairs, left_on="t_plus_1m", right_on="captured_at", cols=["imbalance", "bid_slope", "ask_slope", "depth_ratio"])
    now_join = now_join.rename(
        columns={
            "imbalance": "imb_tplus1",
            "bid_slope": "bid_slope_tplus1",
            "ask_slope": "ask_slope_tplus1",
            "depth_ratio": "depth_ratio_tplus1",
        }
    )
    prev_join = asof_join_pairwise(now_join, ob, pairs=pairs, left_on="t_minus_2m", right_on="captured_at", cols=["imbalance", "bid_slope", "ask_slope"])
    prev_join = prev_join.rename(columns={"imbalance": "imb_tminus2", "bid_slope": "bid_slope_tminus2", "ask_slope": "ask_slope_tminus2"})

    ob_eval = prev_join.copy()
    ob_eval["ready"] = ob_eval[
        [
            "imb_tplus1",
            "imb_tminus2",
            "bid_slope_tplus1",
            "bid_slope_tminus2",
            "ask_slope_tplus1",
            "ask_slope_tminus2",
            "depth_ratio_tplus1",
        ]
    ].notna().all(axis=1)
    ob_eval["imbalance_delta"] = ob_eval["imb_tplus1"] - ob_eval["imb_tminus2"]
    ob_eval["bid_slope_delta"] = ob_eval["bid_slope_tplus1"] - ob_eval["bid_slope_tminus2"]
    ob_eval["composite"] = ob_eval["imbalance_delta"] + (0.5 * ob_eval["bid_slope_delta"])
    ob_eval["pred"] = "none"
    ob_eval.loc[ob_eval["ready"] & (ob_eval["composite"] > 1.2), "pred"] = "up"
    ob_eval.loc[ob_eval["ready"] & (ob_eval["composite"] < -1.2), "pred"] = "down"

    # OI indicator features
    mom = iv_mom.sort_values(["pair", "bucket_time"]).copy()
    mom["momentum_prev"] = mom.groupby("pair")["momentum_10_15m"].shift(1)

    oi_base = events[["pair", "bucket_time", "outcome_up"]].copy()
    oi_base = asof_join_pairwise(oi_base, oi, pairs=pairs, left_on="bucket_time", right_on="bucket_time", cols=["oi_roc_4h", "price_oi_corr_16"])
    oi_base = asof_join_pairwise(
        oi_base,
        mom.rename(columns={"momentum_10_15m": "momentum_now"}),
        pairs=pairs,
        left_on="bucket_time",
        right_on="bucket_time",
        cols=["momentum_now", "momentum_prev"],
    )
    oi_eval = oi_base.copy()
    oi_eval["ready"] = oi_eval[["oi_roc_4h", "price_oi_corr_16", "momentum_now", "momentum_prev"]].notna().all(axis=1)
    oi_eval["momentum_slope"] = oi_eval["momentum_now"] - oi_eval["momentum_prev"]
    oi_eval["oi_spike"] = oi_eval["oi_roc_4h"] > 0.15
    oi_eval["momentum_stalling"] = (oi_eval["momentum_now"] < 5.0) & (oi_eval["momentum_slope"] < 0.0)
    oi_eval["corr_collapse"] = oi_eval["price_oi_corr_16"] < 0.3
    oi_eval["pred"] = "none"
    oi_eval.loc[oi_eval["ready"] & oi_eval["oi_spike"] & (oi_eval["momentum_now"] > 10.0) & (~oi_eval["corr_collapse"]), "pred"] = "up"
    oi_eval.loc[oi_eval["ready"] & oi_eval["oi_spike"] & oi_eval["momentum_stalling"], "pred"] = "down"

    out = pd.concat(
        [
            summarize(ob_eval, "OB_Imbalance_Acceleration_3p", pairs),
            summarize(oi_eval, "OI_Price_Divergence_4h", pairs),
        ],
        ignore_index=True,
    )

    now = datetime.now(timezone.utc)
    out_dir = Path(__file__).resolve().parents[1] / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_json = out_dir / f"minimax_ob_oi_backtest_{stamp}.json"
    out_md = out_dir / f"minimax_ob_oi_backtest_{stamp}.md"
    payload = {
        "as_of_utc": iso_z(as_of),
        "days": int(args.days),
        "start_utc": iso_z(start),
        "pairs": pairs,
        "results": out.to_dict(orient="records"),
    }
    out_json.write_text(json.dumps(payload, indent=2))

    rows = [
        [
            r["indicator"],
            r["pair"],
            r["events"],
            r["ready"],
            r["triggered"],
            r["correct"],
            r["accuracy_pct"],
            r["coverage_pct"],
            r["up_triggers"],
            r["down_triggers"],
        ]
        for r in payload["results"]
    ]
    md = []
    md.append("# Minimax OB/OI Backtest")
    md.append("")
    md.append(f"- As-of UTC: `{payload['as_of_utc']}`")
    md.append(f"- Window days: `{payload['days']}`")
    md.append(f"- Start UTC: `{payload['start_utc']}`")
    md.append(f"- Pairs: `{', '.join(payload['pairs'])}`")
    md.append("")
    md.append("```text")
    md.append(
        table(
            ["indicator", "pair", "events", "ready", "triggered", "correct", "accuracy_pct", "coverage_pct", "up_triggers", "down_triggers"],
            rows,
        )
    )
    md.append("```")
    out_md.write_text("\n".join(md) + "\n")

    print(f"output_json={out_json}")
    print(f"output_md={out_md}")
    print()
    print(
        table(
            ["indicator", "pair", "events", "ready", "triggered", "correct", "accuracy_pct", "coverage_pct", "up_triggers", "down_triggers"],
            rows,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

