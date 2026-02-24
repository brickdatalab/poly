#!/usr/bin/env python3
"""Support decay and stability diagnostics for codex rules."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
import sys

if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from common import db_url_from_env, psql_csv
from metrics import evaluate_threshold_rule, wilson_ci


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Support decay diagnostics")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--min-support-n", type=int, default=40)
    ap.add_argument("--out-dir", default=None)
    return ap.parse_args()


def _load_rules(db_url: str, pairs: list[str]) -> pd.DataFrame:
    pair_sql = ", ".join(f"'{p}'" for p in pairs)
    rows = psql_csv(
        db_url,
        f"""
        select rule_id, pair, config_id, operator, threshold::float8 as threshold,
               prediction, is_active
        from indicators.codex_signal_rules
        where pair in ({pair_sql})
        order by pair, config_id, rule_id
        """,
    )
    return pd.DataFrame(rows)


def _attach_chop(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["atr_pct"] = out["atr_14_15m"] / out["event_close"].replace(0, np.nan)
    out["trend_strength"] = (out["ema_9_15m"] - out["ema_21_15m"]).abs() / out["event_close"].replace(0, np.nan)
    out["vol_q33"] = out.groupby("pair")["atr_pct"].transform(lambda s: s.quantile(0.33))
    out["vol_q66"] = out.groupby("pair")["atr_pct"].transform(lambda s: s.quantile(0.66))
    out["trend_q33"] = out.groupby("pair")["trend_strength"].transform(lambda s: s.quantile(0.33))
    out["choppy_market"] = (out["trend_strength"] <= out["trend_q33"]) & (out["atr_pct"] <= out["vol_q66"])
    return out


def _evaluate_rule_series(df: pd.DataFrame, rule: dict[str, Any]) -> tuple[pd.DataFrame, dict[str, Any]]:
    g = df[(df["pair"] == rule["pair"]) & (df["config_id"] == rule["config_id"])].copy()
    if g.empty:
        return pd.DataFrame(), {
            "rule_id": rule["rule_id"],
            "pair": rule["pair"],
            "config_id": rule["config_id"],
            "support_n": 0,
            "accuracy": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "choppy_support_n": 0,
            "choppy_accuracy": 0.0,
            "weekly_acc_slope": 0.0,
            "mean_daily_support": 0.0,
            "max_loss_streak": 0,
            "active_now": str(rule.get("is_active", "")).lower() in {"t", "true", "1"},
        }

    thr = float(rule["threshold"])
    if rule["operator"] == ">=":
        mask = g["value"] >= thr
    else:
        mask = g["value"] <= thr

    tr = g.loc[mask].copy()
    if tr.empty:
        return tr, {
            "rule_id": rule["rule_id"],
            "pair": rule["pair"],
            "config_id": rule["config_id"],
            "support_n": 0,
            "accuracy": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
            "choppy_support_n": 0,
            "choppy_accuracy": 0.0,
            "weekly_acc_slope": 0.0,
            "mean_daily_support": 0.0,
            "max_loss_streak": 0,
            "active_now": str(rule.get("is_active", "")).lower() in {"t", "true", "1"},
        }

    tr["correct"] = np.where(rule["prediction"] == "up", tr["is_up"], ~tr["is_up"]).astype(int)
    tr["bucket_time"] = pd.to_datetime(tr["bucket_time"], utc=True, errors="coerce")
    tr["day"] = tr["bucket_time"].dt.floor("D")
    tr["week"] = tr["bucket_time"].dt.to_period("W").astype(str)

    support_n = int(len(tr))
    wins = int(tr["correct"].sum())
    accuracy = wins / support_n if support_n else 0.0
    ci = wilson_ci(wins, support_n)

    ch = tr.loc[tr["choppy_market"]]
    ch_n = int(len(ch))
    ch_acc = float(ch["correct"].mean()) if ch_n else 0.0

    daily = tr.groupby("day")["correct"].agg(["count", "mean"]).reset_index()
    mean_daily_support = float(daily["count"].mean()) if not daily.empty else 0.0

    weekly = tr.groupby("week")["correct"].mean().reset_index(drop=True)
    if len(weekly) >= 3:
        x = np.arange(len(weekly), dtype=np.float64)
        y = weekly.to_numpy(dtype=np.float64)
        slope = float(np.polyfit(x, y, 1)[0])
    else:
        slope = 0.0

    max_loss_streak = 0
    curr = 0
    for c in tr.sort_values("bucket_time")["correct"].tolist():
        if c == 0:
            curr += 1
            max_loss_streak = max(max_loss_streak, curr)
        else:
            curr = 0

    metrics = {
        "rule_id": rule["rule_id"],
        "pair": rule["pair"],
        "config_id": rule["config_id"],
        "prediction": rule["prediction"],
        "operator": rule["operator"],
        "threshold": thr,
        "support_n": support_n,
        "accuracy": accuracy,
        "ci_low": ci.low,
        "ci_high": ci.high,
        "choppy_support_n": ch_n,
        "choppy_accuracy": ch_acc,
        "weekly_acc_slope": slope,
        "mean_daily_support": mean_daily_support,
        "max_loss_streak": int(max_loss_streak),
        "active_now": str(rule.get("is_active", "")).lower() in {"t", "true", "1"},
    }
    return tr, metrics


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = dataset_path.parent / f"decay_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[3]
    db_url = db_url_from_env(root)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    df = pd.read_csv(dataset_path, compression="gzip")
    if df.empty:
        raise SystemExit("Dataset is empty")

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["is_up"] = df["outcome"].eq("up")
    df = _attach_chop(df)

    rules = _load_rules(db_url, pairs)
    if rules.empty:
        raise SystemExit("No rules for selected pairs")

    metrics_rows: list[dict[str, Any]] = []
    daily_rows: list[dict[str, Any]] = []

    for rule in rules.to_dict(orient="records"):
        tr, metrics = _evaluate_rule_series(df, rule)
        metrics_rows.append(metrics)
        if not tr.empty:
            g = tr.groupby(tr["bucket_time"].dt.floor("D"))["correct"].agg(["count", "mean"]).reset_index()
            g.columns = ["day", "support_n", "accuracy"]
            g["rule_id"] = metrics["rule_id"]
            g["pair"] = metrics["pair"]
            g["config_id"] = metrics["config_id"]
            daily_rows.extend(g.to_dict(orient="records"))

    mdf = pd.DataFrame(metrics_rows).sort_values(["pair", "config_id", "rule_id"])
    ddf = pd.DataFrame(daily_rows)

    # Strategy gate used for optional production activation updates.
    mdf["recommended_active"] = (
        (mdf["accuracy"] >= 0.60)
        & (mdf["ci_low"] >= 0.55)
        & (mdf["support_n"] >= args.min_support_n)
        & ((mdf["choppy_support_n"] < 20) | (mdf["choppy_accuracy"] >= 0.55))
        & (mdf["weekly_acc_slope"] >= -0.03)
        & (mdf["max_loss_streak"] <= 8)
    )

    summary = {
        "rules_total": int(len(mdf)),
        "rules_recommended_active": int(mdf["recommended_active"].sum()),
        "rules_recommended_inactive": int((~mdf["recommended_active"]).sum()),
    }

    metrics_csv = out_dir / "rule_stability_metrics.csv"
    daily_csv = out_dir / "rule_daily_accuracy.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "REPORT.md"

    mdf.to_csv(metrics_csv, index=False)
    ddf.to_csv(daily_csv, index=False)
    summary_json.write_text(json.dumps(summary, indent=2))

    lines = [
        "# Support Decay Diagnostics",
        "",
        f"Rules total: `{summary['rules_total']}`",
        f"Recommended active: `{summary['rules_recommended_active']}`",
        f"Recommended inactive: `{summary['rules_recommended_inactive']}`",
        "",
        "## Files",
        "",
        f"- `{metrics_csv}`",
        f"- `{daily_csv}`",
        f"- `{summary_json}`",
    ]
    report_md.write_text("\n".join(lines) + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
