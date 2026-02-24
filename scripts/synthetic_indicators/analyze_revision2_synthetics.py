#!/usr/bin/env python3
"""Revision 2 synthetic indicator evaluation with strict t0-1 indexing in SQL."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PAIRS_DEFAULT = ["BTC-USD", "ETH-USD", "SOL-USD"]
START_DEFAULT = "2026-01-22T00:00:00Z"


@dataclass
class FeatureMetrics:
    feature: str
    ic: float
    ic_abs: float
    top_quintile_win_rate: float
    max_drawdown: float
    regime_trending_ic: float
    regime_trending_n: int
    regime_choppy_ic: float
    regime_choppy_n: int
    regime_ic_spread: float
    regime_stability: str
    target_ic_pass: bool


def compute_aroon_pvt_confidence(aroon_osc_t1: float, pvt_t1: float, pvt_t2: float) -> float:
    pvt_confirm = float(np.sign(pvt_t1 - pvt_t2))
    return float(((aroon_osc_t1 / 100.0) + (pvt_confirm * 0.5)) * 1.5)


def compute_adx_roc_regime_filter(adx_t1: float, plus_di_t1: float, minus_di_t1: float, roc_t1: float) -> float:
    if adx_t1 > 25.0:
        base = roc_t1
    elif adx_t1 < 20.0:
        base = -roc_t1
    else:
        # Neutral (20-25): keep base momentum unchanged.
        base = roc_t1
    di_spread = (plus_di_t1 - minus_di_t1) / 100.0
    return float(base + (di_spread * 10.0))


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


def db_url_from_env(root: Path) -> str:
    db_url = load_env(root).get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


def psql_csv(db_url: str, sql: str) -> list[dict[str, str]]:
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-F", ",", "--csv", "-c", sql],
        text=True,
    )
    return list(csv.DictReader(out.splitlines()))


def psql_exec(db_url: str, sql: str) -> None:
    subprocess.check_call(["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-c", sql])


def psql_script(db_url: str, script: str) -> None:
    subprocess.run(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off"],
        input=script,
        text=True,
        check=True,
    )


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Analyze Revision 2 synthetic indicators")
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default="now")
    ap.add_argument("--pairs", default=",".join(PAIRS_DEFAULT))
    ap.add_argument("--out", default="")
    ap.add_argument("--write-db-table", action="store_true", default=True)
    return ap.parse_args()


def _pair_sql(pairs: list[str]) -> str:
    return ", ".join(f"'{p}'" for p in pairs)


def _end_expr(end_ts: str) -> str:
    if end_ts.lower() == "now":
        return "date_trunc('minute', now())"
    return f"'{end_ts}'::timestamptz"


def build_revision2_dataset_sql(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    pair_sql = _pair_sql(pairs)
    end_expr = _end_expr(end_ts)
    return f"""
