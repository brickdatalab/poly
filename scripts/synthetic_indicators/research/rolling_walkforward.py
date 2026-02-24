#!/usr/bin/env python3
"""Walk-forward evaluation of fixed codex rules on canonical dataset."""

from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pandas as pd

THIS_DIR = Path(__file__).resolve().parent
import sys

if str(THIS_DIR) not in sys.path:
    sys.path.append(str(THIS_DIR))

from common import db_url_from_env, psql_csv
from metrics import evaluate_threshold_rule


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Walk-forward fixed-rule evaluation")
    ap.add_argument("--dataset", required=True)
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD")
    ap.add_argument("--train-days", type=int, default=21)
    ap.add_argument("--test-days", type=int, default=7)
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


def main() -> None:
    args = parse_args()
    dataset_path = Path(args.dataset)
    if not dataset_path.exists():
        raise SystemExit(f"Dataset not found: {dataset_path}")

    if args.out_dir:
        out_dir = Path(args.out_dir)
    else:
        run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        out_dir = dataset_path.parent / f"walkforward_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    root = Path(__file__).resolve().parents[3]
    db_url = db_url_from_env(root)
    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]

    df = pd.read_csv(dataset_path, compression="gzip")
    if df.empty:
        raise SystemExit("Dataset is empty")

    df["bucket_time"] = pd.to_datetime(df["bucket_time"], utc=True, errors="coerce")
    df["value"] = pd.to_numeric(df["value"], errors="coerce")
    df["is_up"] = df["outcome"].eq("up")

    rules = _load_rules(db_url, pairs)
    if rules.empty:
        raise SystemExit("No rules found")

    t_min = df["bucket_time"].min().floor("D")
    t_max = df["bucket_time"].max().floor("D")
    total_days = int((t_max - t_min).days + 1)
    train_days = int(args.train_days)
    test_days = int(args.test_days)

    if total_days < (train_days + test_days + 1):
        # Auto-shrink window to avoid failing on shorter newly backfilled ranges.
        test_days = min(test_days, max(1, total_days // 3))
        train_days = max(1, total_days - test_days - 1)

    fold_rows = []
    for rule in rules.to_dict(orient="records"):
        g = df[(df["pair"] == rule["pair"]) & (df["config_id"] == rule["config_id"])].copy()
        if g.empty:
            continue

        cur = t_min + pd.Timedelta(days=train_days)
        while cur + pd.Timedelta(days=test_days) <= t_max + pd.Timedelta(days=1):
            test_start = cur
            test_end = cur + pd.Timedelta(days=test_days)

            te = g[(g["bucket_time"] >= test_start) & (g["bucket_time"] < test_end)]
            if te.empty:
                cur = cur + pd.Timedelta(days=args.test_days)
                continue

            res = evaluate_threshold_rule(
                te["value"].to_numpy(dtype=np.float64),
                te["is_up"].to_numpy(dtype=bool),
                str(rule["prediction"]),
                str(rule["operator"]),
                float(rule["threshold"]),
            )

            fold_rows.append(
                {
                    "rule_id": rule["rule_id"],
                    "pair": rule["pair"],
                    "config_id": rule["config_id"],
                    "prediction": rule["prediction"],
                    "operator": rule["operator"],
                    "threshold": float(rule["threshold"]),
                    "test_start": test_start,
                    "test_end": test_end,
                    "support_n": int(res["support_n"]),
                    "accuracy": float(res["accuracy"]),
                }
            )
            cur = cur + pd.Timedelta(days=test_days)

    folds = pd.DataFrame(fold_rows)
    if folds.empty:
        agg = pd.DataFrame(
            columns=[
                "rule_id",
                "pair",
                "config_id",
                "prediction",
                "operator",
                "threshold",
                "folds",
                "mean_accuracy",
                "min_accuracy",
                "max_accuracy",
                "avg_support",
                "min_support",
            ]
        )
    else:
        agg = (
            folds.groupby(["rule_id", "pair", "config_id", "prediction", "operator", "threshold"], as_index=False)
            .agg(
                folds=("accuracy", "count"),
                mean_accuracy=("accuracy", "mean"),
                min_accuracy=("accuracy", "min"),
                max_accuracy=("accuracy", "max"),
                avg_support=("support_n", "mean"),
                min_support=("support_n", "min"),
            )
            .sort_values(["pair", "config_id", "rule_id"])
        )

    summary = {
        "rules_evaluated": int(agg.shape[0]),
        "folds_total": int(folds.shape[0]),
        "rules_mean_acc_ge_60": int((agg["mean_accuracy"] >= 0.60).sum()) if not agg.empty else 0,
        "effective_train_days": train_days,
        "effective_test_days": test_days,
    }

    folds_csv = out_dir / "walkforward_folds.csv"
    agg_csv = out_dir / "walkforward_rule_summary.csv"
    summary_json = out_dir / "summary.json"
    report_md = out_dir / "REPORT.md"

    folds.to_csv(folds_csv, index=False)
    agg.to_csv(agg_csv, index=False)
    summary_json.write_text(json.dumps(summary, indent=2, default=str))

    lines = [
        "# Walk-Forward Evaluation",
        "",
        f"Rules evaluated: `{summary['rules_evaluated']}`",
        f"Total folds: `{summary['folds_total']}`",
        f"Rules with mean accuracy >=60%: `{summary['rules_mean_acc_ge_60']}`",
        "",
        "## Files",
        "",
        f"- `{folds_csv}`",
        f"- `{agg_csv}`",
        f"- `{summary_json}`",
    ]
    report_md.write_text("\n".join(lines) + "\n")
    print(str(out_dir))


if __name__ == "__main__":
    main()
