#!/usr/bin/env python3
from __future__ import annotations

import argparse
import datetime as dt
import json
import math
import os
import subprocess
from dataclasses import dataclass
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd
from joblib import dump
from sklearn.calibration import CalibratedClassifierCV
from sklearn.ensemble import HistGradientBoostingClassifier
from sklearn.metrics import accuracy_score, confusion_matrix

# Reuse our psql JSON helper (no MCP).
import sys

ROOT = Path("/Users/vitolo/Desktop/projects/poly")
SCRIPTS_DIR = ROOT / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from training_schema_review.db import (  # noqa: E402
    PsqlSettings,
    build_db_url,
    load_dotenv,
    require_env,
)
from training_schema_review.queries import sql_list_columns  # noqa: E402
from training_schema_review.time_utils import utc_slug  # noqa: E402


OUT_ROOT = ROOT / "scripts" / "output" / "btc_1h_baseline"
REVIEW_RUNS_DIR = ROOT / "scripts" / "training_schema_review" / "runs"


def _utc_date(s: str) -> dt.date:
    # s like 2026-02-01T16:00:00+00:00
    return dt.datetime.fromisoformat(s.replace("Z", "+00:00")).date()


def list_cols(schema: str, rel: str, settings: PsqlSettings) -> list[dict[str, Any]]:
    # Use a lightweight JSON query.
    load_dotenv()
    db_url = build_db_url()
    db_password = require_env("SUPABASE_DB_PASSWORD")
    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")
    sql = (
        f"set statement_timeout='{settings.statement_timeout_s}s';\n"
        f"set work_mem='{settings.work_mem_mb}MB';\n"
        f"set max_parallel_workers_per_gather={settings.max_parallel_workers_per_gather};\n"
        "set jit=on;\n"
        + sql_list_columns(schema, rel).strip()
        + "\n"
    )
    out = subprocess.check_output(
        ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-t", "-A", "-c", sql],
        env=env,
        stderr=subprocess.STDOUT,
        timeout=max(settings.statement_timeout_s + 30, 90),
    )
    s = out.decode("utf-8", errors="replace").strip()
    return [] if not s else json.loads(s)


def intersection_features(
    *,
    training_table: str,
    indicators_view: str,
    settings: PsqlSettings,
) -> list[str]:
    ts_exclude = {"open_time", "bucket_time", "ts"}
    key_exclude = {"symbol", "pair"}
    label_like = {
        "label",
        "next_label",
        "pct_change",
        "next_pct_change",
        "outcome",
        "event_end",
        "event_start",
        "start_price",
        "end_price",
        "price_change",
        "price_change_pct",
        "label_version",
    }

    tr_schema, tr_rel = training_table.split(".", 1)
    in_schema, in_rel = indicators_view.split(".", 1)
    tr_cols = list_cols(tr_schema, tr_rel, settings)
    in_cols = list_cols(in_schema, in_rel, settings)

    tr = {c["name"]: c for c in tr_cols}
    inn = {c["name"]: c for c in in_cols}

    common = sorted(set(tr.keys()) & set(inn.keys()))

    numeric_types = {
        "double precision",
        "numeric",
        "real",
        "integer",
        "bigint",
        "smallint",
    }

    feats: list[str] = []
    for c in common:
        if c in ts_exclude or c in key_exclude or c in label_like:
            continue
        if tr[c]["data_type"] in numeric_types and inn[c]["data_type"] in numeric_types:
            feats.append(c)

    # Ensure core OHLCV is present (these exist in both and are useful baseline predictors).
    for core in ["open", "high", "low", "close", "volume"]:
        if core in common and core not in feats:
            feats.append(core)

    return feats