with base as (
  select
    pair as asset,
    bucket_time as timestamp,
    close::float8 as close,
    aroon_25_up::float8 as aroon_25_up,
    aroon_25_down::float8 as aroon_25_down,
    aroon_25_osc::float8 as aroon_25_osc,
    pvt_50::float8 as pvt_50,
    roc_9::float8 as roc_9,
    adx_20::float8 as adx_20,
    adx_20_plus_di::float8 as adx_20_plus_di,
    adx_20_minus_di::float8 as adx_20_minus_di,
    adx_14::float8 as adx_14
  from indicators.v_model_15m
  where pair in ({pair_sql})
    and bucket_time >= '{start_ts}'::timestamptz - interval '4 hours'
    and bucket_time <= {end_expr} + interval '30 minutes'
),
lagged as (
  select
    asset,
    timestamp,
    close,
    lead(close, 1) over w as close_tplus1,
    lag(aroon_25_up, 1) over w as aroon_up_t1,
    lag(aroon_25_down, 1) over w as aroon_down_t1,
    lag(aroon_25_osc, 1) over w as aroon_osc_t1,
    lag(pvt_50, 1) over w as pvt_t1,
    lag(pvt_50, 2) over w as pvt_t2,
    lag(roc_9, 1) over w as roc_t1,
    lag(adx_20, 1) over w as adx20_t1,
    lag(adx_20_plus_di, 1) over w as plus_di_t1,
    lag(adx_20_minus_di, 1) over w as minus_di_t1,
    lag(adx_14, 1) over w as adx14_t1,
    aroon_25_osc as aroon_osc_t0,
    pvt_50 as pvt_t0,
    roc_9 as roc_t0,
    adx_20 as adx20_t0,
    adx_20_plus_di as plus_di_t0,
    adx_20_minus_di as minus_di_t0
  from base
  window w as (partition by asset order by timestamp)
),
calc as (
  select
    asset,
    timestamp,
    close,
    close_tplus1,
    aroon_up_t1,
    aroon_down_t1,
    aroon_osc_t1,
    pvt_t1,
    pvt_t2,
    roc_t1,
    adx20_t1,
    plus_di_t1,
    minus_di_t1,
    adx14_t1,
    aroon_osc_t0,
    pvt_t0,
    roc_t0,
    adx20_t0,
    plus_di_t0,
    minus_di_t0,
    (((aroon_osc_t1 / 100.0) + (sign(pvt_t1 - pvt_t2) * 0.5)) * 1.5) as feature_1_value,
    (
      (
        case
          when adx20_t1 > 25 then roc_t1
          when adx20_t1 < 20 then -roc_t1
          else roc_t1
        end
      ) + (((plus_di_t1 - minus_di_t1) / 100.0) * 10.0)
    ) as feature_2_value,
    (close_tplus1 - close) as target_return_15m,
    ((close_tplus1 - close) / nullif(close, 0.0)) as target_return_pct
  from lagged
)
select *
from calc
where timestamp >= '{start_ts}'::timestamptz
  and timestamp <= {end_expr}
  and close_tplus1 is not null
