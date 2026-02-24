#!/usr/bin/env python3
"""Regime decomposition for synthetic codex rules.

Outputs per-rule performance across volatility/trend/liquidity/OI regimes and
recommended deployable situations under >=60% + CI/support gates.
"""

from __future__ import annotations

import argparse
import json
import os
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
    ap = argparse.ArgumentParser(description="Regime decomposition for codex rules")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--min-support-n", type=int, default=40)
    ap.add_argument("--min-regime-support-n", type=int, default=25)
    ap.add_argument("--out-dir", default=None)
    return ap.parse_args()


def _bucket3(s: pd.Series, labels: tuple[str, str, str]) -> pd.Series:
    s = pd.to_numeric(s, errors="coerce")
    q1 = s.quantile(1 / 3)
    q2 = s.quantile(2 / 3)

    def f(x: float) -> str:
        if pd.isna(x):
            return "unknown"
        if x <= q1:
            return labels[0]
        if x <= q2:
            return labels[1]
        return labels[2]

    return s.apply(f)


def _attach_regimes(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy()
    out["atr_pct"] = out["atr_14_15m"] / out["event_close"].replace(0, np.nan)
    out["trend_strength"] = (out["ema_9_15m"] - out["ema_21_15m"]).abs() / out["event_close"].replace(0, np.nan)
    out["liq_spread"] = out["spread_pct"].abs()
    out["oi_pressure_abs"] = out["funding_oi_pressure"].abs()

    out["vol_regime"] = (
        out.groupby("pair", group_keys=False)["atr_pct"]
        .apply(lambda s: _bucket3(s, ("vol_low", "vol_mid", "vol_high")))
        .astype(str)
    )
    out["trend_regime"] = (
        out.groupby("pair", group_keys=False)["trend_strength"]
        .apply(lambda s: _bucket3(s, ("trend_chop", "trend_mixed", "trend_strong")))
        .astype(str)
    )
    out["liquidity_regime"] = (
        out.groupby("pair", group_keys=False)["liq_spread"]
        .apply(lambda s: _bucket3(s, ("liq_tight", "liq_mid", "liq_wide")))
        .astype(str)
    )
    out["oi_regime"] = (
        out.groupby("pair", group_keys=False)["oi_pressure_abs"]
        .apply(lambda s: _bucket3(s, ("oi_calm", "oi_mid", "oi_stressed")))
        .astype(str)
    )
    out["choppy_market"] = (out["trend_regime"] == "trend_chop") & (out["vol_regime"] != "vol_high")
    return out


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


def _evaluate_rule(df: pd.DataFrame, rule: dict[str, Any]) -> tuple[dict[str, Any], pd.DataFrame]:
    pair = rule["pair"]
    config_id = rule["config_id"]
    operator = rule["operator"]
    threshold = float(rule["threshold"])
    prediction = rule["prediction"]

    g = df[(df["pair"] == pair) & (df["config_id"] == config_id)].copy()
    if g.empty:
        empty = {
            "rule_id": rule["rule_id"],
            "pair": pair,
            "config_id": config_id,
            "prediction": prediction,
            "operator": operator,
            "threshold": threshold,
            "support_n": 0,
            "accuracy": 0.0,
            "ci_low": 0.0,
            "ci_high": 0.0,
        }
        return empty, pd.DataFrame()

    vals = g["value"].to_numpy(dtype=np.float64)
    y = g["is_up"].to_numpy(dtype=bool)
    res = evaluate_threshold_rule(vals, y, prediction, operator, threshold)
    ci = wilson_ci(int(res["wins"]), int(res["support_n"]))

    if operator == ">=":
        mask = g["value"] >= threshold
    else:
        mask = g["value"] <= threshold
    tr = g.loc[mask].copy()
    tr["correct"] = np.where(prediction == "up", tr["is_up"], ~tr["is_up"])

    overall = {
        "rule_id": rule["rule_id"],
        "pair": pair,
        "config_id": config_id,
        "prediction": prediction,
        "operator": operator,
        "threshold": threshold,
        "support_n": int(res["support_n"]),
        "accuracy": float(res["accuracy"]),
        "ci_low": float(ci.low),
        "ci_high": float(ci.high),
        "active_now": str(rule.get("is_active", "")).lower() in {"t", "true", "1"},
    }
    return overall, tr


def _regime_breakdown(triggered: pd.DataFrame, rule_id: str) -> pd.DataFrame:
    if triggered.empty:
        return pd.DataFrame()

    dims = ["vol_regime", "trend_regime", "liquidity_regime", "oi_regime", "choppy_market"]
    rows: list[dict[str, Any]] = []
    for dim in dims:
        gb = triggered.groupby(dim, dropna=False)
        for bucket, gg in gb:
            n = int(len(gg))
            wins = int(gg["correct"].sum())
            acc = wins / n if n else 0.0
            ci = wilson_ci(wins, n)
            rows.append(
                {
                    "rule_id": rule_id,
                    "dimension": dim,
                    "bucket": str(bucket),
                    "support_n": n,
                    "wins": wins,
                    "accuracy": acc,
                    "ci_low": ci.low,
                    "ci_high": ci.high,
                }
            )
    return pd.DataFrame(rows)


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = dataset_path.parent / f"regimes_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[3]
    db_url = db_url_from_env(root)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    df = pd.read_csv(dataset_path, compression="gzip")
    if df.empty:
        raise SystemExit("Dataset is empty")

    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["is_up"] = df["outcome"].eq("up")
    df = _attach_regimes(df)

    rules = _load_rules(db_url, pairs)
    if rules.empty:
        raise SystemExit("No codex rules found for requested pairs")

    overall_rows: list[dict[str, Any]] = []
    regime_parts: list[pd.DataFrame] = []

    for r in rules.to_dict(orient="records"):
        overall, triggered = _evaluate_rule(df, r)
        overall_rows.append(overall)
        regime_parts.append(_regime_breakdown(triggered, overall["rule_id"]))

    overall_df = pd.DataFrame(overall_rows).sort_values(["pair", "config_id", "rule_id"])
    regime_df = pd.concat(regime_parts, ignore_index=True) if regime_parts else pd.DataFrame()

    if not regime_df.empty:
        deployable = regime_df[
            (regime_df["accuracy"] >= 0.60)
            & (regime_df["ci_low"] >= 0.55)
            & (regime_df["support_n"] >= args.min_regime_support_n)
        ].copy()
        deployable = deployable.sort_values(["rule_id", "accuracy", "support_n"], ascending=[True, False, False])
        deployable_best = deployable.groupby("rule_id", as_index=False).head(1)
    else:
        deployable_best = pd.DataFrame()

    overall_df["passes_overall_gate"] = (
        (overall_df["accuracy"] >= 0.60)
        & (overall_df["ci_low"] >= 0.55)
        & (overall_df["support_n"] >= args.min_support_n)
    )

    overall_csv = out_dir / "rule_overall_metrics.csv"
    regime_csv = out_dir / "rule_regime_metrics.csv"
    best_csv = out_dir / "rule_best_regime_situations.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "REPORT.md"

    overall_df.to_csv(overall_csv, index=False)
    regime_df.to_csv(regime_csv, index=False)
    deployable_best.to_csv(best_csv, index=False)

    summary = {
        "rules_total": int(len(overall_df)),
        "rules_passing_overall_gate": int(overall_df["passes_overall_gate"].sum()),
        "rules_with_deployable_regime": int(deployable_best["rule_id"].nunique()) if not deployable_best.empty else 0,
    }
    summary_json.write_text(json.dumps(summary, indent=2))

    lines = [
        "# Regime Decomposition",
        "",
        f"Rules evaluated: `{summary['rules_total']}`",
        f"Rules passing overall gate: `{summary['rules_passing_overall_gate']}`",
        f"Rules with deployable regime situations: `{summary['rules_with_deployable_regime']}`",
        "",
        "## Files",
        "",
        f"- `{overall_csv}`",
        f"- `{regime_csv}`",
        f"- `{best_csv}`",
        f"- `{summary_json}`",
    ]

    report_md.write_text("\n".join(lines) + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