def sql_training_dataset(*, base_features: list[str], n_lags: int) -> tuple[str, list[str]]:
    # Use lag(feature) so that at bucket_time t, features reflect last closed hour (t-1h).
    have_open = "open" in base_features
    cols_no_open = [c for c in base_features if c != "open"]

    lag_selects: list[str] = []
    feature_names: list[str] = []

    # Filter out the first row (and any row without a prior hour).
    lag_selects.append("lag(open_cur, 1) over w as _lag_open_1")

    def add_lags(source_expr: str, out_base: str) -> None:
        for k in range(1, n_lags + 1):
            out_name = f"{out_base}_lag{k}"
            lag_selects.append(f"lag({source_expr}, {k}) over w as {out_name}")
            feature_names.append(out_name)

    if have_open:
        add_lags("open_cur", "open")
    for c in cols_no_open:
        add_lags(c, c)

    selects_sql = ",\n        ".join(lag_selects) if lag_selects else "null::float8 as _dummy"
    out_cols_sql = ", ".join(feature_names) if feature_names else "null::float8 as _dummy"
    base_cols_sql = ", ".join(cols_no_open) if cols_no_open else "open as _dummy"

    sql = f"""
    with base as (
      select
        open_time as bucket_time,
        open as open_cur,
        {base_cols_sql}
      from training.unified_1h
      where symbol = 'BTC'
      order by open_time
    ),
    x as (
      select
        bucket_time,
        open_cur,
        lead(open_cur) over w as next_open,
        {selects_sql}
      from base
      window w as (order by bucket_time)
    )
    select
      bucket_time,
      case when next_open > open_cur then 1 else 0 end as y_up,
      (next_open - open_cur) / nullif(open_cur, 0) as y_return,
      {out_cols_sql}
    from x
    where next_open is not null
      and _lag_open_1 is not null
    order by bucket_time
    """
    return sql, feature_names


def sql_indicators_dataset(*, base_features: list[str], n_lags: int, start_utc: str) -> tuple[str, list[str]]:
    have_open = "open" in base_features
    cols_no_open = [c for c in base_features if c != "open"]

    lag_selects: list[str] = []
    feature_names: list[str] = []

    lag_selects.append("lag(open_cur, 1) over w as _lag_open_1")

    def add_lags(source_expr: str, out_base: str) -> None:
        for k in range(1, n_lags + 1):
            out_name = f"{out_base}_lag{k}"
            lag_selects.append(f"lag({source_expr}, {k}) over w as {out_name}")
            feature_names.append(out_name)

    if have_open:
        add_lags("open_cur", "open")
    for c in cols_no_open:
        add_lags(c, c)

    selects_sql = ",\n        ".join(lag_selects) if lag_selects else "null::float8 as _dummy"
    out_cols_sql = ", ".join(feature_names) if feature_names else "null::float8 as _dummy"
    base_cols_sql = ", ".join(cols_no_open) if cols_no_open else "open as _dummy"

    sql = f"""
    with base as (
      select
        bucket_time,
        open as open_cur,
        {base_cols_sql}
      from indicators.v_model_1h
      where pair = 'BTC-USD'
        and bucket_time >= '{start_utc}'::timestamptz
      order by bucket_time
    ),
    x as (
      select
        bucket_time,
        open_cur,
        lead(open_cur) over w as next_open,
        {selects_sql}
      from base
      window w as (order by bucket_time)
    )
    select
      bucket_time,
      case when next_open > open_cur then 1 else 0 end as y_up,
      (next_open - open_cur) / nullif(open_cur, 0) as y_return,
      {out_cols_sql}
    from x
    where next_open is not null
      and _lag_open_1 is not null
    order by bucket_time
    """
    return sql, feature_names


def psql_copy_csv(*, sql: str, out_path: Path, settings: PsqlSettings) -> None:
    load_dotenv()
    db_url = build_db_url()
    db_password = require_env("SUPABASE_DB_PASSWORD")

    env = os.environ.copy()
    env["PGPASSWORD"] = db_password
    env.setdefault("PGSSLMODE", "require")

    out_path.parent.mkdir(parents=True, exist_ok=True)

    # Use server-side COPY TO STDOUT and stream directly to a local file.
    cmd_sql = (
        f"set statement_timeout = '{settings.statement_timeout_s}s';\n"
        f"set work_mem = '{settings.work_mem_mb}MB';\n"
        f"set max_parallel_workers_per_gather = {settings.max_parallel_workers_per_gather};\n"
        "set jit = on;\n"
        f"copy ({sql.strip()}) to stdout with (format csv, header true);\n"
    )
    timeout_s = max(settings.statement_timeout_s + 60, 180)
    with out_path.open("wb") as f:
        p = subprocess.Popen(
            ["psql", "-X", db_url, "-v", "ON_ERROR_STOP=1", "-q", "-c", cmd_sql],
            env=env,
            stdout=f,
            stderr=subprocess.PIPE,
        )
        try:
            _, err = p.communicate(timeout=timeout_s)
        except subprocess.TimeoutExpired:
            p.kill()
            raise RuntimeError(f"psql timed out after {timeout_s}s")
        if p.returncode != 0:
            raise RuntimeError(err.decode("utf-8", errors="replace"))


@dataclass(frozen=True)
class ThresholdResult:
    tau: float
    n_pred: int
    coverage: float
    acc: float
    avg_pred_per_day: float
    min_pred_per_day: int
    days: int


