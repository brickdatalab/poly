#!/usr/bin/env python3
"""Revision 3 synthetic indicator evaluation with regime-adaptive logic."""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PAIRS_DEFAULT = ["BTC-USD", "ETH-USD", "SOL-USD"]
START_DEFAULT = "2026-01-25T00:00:00Z"
REV2_MAX_DRAWDOWN_BASELINE = -0.3463


def compute_adaptive_regime_alpha(
    adx_t1: float,
    aroon_osc_t1: float,
    pvt_t1: float,
    pvt_t2: float,
    roc_t1: float,
) -> float:
    if adx_t1 > 25.0:
        return float((aroon_osc_t1 / 100.0) + (np.sign(pvt_t1 - pvt_t2) * 0.5))
    if adx_t1 < 20.0:
        return float(-1.0 * (roc_t1 / 10.0))
    return 0.0


def compute_volume_strength_confirmation(
    pvt_t1: float,
    pvt_t2: float,
    atr_t1: float,
    atr_avg_t15_to_t2: float,
) -> float:
    if atr_avg_t15_to_t2 == 0 or np.isnan(atr_avg_t15_to_t2):
        return 0.0
    vol_ratio = atr_t1 / atr_avg_t15_to_t2
    if vol_ratio <= 0.8:
        return 0.0
    return float((pvt_t1 - pvt_t2) * vol_ratio)


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
    ap = argparse.ArgumentParser(description="Analyze Revision 3 synthetic indicators")
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


def build_revision3_dataset_sql(start_ts: str, end_ts: str, pairs: list[str]) -> str:
    pair_sql = _pair_sql(pairs)
    end_expr = _end_expr(end_ts)
    return f"""
with base as (
  select
    pair as asset,
    bucket_time as timestamp,
    close::float8 as close,
    adx_20::float8 as adx_20,
    adx_14::float8 as adx_14,
    aroon_25_up::float8 as aroon_25_up,
    aroon_25_down::float8 as aroon_25_down,
    aroon_25_osc::float8 as aroon_25_osc,
    pvt_50::float8 as pvt_50,
    roc_9::float8 as roc_9,
    atr_14::float8 as atr_14,
    obv_50::float8 as obv_50
  from indicators.v_model_15m
  where pair in ({pair_sql})
    and bucket_time >= '{start_ts}'::timestamptz - interval '8 hours'
    and bucket_time <= {end_expr} + interval '30 minutes'
),
lagged as (
  select
    asset,
    timestamp,
    close,
    lead(close, 1) over w as close_tplus1,
    lag(adx_20, 1) over w as adx_20_t1,
    lag(adx_14, 1) over w as adx_14_t1,
    lag(aroon_25_up, 1) over w as aroon_25_up_t1,
    lag(aroon_25_down, 1) over w as aroon_25_down_t1,
    lag(aroon_25_osc, 1) over w as aroon_25_osc_t1,
    lag(pvt_50, 1) over w as pvt_50_t1,
    lag(pvt_50, 2) over w as pvt_50_t2,
    lag(roc_9, 1) over w as roc_9_t1,
    lag(atr_14, 1) over w as atr_14_t1,
    avg(atr_14) over (partition by asset order by timestamp rows between 15 preceding and 2 preceding) as atr_avg_t15_to_t2,
    lag(obv_50, 1) over w as obv_50_t1,
    lag(obv_50, 2) over w as obv_50_t2,
    adx_20 as adx_20_t0,
    aroon_25_osc as aroon_25_osc_t0,
    pvt_50 as pvt_50_t0,
    roc_9 as roc_9_t0,
    atr_14 as atr_14_t0
  from base
  window w as (partition by asset order by timestamp)
)
select
  *,
  (close_tplus1 - close) as target_return_15m,
  ((close_tplus1 - close) / nullif(close, 0.0)) as target_return_pct
from lagged
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
    x = work[feature_col]
    y = work["target_return_pct"]
    if x.std(ddof=0) == 0 or y.std(ddof=0) == 0:
        ic = float("nan")
    else:
        ic = float(x.corr(y))
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
    out: dict[str, Any] = {}
    regimes = {
        "adx_gt_25": df["adx_20_t1"] > 25.0,
        "adx_lt_20": df["adx_20_t1"] < 20.0,
        "adx_20_25": (df["adx_20_t1"] >= 20.0) & (df["adx_20_t1"] <= 25.0),
    }
    for name, mask in regimes.items():
        g = df.loc[mask, [feature_col, "target_return_pct"]].dropna()
        if len(g) < 30:
            ic = float("nan")
        elif g[feature_col].std(ddof=0) == 0 or g["target_return_pct"].std(ddof=0) == 0:
            ic = float("nan")
        else:
            ic = float(g[feature_col].corr(g["target_return_pct"]))
        out[f"{name}_n"] = int(len(g))
        out[f"{name}_ic"] = ic
    return out


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


def _zscore_by_asset(df: pd.DataFrame, value_col: str) -> pd.Series:
    grp = df.groupby("asset")[value_col]
    mu = grp.transform("mean")
    sd = grp.transform("std")
    z = (df[value_col] - mu) / sd.replace(0, np.nan)
    return z


def _make_promotion_sql() -> str:
    return """