order by asset, timestamp;
""".strip()


def _to_num(df: pd.DataFrame, skip: set[str] | None = None) -> pd.DataFrame:
    skip = skip or set()
    for c in df.columns:
        if c in skip:
            continue
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="coerce")
    return df


def _to_dt(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def _quintiles(s: pd.Series) -> pd.Series:
    r = s.rank(method="first")
    return pd.qcut(r, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min())


def _feature_metrics(df: pd.DataFrame, feature_col: str) -> dict[str, Any]:
    work = df[[feature_col, "target_return_15m", "target_return_pct"]].dropna().copy()
    if work.empty:
        return {
            "ic": float("nan"),
            "ic_abs": float("nan"),
            "top_quintile_win_rate": float("nan"),
            "max_drawdown": float("nan"),
        }
    ic = float(work[feature_col].corr(work["target_return_pct"]))
    work["q"] = _quintiles(work[feature_col])
    top = work[work["q"] == 5]
    win = float((top["target_return_15m"] > 0).mean()) if len(top) else float("nan")
    signal_ret = np.sign(work[feature_col]) * work["target_return_pct"]
    return {
        "ic": ic,
        "ic_abs": abs(ic) if not math.isnan(ic) else float("nan"),
        "top_quintile_win_rate": win,
        "max_drawdown": _max_drawdown(signal_ret),
    }


def _regime_split_ic(df: pd.DataFrame, feature_col: str) -> dict[str, Any]:
    trending = df[df["adx20_t1"] > 25.0][[feature_col, "target_return_pct"]].dropna()
    choppy = df[df["adx20_t1"] < 20.0][[feature_col, "target_return_pct"]].dropna()
    tr_ic = float(trending[feature_col].corr(trending["target_return_pct"])) if len(trending) >= 30 else float("nan")
    ch_ic = float(choppy[feature_col].corr(choppy["target_return_pct"])) if len(choppy) >= 30 else float("nan")
    return {
        "trending_n": int(len(trending)),
        "trending_ic": tr_ic,
        "choppy_n": int(len(choppy)),
        "choppy_ic": ch_ic,
    }


def _stability_label(trending_ic: float, choppy_ic: float) -> tuple[float, str]:
    if math.isnan(trending_ic) or math.isnan(choppy_ic):
        return float("nan"), "insufficient"
    spread = abs(trending_ic - choppy_ic)
    sign_consistent = np.sign(trending_ic) == np.sign(choppy_ic)
    if sign_consistent and spread <= 0.02:
        return spread, "stable"
    if spread <= 0.05:
        return spread, "moderate"
    return spread, "unstable"


def _build_feature_metrics(df: pd.DataFrame, feature_col: str, feature_name: str) -> FeatureMetrics:
    m = _feature_metrics(df, feature_col)
    reg = _regime_split_ic(df, feature_col)
    spread, stability = _stability_label(reg["trending_ic"], reg["choppy_ic"])
    return FeatureMetrics(
        feature=feature_name,
        ic=float(m["ic"]),
        ic_abs=float(m["ic_abs"]),
        top_quintile_win_rate=float(m["top_quintile_win_rate"]),
        max_drawdown=float(m["max_drawdown"]),
        regime_trending_ic=float(reg["trending_ic"]),
        regime_trending_n=int(reg["trending_n"]),
        regime_choppy_ic=float(reg["choppy_ic"]),
        regime_choppy_n=int(reg["choppy_n"]),
        regime_ic_spread=float(spread) if not math.isnan(spread) else float("nan"),
        regime_stability=stability,
        target_ic_pass=(not math.isnan(m["ic_abs"]) and abs(m["ic"]) > 0.035),
    )


def _write_synthetic_feature_table(db_url: str, syn_csv: Path) -> None:
    psql_exec(
        db_url,
        """
        drop table if exists indicators.synthetic_feature_test;
        create table indicators.synthetic_feature_test (
          timestamp timestamptz not null,
          asset text not null,
          feature_1_value double precision,
          feature_2_value double precision,
          target_return_15m double precision
        );
        """,
    )
    script = f"\\copy indicators.synthetic_feature_test (timestamp,asset,feature_1_value,feature_2_value,target_return_15m) FROM '{syn_csv.as_posix()}' CSV HEADER;"
    psql_script(db_url, script)


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[2]
    db_url = db_url_from_env(root)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else root / "scripts" / "output" / "synthetic_indicators" / f"revision2_eval_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sql = build_revision2_dataset_sql(start_ts=args.start, end_ts=args.end, pairs=pairs)
    df = pd.DataFrame(psql_csv(db_url, sql))
    if df.empty:
        raise SystemExit("No rows returned for requested window/pairs")

    df = _to_dt(df, ["timestamp"])
    df = _to_num(df, skip={"asset"})
    df = df.sort_values(["asset", "timestamp"]).reset_index(drop=True)

    # Derived helpers for decision ladders and leakage diagnostics.
    df["pvt_confirm"] = np.sign(df["pvt_t1"] - df["pvt_t2"])
    df["is_trending"] = df["adx20_t1"] > 25.0
    df["is_choppy"] = df["adx20_t1"] < 20.0
    df["di_spread"] = (df["plus_di_t1"] - df["minus_di_t1"]) / 100.0

    # Feature decision strengths (optional diagnostics).
    f1_down = np.select(
        [
            (df["aroon_down_t1"] > 70.0) & (df["pvt_confirm"] < 0),
            (df["aroon_down_t1"] > 50.0) & (df["pvt_confirm"] < 0),
            (df["aroon_down_t1"] > 50.0) & (df["pvt_confirm"] >= 0),
        ],
        [3, 2, 1],
        default=0,
    )
    f1_up = np.select(
        [
            (df["aroon_up_t1"] > 70.0) & (df["pvt_confirm"] > 0),
            (df["aroon_up_t1"] > 50.0) & (df["pvt_confirm"] > 0),
            (df["aroon_up_t1"] > 50.0) & (df["pvt_confirm"] <= 0),
        ],
        [3, 2, 1],
        default=0,
    )
    df["feature_1_down_strength"] = np.where(df["aroon_up_t1"] > 70.0, 0, f1_down)
    df["feature_1_up_strength"] = np.where(df["aroon_down_t1"] > 70.0, 0, f1_up)

    f2_down = np.select(
        [
            df["is_trending"] & (df["roc_t1"] < 0.0) & (df["minus_di_t1"] > df["plus_di_t1"]),
            df["is_choppy"] & (df["roc_t1"] > 5.0),
            df["is_trending"] & (df["roc_t1"] < 0.0),
            df["is_choppy"] & (df["roc_t1"] > 2.0),
        ],
        [3, 3, 2, 2],
        default=0,
    )
    f2_up = np.select(
        [
            df["is_trending"] & (df["roc_t1"] > 0.0) & (df["plus_di_t1"] > df["minus_di_t1"]),
            df["is_choppy"] & (df["roc_t1"] < -5.0),
            df["is_trending"] & (df["roc_t1"] > 0.0),
            df["is_choppy"] & (df["roc_t1"] < -2.0),
        ],
        [3, 3, 2, 2],
        default=0,
    )
    df["feature_2_down_strength"] = f2_down
    df["feature_2_up_strength"] = f2_up

    # Leakage diagnostics: compare no-leak features (t0-1) vs intentionally leaky (t0) variants.
    df["feature_1_value_leaky"] = ((df["aroon_osc_t0"] / 100.0) + (np.sign(df["pvt_t0"] - df["pvt_t1"]) * 0.5)) * 1.5
    base_leaky = np.select(
        [df["adx20_t0"] > 25.0, df["adx20_t0"] < 20.0],
        [df["roc_t0"], -df["roc_t0"]],
        default=df["roc_t0"],
    )
    df["feature_2_value_leaky"] = base_leaky + (((df["plus_di_t0"] - df["minus_di_t0"]) / 100.0) * 10.0)

    # Persist requested table.
    syn_table = df[["timestamp", "asset", "feature_1_value", "feature_2_value", "target_return_15m"]].copy()
    syn_csv = out_dir / "synthetic_feature_test.csv"
    syn_table.to_csv(syn_csv, index=False)
    if args.write_db_table:
        _write_synthetic_feature_table(db_url, syn_csv)

    # Metrics for revised synthetic indicators.
    f1_metrics = _build_feature_metrics(df, "feature_1_value", "aroon_pvt_confidence")
    f2_metrics = _build_feature_metrics(df, "feature_2_value", "adx_roc_regime_filter")
    feat_df = pd.DataFrame([f1_metrics.__dict__, f2_metrics.__dict__])

    # Baseline top-5 from previous audit family.
    baseline_cols = [
        ("aroon_down_t1", "aroon_25_down"),
        ("pvt_t1", "pvt_50"),
        ("roc_t1", "roc_9"),
        ("adx20_t1", "adx_20"),
        ("aroon_osc_t1", "aroon_25_osc"),
    ]
    baseline_rows: list[dict[str, Any]] = []
    for col, name in baseline_cols:
        m = _feature_metrics(df, col)
        reg = _regime_split_ic(df, col)
        baseline_rows.append(
            {
                "indicator": name,
                "ic": float(m["ic"]),
                "ic_abs": float(m["ic_abs"]),
                "top_quintile_win_rate": float(m["top_quintile_win_rate"]),
                "trend_ic_adx20_gt_25": float(reg["trending_ic"]),
                "trend_n_adx20_gt_25": int(reg["trending_n"]),
                "chop_ic_adx20_lt_20": float(reg["choppy_ic"]),
                "chop_n_adx20_lt_20": int(reg["choppy_n"]),
            }
        )
    baseline_df = pd.DataFrame(baseline_rows).sort_values("ic_abs", ascending=False)
    best_baseline_ic = float(baseline_df["ic_abs"].max()) if not baseline_df.empty else float("nan")

    # Strict no-leak indexing audit.
    leakage_summary = {
        "sql_enforces_lag_inputs": True,
        "required_lag_terms_present": all(
            term in sql
            for term in [
                "lag(aroon_25_up, 1)",
                "lag(aroon_25_down, 1)",
                "lag(aroon_25_osc, 1)",
                "lag(pvt_50, 1)",
                "lag(pvt_50, 2)",
                "lag(adx_20, 1)",
                "lag(adx_20_plus_di, 1)",
                "lag(adx_20_minus_di, 1)",
                "lag(roc_9, 1)",
                "lead(close, 1)",
            ]
        ),
        "feature_1_ic_no_leak": float(_feature_metrics(df, "feature_1_value")["ic"]),
        "feature_1_ic_leaky_t0": float(_feature_metrics(df, "feature_1_value_leaky")["ic"]),
        "feature_2_ic_no_leak": float(_feature_metrics(df, "feature_2_value")["ic"]),
        "feature_2_ic_leaky_t0": float(_feature_metrics(df, "feature_2_value_leaky")["ic"]),
        "feature_1_equal_to_leaky_ratio": float((np.isclose(df["feature_1_value"], df["feature_1_value_leaky"], equal_nan=False)).mean()),
        "feature_2_equal_to_leaky_ratio": float((np.isclose(df["feature_2_value"], df["feature_2_value_leaky"], equal_nan=False)).mean()),
        "close_used_in_feature_sql": False,
    }

    # Save artifacts.
    feat_csv = out_dir / "revision2_feature_metrics.csv"
    baseline_csv = out_dir / "baseline_top5_metrics.csv"
    detail_csv = out_dir / "revision2_dataset_detail.csv"
    feat_df.to_csv(feat_csv, index=False)
    baseline_df.to_csv(baseline_csv, index=False)
    df.to_csv(detail_csv, index=False)

    summary = {
        "run_id": run_id,
        "pairs": pairs,
        "start": args.start,
        "end": args.end,
        "rows_analyzed": int(len(df)),
        "rows_synthetic_feature_test": int(len(syn_table)),
        "revised_features": feat_df.to_dict("records"),
        "baseline_top5": baseline_df.to_dict("records"),
        "best_baseline_ic_abs": best_baseline_ic,
        "synthetic_vs_baseline": [
            {
                "feature": r["feature"],
                "ic_abs": r["ic_abs"],
                "delta_vs_best_baseline": float(r["ic_abs"] - best_baseline_ic) if not math.isnan(best_baseline_ic) else float("nan"),
            }
            for r in feat_df.to_dict("records")
        ],
        "leakage_check": leakage_summary,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    report_lines = [
        "# Revision 2 Synthetic Indicator Report",
        "",
        f"Run UTC: `{run_id}`",
        f"Pairs: `{', '.join(pairs)}`",
        f"Window: `{args.start}` to `{args.end}`",
        "",
        "## Implemented Features",
        "- `aroon_pvt_confidence` (uses `aroon_25_*[t0-1]` and `pvt_50[t0-1]-pvt_50[t0-2]`)",
        "- `adx_roc_regime_filter` (uses `adx_20/DI/roc_9[t0-1]` and ADX regime filter)",
        "",
        "## Regime Stability (IC split by ADX20 regimes)",
        feat_df[["feature", "ic", "regime_trending_ic", "regime_trending_n", "regime_choppy_ic", "regime_choppy_n", "regime_ic_spread", "regime_stability", "target_ic_pass"]].to_markdown(index=False),
        "",
        "## Baseline Top 5 Comparison",
        baseline_df.to_markdown(index=False),
        "",
        "## Leakage Check",
        f"- SQL lag contract present: `{leakage_summary['required_lag_terms_present']}`",
        f"- feature_1 IC no-leak vs leaky: `{leakage_summary['feature_1_ic_no_leak']:.6f}` vs `{leakage_summary['feature_1_ic_leaky_t0']:.6f}`",
        f"- feature_2 IC no-leak vs leaky: `{leakage_summary['feature_2_ic_no_leak']:.6f}` vs `{leakage_summary['feature_2_ic_leaky_t0']:.6f}`",
        f"- feature_1 value-equality ratio (no-leak vs leaky): `{leakage_summary['feature_1_equal_to_leaky_ratio']:.4f}`",
        f"- feature_2 value-equality ratio (no-leak vs leaky): `{leakage_summary['feature_2_equal_to_leaky_ratio']:.4f}`",
        "",
        "## Target Check (|IC| > 0.035)",
        feat_df[["feature", "ic_abs", "target_ic_pass"]].to_markdown(index=False),
    ]
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "report": str(out_dir / "report.md"),
                "summary": str(out_dir / "summary.json"),
                "feature_metrics_csv": str(feat_csv),
                "baseline_metrics_csv": str(baseline_csv),
                "rows_analyzed": int(len(df)),
                "rows_synthetic_feature_test": int(len(syn_table)),
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