def threshold_sweep(
    *,
    p_up: np.ndarray,
    y: np.ndarray,
    ts: pd.Series,
    min_pred_per_day: int,
) -> list[ThresholdResult]:
    assert len(p_up) == len(y) == len(ts)
    df = pd.DataFrame({"ts": pd.to_datetime(ts, utc=True), "p": p_up, "y": y})
    df["day"] = df["ts"].dt.date

    out: list[ThresholdResult] = []
    for tau in np.round(np.arange(0.50, 0.995, 0.005), 3):
        pred = np.full(len(df), -1, dtype=int)
        pred[df["p"].to_numpy() >= tau] = 1
        pred[df["p"].to_numpy() <= (1.0 - tau)] = 0

        mask = pred != -1
        n_pred = int(mask.sum())
        if n_pred == 0:
            continue

        acc = float(accuracy_score(df["y"].to_numpy()[mask], pred[mask]))
        coverage = float(n_pred / len(df))

        by_day = df.loc[mask].groupby("day").size()
        days = int(df["day"].nunique())
        # Include days with 0 predictions.
        by_day_full = by_day.reindex(sorted(df["day"].unique()), fill_value=0)
        avg = float(by_day_full.mean())
        mn = int(by_day_full.min())

        out.append(
            ThresholdResult(
                tau=float(tau),
                n_pred=n_pred,
                coverage=coverage,
                acc=acc,
                avg_pred_per_day=avg,
                min_pred_per_day=mn,
                days=days,
            )
        )
    return out


def pick_threshold(
    sweep: list[ThresholdResult],
    *,
    min_avg_pred_per_day: int,
    target_acc: float,
) -> ThresholdResult:
    # Prefer: meet target acc AND meet avg predictions/day constraint, maximize acc, then maximize avg preds/day.
    feasible = [r for r in sweep if r.avg_pred_per_day >= min_avg_pred_per_day and r.acc >= target_acc]
    if feasible:
        feasible.sort(key=lambda r: (r.acc, r.avg_pred_per_day, r.coverage), reverse=True)
        return feasible[0]

    # Else: meet avg predictions/day, maximize acc.
    feasible2 = [r for r in sweep if r.avg_pred_per_day >= min_avg_pred_per_day]
    if feasible2:
        feasible2.sort(key=lambda r: (r.acc, r.avg_pred_per_day, r.coverage), reverse=True)
        return feasible2[0]

    # Else: maximize acc regardless (report will show it didn't meet the trading cadence requirement).
    sweep.sort(key=lambda r: (r.acc, r.avg_pred_per_day, r.coverage), reverse=True)
    return sweep[0]