-- Promote Revision 3 synthetic features from synthetic_feature_test into indicator_values.
-- Run after validation sign-off.

begin;

insert into indicators.indicator_values (pair, bucket_time, config_id, v1, created_at)
select
  asset as pair,
  timestamp as bucket_time,
  'adaptive_regime_alpha_15m' as config_id,
  feature_1_value as v1,
  now() as created_at
from indicators.synthetic_feature_test
on conflict (pair, bucket_time, config_id) do update
set v1 = excluded.v1,
    created_at = now();

insert into indicators.indicator_values (pair, bucket_time, config_id, v1, created_at)
select
  asset as pair,
  timestamp as bucket_time,
  'volume_strength_confirmation_15m' as config_id,
  feature_2_value as v1,
  now() as created_at
from indicators.synthetic_feature_test
on conflict (pair, bucket_time, config_id) do update
set v1 = excluded.v1,
    created_at = now();

commit;
""".strip()


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[2]
    db_url = db_url_from_env(root)
    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else root / "scripts" / "output" / "synthetic_indicators" / f"revision3_eval_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    sql = build_revision3_dataset_sql(start_ts=args.start, end_ts=args.end, pairs=pairs)
    df = pd.DataFrame(psql_csv(db_url, sql))
    if df.empty:
        raise SystemExit("No rows returned for requested window/pairs")
    df = _to_dt(df, ["timestamp"])
    df = _to_num(df, skip={"asset"})
    df = df.sort_values(["asset", "timestamp"]).reset_index(drop=True)

    # Revision 3 feature formulas.
    df["pvt_slope_t1"] = df["pvt_50_t1"] - df["pvt_50_t2"]
    df["adaptive_regime_alpha"] = np.select(
        [df["adx_20_t1"] > 25.0, df["adx_20_t1"] < 20.0],
        [
            (df["aroon_25_osc_t1"] / 100.0) + (np.sign(df["pvt_slope_t1"]) * 0.5),
            -1.0 * (df["roc_9_t1"] / 10.0),
        ],
        default=0.0,
    )

    df["vol_ratio"] = np.where(
        df["atr_avg_t15_to_t2"].abs() > 0.0,
        df["atr_14_t1"] / df["atr_avg_t15_to_t2"],
        np.nan,
    )
    df["volume_strength_confirmation"] = np.where(
        df["vol_ratio"] > 0.8,
        (df["pvt_50_t1"] - df["pvt_50_t2"]) * df["vol_ratio"],
        0.0,
    )
    df["obv_slope_t1"] = df["obv_50_t1"] - df["obv_50_t2"]

    # Decision strengths for diagnostics.
    df["adaptive_down_strength"] = np.select(
        [
            (df["adx_20_t1"] > 25.0) & (df["aroon_25_osc_t1"] < -50.0) & (df["pvt_slope_t1"] < 0),
            (df["adx_20_t1"] > 25.0) & (df["aroon_25_osc_t1"] < -50.0),
            (df["adx_20_t1"] < 20.0) & (df["roc_9_t1"] > 3.0),
            (df["adx_20_t1"] < 20.0) & (df["roc_9_t1"] > 1.5),
        ],
        [3, 2, 3, 2],
        default=0,
    )
    df["adaptive_up_strength"] = np.select(
        [
            (df["adx_20_t1"] > 25.0) & (df["aroon_25_osc_t1"] > 50.0) & (df["pvt_slope_t1"] > 0),
            (df["adx_20_t1"] > 25.0) & (df["aroon_25_osc_t1"] > 50.0),
            (df["adx_20_t1"] < 20.0) & (df["roc_9_t1"] < -3.0),
            (df["adx_20_t1"] < 20.0) & (df["roc_9_t1"] < -1.5),
        ],
        [3, 2, 3, 2],
        default=0,
    )

    base_down = np.select(
        [df["volume_strength_confirmation"] < -3, df["volume_strength_confirmation"] < -2, df["volume_strength_confirmation"] < -1],
        [3, 2, 1],
        default=0,
    )
    base_up = np.select(
        [df["volume_strength_confirmation"] > 3, df["volume_strength_confirmation"] > 2, df["volume_strength_confirmation"] > 1],
        [3, 2, 1],
        default=0,
    )
    df["volume_down_strength"] = base_down + np.where(df["obv_slope_t1"] < 0, 1, 0)
    df["volume_up_strength"] = base_up + np.where(df["obv_slope_t1"] > 0, 1, 0)

    # Leaky comparators for diagnostics only (do not write/use for production).
    df["adaptive_regime_alpha_leaky"] = np.select(
        [df["adx_20_t0"] > 25.0, df["adx_20_t0"] < 20.0],
        [
            (df["aroon_25_osc_t0"] / 100.0) + (np.sign(df["pvt_50_t0"] - df["pvt_50_t1"]) * 0.5),
            -1.0 * (df["roc_9_t0"] / 10.0),
        ],
        default=0.0,
    )
    # rolling mean that includes t0 by construction (leaky reference).
    df["atr_avg_leaky_t14_to_t0"] = df.groupby("asset")["atr_14_t0"].transform(
        lambda s: s.rolling(window=15, min_periods=3).mean()
    )
    df["volume_strength_confirmation_leaky"] = np.where(
        (df["atr_avg_leaky_t14_to_t0"].abs() > 0.0) & ((df["atr_14_t0"] / df["atr_avg_leaky_t14_to_t0"]) > 0.8),
        (df["pvt_50_t0"] - df["pvt_50_t1"]) * (df["atr_14_t0"] / df["atr_avg_leaky_t14_to_t0"]),
        0.0,
    )

    dataset = df.dropna(
        subset=[
            "target_return_15m",
            "target_return_pct",
            "adaptive_regime_alpha",
            "volume_strength_confirmation",
            "adx_20_t1",
        ]
    ).copy()

    # Combined strategy: average of per-asset z-scored features.
    dataset["adaptive_z"] = _zscore_by_asset(dataset, "adaptive_regime_alpha")
    dataset["volume_z"] = _zscore_by_asset(dataset, "volume_strength_confirmation")
    dataset["combined_strategy"] = (dataset["adaptive_z"].fillna(0.0) + dataset["volume_z"].fillna(0.0)) / 2.0

    syn_table = dataset[["timestamp", "asset", "adaptive_regime_alpha", "volume_strength_confirmation", "target_return_15m"]].rename(
        columns={
            "adaptive_regime_alpha": "feature_1_value",
            "volume_strength_confirmation": "feature_2_value",
        }
    )
    syn_csv = out_dir / "synthetic_feature_test.csv"
    syn_table.to_csv(syn_csv, index=False)
    if args.write_db_table:
        _write_synthetic_feature_table(db_url, syn_csv)

    # Metrics.
    adaptive_metrics = _feature_metrics(dataset, "adaptive_regime_alpha")
    adaptive_regimes = _regime_split_ic(dataset, "adaptive_regime_alpha")

    volume_metrics = _feature_metrics(dataset, "volume_strength_confirmation")
    volume_regimes = _regime_split_ic(dataset, "volume_strength_confirmation")

    combined_metrics = _feature_metrics(dataset, "combined_strategy")
    combined_regimes = _regime_split_ic(dataset, "combined_strategy")

    # Baseline comparison from prior top features.
    baseline_cols = [
        ("aroon_25_down_t1", "aroon_25_down"),
        ("pvt_50_t1", "pvt_50"),
        ("roc_9_t1", "roc_9"),
        ("adx_20_t1", "adx_20"),
        ("aroon_25_osc_t1", "aroon_25_osc"),
    ]
    baseline_rows: list[dict[str, Any]] = []
    for col, name in baseline_cols:
        m = _feature_metrics(dataset, col)
        r = _regime_split_ic(dataset, col)
        baseline_rows.append(
            {
                "indicator": name,
                "ic": float(m["ic"]),
                "ic_abs": float(m["ic_abs"]),
                "top_quintile_win_rate": float(m["top_quintile_win_rate"]),
                "adx_gt_25_ic": float(r["adx_gt_25_ic"]),
                "adx_gt_25_n": int(r["adx_gt_25_n"]),
                "adx_lt_20_ic": float(r["adx_lt_20_ic"]),
                "adx_lt_20_n": int(r["adx_lt_20_n"]),
                "adx_20_25_ic": float(r["adx_20_25_ic"]),
                "adx_20_25_n": int(r["adx_20_25_n"]),
            }
        )
    baseline_df = pd.DataFrame(baseline_rows).sort_values("ic_abs", ascending=False)

    # Success + flags.
    adaptive_choppy_ic = float(adaptive_regimes["adx_lt_20_ic"])
    adaptive_primary_alpha_flag = (not math.isnan(adaptive_choppy_ic)) and (adaptive_choppy_ic > 0.040)
    combined_ic = float(combined_metrics["ic"])
    combined_target_pass = (not math.isnan(combined_ic)) and (combined_ic > 0.035)

    volume_mdd = float(volume_metrics["max_drawdown"])
    drawdown_reduced = (not math.isnan(volume_mdd)) and (volume_mdd > REV2_MAX_DRAWDOWN_BASELINE)
    drawdown_delta = volume_mdd - REV2_MAX_DRAWDOWN_BASELINE if not math.isnan(volume_mdd) else float("nan")

    sql_l = sql.lower()
    leakage_contract = {
        "required_lag_terms_present": all(
            term in sql_l
            for term in [
                "lag(adx_20, 1)",
                "lag(aroon_25_osc, 1)",
                "lag(pvt_50, 1)",
                "lag(pvt_50, 2)",
                "lag(roc_9, 1)",
                "lag(atr_14, 1)",
                "lag(obv_50, 1)",
                "lag(obv_50, 2)",
                "avg(atr_14) over (partition by asset order by timestamp rows between 15 preceding and 2 preceding)",
                "lead(close, 1)",
            ]
        ),
        "atr_avg_excludes_t0": "rows between 15 preceding and 2 preceding" in sql_l,
        "adaptive_ic_no_leak": float(adaptive_metrics["ic"]),
        "adaptive_ic_leaky_t0": float(_feature_metrics(dataset, "adaptive_regime_alpha_leaky")["ic"]),
        "volume_ic_no_leak": float(volume_metrics["ic"]),
        "volume_ic_leaky_t0": float(_feature_metrics(dataset, "volume_strength_confirmation_leaky")["ic"]),
    }

    promotion_ready = combined_target_pass and leakage_contract["required_lag_terms_present"] and leakage_contract["atr_avg_excludes_t0"]
    migration_sql_path = ""
    if promotion_ready:
        migration_sql_path = str(out_dir / "promotion_migration.sql")
        Path(migration_sql_path).write_text(_make_promotion_sql() + "\n", encoding="utf-8")

    # Outputs.
    dataset.to_csv(out_dir / "revision3_dataset_detail.csv", index=False)
    baseline_df.to_csv(out_dir / "baseline_top5_metrics.csv", index=False)

    summary = {
        "run_id": run_id,
        "pairs": pairs,
        "start": args.start,
        "end": args.end,
        "rows_analyzed": int(len(dataset)),
        "rows_synthetic_feature_test": int(len(syn_table)),
        "features": {
            "adaptive_regime_alpha": {
                **adaptive_metrics,
                **adaptive_regimes,
                "primary_alpha_flag_choppy_ic_gt_0_040": adaptive_primary_alpha_flag,
            },
            "volume_strength_confirmation": {
                **volume_metrics,
                **volume_regimes,
                "rev2_baseline_max_drawdown": REV2_MAX_DRAWDOWN_BASELINE,
                "drawdown_reduced_vs_rev2": drawdown_reduced,
                "drawdown_delta_vs_rev2": drawdown_delta,
            },
        },
        "combined_strategy": {
            **combined_metrics,
            **combined_regimes,
            "target_ic_gt_0_035": combined_target_pass,
        },
        "baseline_top5": baseline_df.to_dict("records"),
        "leakage_contract": leakage_contract,
        "promotion_ready": promotion_ready,
        "promotion_migration_sql": migration_sql_path or None,
    }
    (out_dir / "summary.json").write_text(json.dumps(summary, indent=2, default=str), encoding="utf-8")

    report_lines = [
        "# Revision 3 Synthetic Indicator Report",
        "",
        f"Run UTC: `{run_id}`",
        f"Pairs: `{', '.join(pairs)}`",
        f"Window: `{args.start}` to `{args.end}`",
        "",
        "## Regime-Specific IC (ADX20 bins)",
        f"- adaptive_regime_alpha: `>25={adaptive_regimes['adx_gt_25_ic']:.6f}`, `<20={adaptive_regimes['adx_lt_20_ic']:.6f}`, `20-25={adaptive_regimes['adx_20_25_ic']:.6f}`",
        f"- volume_strength_confirmation: `>25={volume_regimes['adx_gt_25_ic']:.6f}`, `<20={volume_regimes['adx_lt_20_ic']:.6f}`, `20-25={volume_regimes['adx_20_25_ic']:.6f}`",
        f"- combined_strategy: `>25={combined_regimes['adx_gt_25_ic']:.6f}`, `<20={combined_regimes['adx_lt_20_ic']:.6f}`, `20-25={combined_regimes['adx_20_25_ic']:.6f}`",
        "",
        "## Target Checks",
        f"- Combined strategy IC > 0.035: `{combined_target_pass}` (IC={combined_ic:.6f})",
        f"- adaptive_regime_alpha choppy IC > 0.040: `{adaptive_primary_alpha_flag}` (IC={adaptive_choppy_ic:.6f})",
        "",
        "## Drawdown Check",
        f"- volume_strength_confirmation max drawdown: `{volume_mdd:.6f}`",
        f"- Rev2 baseline max drawdown: `{REV2_MAX_DRAWDOWN_BASELINE:.6f}`",
        f"- Drawdown reduced vs Rev2 baseline: `{drawdown_reduced}` (delta={drawdown_delta:.6f})",
        "",
        "## Leakage Contract",
        f"- Required lag terms present: `{leakage_contract['required_lag_terms_present']}`",
        f"- ATR avg excludes t0 via SQL window: `{leakage_contract['atr_avg_excludes_t0']}`",
        f"- adaptive no-leak vs leaky IC: `{leakage_contract['adaptive_ic_no_leak']:.6f}` vs `{leakage_contract['adaptive_ic_leaky_t0']:.6f}`",
        f"- volume no-leak vs leaky IC: `{leakage_contract['volume_ic_no_leak']:.6f}` vs `{leakage_contract['volume_ic_leaky_t0']:.6f}`",
        "",
        "## Promotion",
        f"- Promotion ready: `{promotion_ready}`",
        f"- Migration SQL: `{migration_sql_path if migration_sql_path else 'not generated (criteria not met)'}`",
    ]
    (out_dir / "report.md").write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(
        json.dumps(
            {
                "out_dir": str(out_dir),
                "report": str(out_dir / "report.md"),
                "summary": str(out_dir / "summary.json"),
                "rows_analyzed": int(len(dataset)),
                "rows_synthetic_feature_test": int(len(syn_table)),
                "promotion_ready": promotion_ready,
                "promotion_migration_sql": migration_sql_path or None,
            },
            indent=2,
        )
    )


if __name__ == "__main__":
    main()