def eval_with_tau(p_up: np.ndarray, y: np.ndarray, tau: float) -> dict[str, Any]:
    pred = np.full(len(y), -1, dtype=int)
    pred[p_up >= tau] = 1
    pred[p_up <= (1.0 - tau)] = 0
    mask = pred != -1
    if mask.sum() == 0:
        return {"tau": tau, "n_pred": 0, "acc": None, "cm": None}
    acc = float(accuracy_score(y[mask], pred[mask]))
    cm = confusion_matrix(y[mask], pred[mask]).tolist()
    return {"tau": tau, "n_pred": int(mask.sum()), "coverage": float(mask.mean()), "acc": acc, "cm": cm}


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--start-indicators-utc", default="2026-01-02 00:00:00+00")
    ap.add_argument("--min-preds-per-day", type=int, default=10)
    ap.add_argument("--target-acc", type=float, default=0.70)
    ap.add_argument("--val-frac", type=float, default=0.2)
    ap.add_argument("--n-lags", type=int, default=1, help="How many 1h lags per feature to include (>=1).")
    ap.add_argument("--jobs", type=int, default=12)
    ap.add_argument("--statement-timeout-s", type=int, default=1200)
    ap.add_argument("--work-mem-mb", type=int, default=256)
    ap.add_argument("--parallel-workers", type=int, default=4)
    ap.add_argument("--exclude-flagged-features", action=argparse.BooleanOptionalAction, default=True)
    args = ap.parse_args()

    run_dir = OUT_ROOT / utc_slug()
    run_dir.mkdir(parents=True, exist_ok=True)

    settings = PsqlSettings(
        statement_timeout_s=args.statement_timeout_s,
        work_mem_mb=args.work_mem_mb,
        max_parallel_workers_per_gather=args.parallel_workers,
    )

    feats = intersection_features(
        training_table="training.unified_1h",
        indicators_view="indicators.v_model_1h",
        settings=settings,
    )
    if not feats:
        raise RuntimeError("No intersection features found between training.unified_1h and indicators.v_model_1h")

    if args.exclude_flagged_features and REVIEW_RUNS_DIR.exists():
        # Drop any feature that the review suite flagged as anomalous in any table.
        runs = sorted([p for p in REVIEW_RUNS_DIR.iterdir() if p.is_dir()], key=lambda p: p.name)
        if runs:
            latest = runs[-1]
            anom = latest / "json" / "indicator_anomalies.json"
            if anom.exists():
                flagged = {f["feature"] for f in json.loads(anom.read_text(encoding="utf-8")).get("flags", [])}
                feats = [c for c in feats if c not in flagged]
                if not feats:
                    raise RuntimeError("All intersection features were flagged; cannot train.")

    if args.n_lags < 1:
        raise RuntimeError("--n-lags must be >= 1")

    # Pull datasets via \copy (fast, avoids huge JSON parsing).
    tr_sql, lag_feats = sql_training_dataset(base_features=feats, n_lags=int(args.n_lags))
    te_sql, lag_feats2 = sql_indicators_dataset(base_features=feats, n_lags=int(args.n_lags), start_utc=args.start_indicators_utc)
    if lag_feats != lag_feats2:
        raise RuntimeError("Train/test feature name mismatch (unexpected).")

    tr_csv = run_dir / "training_dataset.csv"
    te_csv = run_dir / "indicators_dataset.csv"
    psql_copy_csv(sql=tr_sql, out_path=tr_csv, settings=settings)
    psql_copy_csv(sql=te_sql, out_path=te_csv, settings=settings)

    tr_df = pd.read_csv(tr_csv)
    te_df = pd.read_csv(te_csv)

    # Ensure types.
    feats_used = lag_feats
    for df in (tr_df, te_df):
        df["bucket_time"] = pd.to_datetime(df["bucket_time"], utc=True)
        df["y_up"] = df["y_up"].astype(int)
        df["y_return"] = df["y_return"].astype(float)
        for c in feats_used:
            df[c] = df[c].astype(float)

    tr_df = tr_df.sort_values("bucket_time").reset_index(drop=True)

    # Time split
    n = len(tr_df)
    n_val = max(1000, int(math.floor(n * float(args.val_frac))))
    split = n - n_val
    train_df = tr_df.iloc[:split].copy()
    val_df = tr_df.iloc[split:].copy()

    X_train = train_df[feats_used].to_numpy()
    y_train = train_df["y_up"].to_numpy()
    X_val = val_df[feats_used].to_numpy()
    y_val = val_df["y_up"].to_numpy()

    # Base model (strong tabular baseline).
    base = HistGradientBoostingClassifier(
        learning_rate=0.05,
        max_depth=4,
        max_iter=600,
        l2_regularization=1e-2,
        random_state=42,
    )

    # Time-respecting calibration:
    # - Fit base on the earlier portion of train
    # - Calibrate on the last chunk of train (still strictly before val)
    n_train = len(train_df)
    n_cal = max(2000, int(0.15 * n_train))
    split_cal = n_train - n_cal
    X_sub, y_sub = X_train[:split_cal], y_train[:split_cal]
    X_cal, y_cal = X_train[split_cal:], y_train[split_cal:]

    base.fit(X_sub, y_sub)
    cal = CalibratedClassifierCV(base, method="sigmoid", cv="prefit")
    cal.fit(X_cal, y_cal)

    p_val = cal.predict_proba(X_val)[:, 1]
    sweep = threshold_sweep(
        p_up=p_val,
        y=y_val,
        ts=val_df["bucket_time"],
        min_pred_per_day=int(args.min_preds_per_day),
    )
    if not sweep:
        raise RuntimeError("Threshold sweep produced no predictions; something is wrong with model probabilities.")

    chosen = pick_threshold(sweep, min_avg_pred_per_day=int(args.min_preds_per_day), target_acc=float(args.target_acc))

    # Final eval
    val_metrics = eval_with_tau(p_val, y_val, chosen.tau)

    # Save sweep so we can see the accuracy/coverage tradeoff.
    sweep_df = pd.DataFrame([r.__dict__ for r in sweep]).sort_values(["acc", "avg_pred_per_day"], ascending=False)
    sweep_df.to_csv(run_dir / "val_threshold_sweep.csv", index=False)
    best_any = max(sweep, key=lambda r: r.acc)
    best_meeting_cadence = max([r for r in sweep if r.avg_pred_per_day >= int(args.min_preds_per_day)] or sweep, key=lambda r: r.acc)

    # Evaluate on indicators dataset (backtest-like)
    X_te = te_df[feats_used].to_numpy()
    y_te = te_df["y_up"].to_numpy()
    p_te = cal.predict_proba(X_te)[:, 1]
    te_metrics = eval_with_tau(p_te, y_te, chosen.tau)

    # Daily prediction counts on indicators
    te_pred = np.full(len(te_df), -1, dtype=int)
    te_pred[p_te >= chosen.tau] = 1
    te_pred[p_te <= (1.0 - chosen.tau)] = 0
    te_out = te_df[["bucket_time", "y_up", "y_return"]].copy()
    te_out["p_up"] = p_te
    te_out["pred"] = te_pred
    te_out["is_pred"] = te_out["pred"] != -1
    te_out["correct"] = (te_out["pred"] == te_out["y_up"]) & te_out["is_pred"]
    te_out["day"] = te_out["bucket_time"].dt.date
    daily = (
        te_out.groupby("day")
        .agg(n=("pred", "size"), n_pred=("is_pred", "sum"), acc=("correct", "mean"))
        .reset_index()
    )

    # Persist artifacts
    (run_dir / "features.json").write_text(json.dumps({"base_features": feats, "features_used": feats_used}, indent=2) + "\n", encoding="utf-8")
    dump(cal, run_dir / "model.joblib")

    te_out.to_csv(run_dir / "indicators_predictions.csv", index=False)
    daily.to_csv(run_dir / "indicators_daily.csv", index=False)

    report = {
        "run_dir": str(run_dir),
        "feature_count": len(feats_used),
        "n_lags": int(args.n_lags),
        "train_rows": len(train_df),
        "val_rows": len(val_df),
        "indicators_rows": len(te_df),
        "train_range": [train_df["bucket_time"].min().isoformat(), train_df["bucket_time"].max().isoformat()],
        "val_range": [val_df["bucket_time"].min().isoformat(), val_df["bucket_time"].max().isoformat()],
        "indicators_range": [te_df["bucket_time"].min().isoformat(), te_df["bucket_time"].max().isoformat()],
        "chosen_threshold": chosen.__dict__,
        "best_any_threshold": best_any.__dict__,
        "best_threshold_meeting_min_preds_per_day": best_meeting_cadence.__dict__,
        "val_metrics": val_metrics,
        "indicators_metrics": te_metrics,
        "min_preds_per_day_target": int(args.min_preds_per_day),
        "target_acc": float(args.target_acc),
        "start_indicators_utc": args.start_indicators_utc,
    }
    (run_dir / "report.json").write_text(json.dumps(report, indent=2, sort_keys=True) + "\n", encoding="utf-8")

    # Human summary
    md: list[str] = []
    md.append("# BTC 1H Base Model")
    md.append("")
    md.append(f"Run: `{run_dir}`")
    md.append("")
    md.append(f"- features: {len(feats_used)} (intersection features with {args.n_lags} lag(s) each)")
    md.append(f"- train rows: {len(train_df)} ({report['train_range'][0]} -> {report['train_range'][1]})")
    md.append(f"- val rows: {len(val_df)} ({report['val_range'][0]} -> {report['val_range'][1]})")
    md.append(f"- indicators backtest rows: {len(te_df)} ({report['indicators_range'][0]} -> {report['indicators_range'][1]})")
    md.append("")
    md.append("## Threshold")
    md.append(f"- tau: `{chosen.tau}`")
    md.append(f"- val acc on predictions: `{val_metrics['acc']}`")
    md.append(f"- val coverage: `{val_metrics.get('coverage')}` predictions `{val_metrics['n_pred']}`")
    md.append(f"- val avg preds/day: `{chosen.avg_pred_per_day}` (min `{chosen.min_pred_per_day}` over `{chosen.days}` days)")
    md.append("")
    md.append("## Indicators Backtest")
    md.append(f"- acc on predictions: `{te_metrics['acc']}`")
    md.append(f"- coverage: `{te_metrics.get('coverage')}` predictions `{te_metrics['n_pred']}`")
    md.append("")
    md.append("## Files")
    md.append(f"- `{run_dir / 'report.json'}`")
    md.append(f"- `{run_dir / 'model.joblib'}`")
    md.append(f"- `{run_dir / 'features.json'}`")
    md.append(f"- `{run_dir / 'indicators_predictions.csv'}`")
    md.append(f"- `{run_dir / 'indicators_daily.csv'}`")
    (run_dir / "REPORT.md").write_text("\n".join(md).rstrip() + "\n", encoding="utf-8")

    print(str(run_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
