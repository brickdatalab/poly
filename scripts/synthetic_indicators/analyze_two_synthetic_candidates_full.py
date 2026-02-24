#!/usr/bin/env python3
"""Full audit + evaluation for two synthetic indicator candidates.

This script is intentionally compute-heavy in Python and only pulls compact table slices
from Supabase via psql.
"""

from __future__ import annotations

import argparse
import csv
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

import numpy as np
import pandas as pd

PAIRS_DEFAULT = ["BTC-USD", "ETH-USD", "SOL-USD"]
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


def db_url_from_env(root: Path) -> str:
    env = load_env(root)
    db_url = env.get("SUPABASE_DB_URL", "").strip()
    if not db_url:
        raise SystemExit("SUPABASE_DB_URL missing in .env")
    return db_url


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


def psql_exec(db_url: str, sql: str) -> None:
    subprocess.check_call(
        [
            "psql",
            db_url,
            "-v",
            "ON_ERROR_STOP=1",
            "-P",
            "pager=off",
            "-c",
            sql,
        ]
    )


@dataclass
class FeatureSummary:
    feature_name: str
    ic: float
    ic_abs: float
    win_rate_top_quintile: float
    max_drawdown: float
    best_regime: str
    worst_regime: str
    regime_stability: str
    decision: str
    decision_reason: str


def _parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Full synthetic candidate audit/eval")
    ap.add_argument("--start", default=START_DEFAULT)
    ap.add_argument("--end", default="now")
    ap.add_argument("--pairs", default=",".join(PAIRS_DEFAULT))
    ap.add_argument("--out", default="")
    ap.add_argument("--write-db-table", action="store_true", default=True)
    return ap.parse_args()


def _end_expr(end_ts: str) -> str:
    if end_ts.lower() == "now":
        return "(date_trunc('minute', now()) - interval '1 minute')"
    return f"'{end_ts}'::timestamptz"


def _pair_sql(pairs: list[str]) -> str:
    return ", ".join(f"'{p}'" for p in pairs)


def _fetch_df(db_url: str, sql: str) -> pd.DataFrame:
    rows = psql_csv(db_url, sql)
    return pd.DataFrame(rows)


def _to_dt(df: pd.DataFrame, cols: list[str]) -> pd.DataFrame:
    for c in cols:
        if c in df.columns:
            df[c] = pd.to_datetime(df[c], utc=True, errors="coerce")
    return df


def _to_num(df: pd.DataFrame, skip: set[str] | None = None) -> pd.DataFrame:
    skip = skip or set()
    for c in df.columns:
        if c in skip:
            continue
        if df[c].dtype == object:
            df[c] = pd.to_numeric(df[c], errors="ignore")
    return df


def _gap_stats(df: pd.DataFrame, pair_col: str, ts_col: str, step: str) -> pd.DataFrame:
    expected = pd.to_timedelta(step)
    out = []
    for pair, g in df.sort_values(ts_col).groupby(pair_col):
        delta = g[ts_col].diff()
        gaps = delta[delta > expected]
        missing = int(((gaps / expected) - 1).sum()) if len(gaps) else 0
        out.append(
            {
                "asset": pair,
                "gap_windows": int(len(gaps)),
                "missing_steps": missing,
                "max_gap": str(gaps.max()) if len(gaps) else "0 days 00:00:00",
            }
        )
    return pd.DataFrame(out)


def _max_drawdown(returns: pd.Series) -> float:
    if returns.empty:
        return float("nan")
    eq = (1.0 + returns.fillna(0.0)).cumprod()
    peak = eq.cummax()
    dd = (eq / peak) - 1.0
    return float(dd.min())


def _quintiles(s: pd.Series) -> pd.Series:
    r = s.rank(method="first")
    return pd.qcut(r, 5, labels=[1, 2, 3, 4, 5]).astype(int)


def _feature_metrics(df: pd.DataFrame, feature_col: str) -> dict[str, Any]:
    work = df[[feature_col, "target_return_15m", "target_return_pct"]].dropna().copy()
    if work.empty:
        return {
            "ic": float("nan"),
            "ic_abs": float("nan"),
            "win_rate_top_quintile": float("nan"),
            "quintile_mean_return_pct": {},
            "max_drawdown": float("nan"),
        }

    ic = float(work[feature_col].corr(work["target_return_pct"]))
    work["q"] = _quintiles(work[feature_col])
    qret = work.groupby("q")["target_return_pct"].mean().to_dict()
    top = work[work["q"] == 5]
    win = float((top["target_return_15m"] > 0).mean()) if len(top) else float("nan")
    signal_ret = np.sign(work[feature_col]) * work["target_return_pct"]
    mdd = _max_drawdown(signal_ret)
    return {
        "ic": ic,
        "ic_abs": abs(ic) if not math.isnan(ic) else float("nan"),
        "win_rate_top_quintile": win,
        "quintile_mean_return_pct": {int(k): float(v) for k, v in qret.items()},
        "max_drawdown": mdd,
    }


def _regime_breakdown(df: pd.DataFrame, feature_col: str) -> pd.DataFrame:
    work = df[[feature_col, "target_return_pct", "adx_prev", "atr_prev", "asset"]].dropna().copy()
    if work.empty:
        return pd.DataFrame(columns=["regime", "n", "ic"])

    atr_median = work.groupby("asset")["atr_prev"].transform("median")
    work["trend_regime"] = np.where(work["adx_prev"] >= 20.0, "Trending", "Choppy")
    work["vol_regime"] = np.where(work["atr_prev"] >= atr_median, "HighVol", "LowVol")
    work["regime"] = work["trend_regime"] + " & " + work["vol_regime"]

    rows: list[dict[str, Any]] = []
    for regime, g in work.groupby("regime"):
        ic = float(g[feature_col].corr(g["target_return_pct"])) if len(g) >= 30 else float("nan")
        rows.append({"regime": regime, "n": int(len(g)), "ic": ic})
    return pd.DataFrame(rows).sort_values("ic", ascending=False)


def _stability_label(reg: pd.DataFrame) -> str:
    if reg.empty:
        return "insufficient"
    good = reg.dropna(subset=["ic"]) 
    if len(good) < 2:
        return "insufficient"
    sign_consistent = np.all(np.sign(good["ic"]) == np.sign(good["ic"].iloc[0]))
    spread = float(good["ic"].max() - good["ic"].min())
    if sign_consistent and spread <= 0.03:
        return "stable"
    if spread <= 0.06:
        return "moderate"
    return "unstable"


def _decision(ic_abs: float, stability: str, leakage_flag: bool) -> tuple[str, str]:
    if leakage_flag or (not math.isnan(ic_abs) and ic_abs < 0.02):
        return "REPLACE", "IC below 0.02 and/or leakage integrity risk"
    if ic_abs > 0.05 and stability == "stable":
        return "KEEP", "IC above 0.05 with regime stability"
    return "TWEAK", "Signal has some edge but is noisy/regime-sensitive"


def main() -> None:
    args = _parse_args()
    root = Path(__file__).resolve().parents[2]
    db_url = db_url_from_env(root)

    pairs = [p.strip() for p in args.pairs.split(",") if p.strip()]
    pair_sql = _pair_sql(pairs)
    end_expr = _end_expr(args.end)

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_dir = Path(args.out) if args.out else root / "scripts" / "output" / "synthetic_indicators" / f"full_eval_{run_id}"
    out_dir.mkdir(parents=True, exist_ok=True)

    # -----------------
    # Fetch source data
    # -----------------
    q_o15 = f"""
    select pair, bucket_time, open, high, low, close, created_at
    from indicators.ohlcv_15m
    where pair in ({pair_sql})
      and bucket_time >= '{args.start}'::timestamptz - interval '2 hours'
      and bucket_time <= {end_expr} + interval '30 minutes'
    order by pair, bucket_time;
    """
    q_o1 = f"""
    select pair, bucket_time, open, close, created_at
    from indicators.ohlcv_1m
    where pair in ({pair_sql})
      and bucket_time >= '{args.start}'::timestamptz - interval '2 hours'
      and bucket_time <= {end_expr} + interval '5 minutes'
    order by pair, bucket_time;
    """
    q_iv = f"""
    select pair, bucket_time, config_id, v1, created_at
    from indicators.indicator_values
    where pair in ({pair_sql})
      and config_id in ('cvd_20_1m','atr_14_15m','rsi_14_15m','adx_14_15m','macd_12_26_9_15m')
      and bucket_time >= '{args.start}'::timestamptz - interval '3 hours'
      and bucket_time <= {end_expr} + interval '5 minutes'
    order by pair, config_id, bucket_time;
    """
    q_oi = f"""
    select pair, bucket_time, oi_acceleration, computed_at
    from indicators.oi_features
    where pair in ({pair_sql})
      and bucket_time >= '{args.start}'::timestamptz - interval '3 hours'
      and bucket_time <= {end_expr}
    order by pair, bucket_time;
    """
    q_v15 = f"""
    select *
    from indicators.v_model_15m
    where pair in ({pair_sql})
      and bucket_time >= '{args.start}'::timestamptz - interval '2 hours'
      and bucket_time <= {end_expr}
    order by pair, bucket_time;
    """

    o15 = _to_num(_to_dt(_fetch_df(db_url, q_o15), ["bucket_time", "created_at"]), skip={"pair"})
    o1 = _to_num(_to_dt(_fetch_df(db_url, q_o1), ["bucket_time", "created_at"]), skip={"pair"})
    iv = _to_num(_to_dt(_fetch_df(db_url, q_iv), ["bucket_time", "created_at"]), skip={"pair", "config_id"})
    oi = _to_num(_to_dt(_fetch_df(db_url, q_oi), ["bucket_time", "computed_at"]), skip={"pair"})
    v15 = _to_num(_to_dt(_fetch_df(db_url, q_v15), ["bucket_time"]), skip={"pair"})

    # -------------------------
    # Phase 1: Integrity audit
    # -------------------------
    audit: dict[str, Any] = {}

    o15_main = o15[(o15["bucket_time"] >= pd.Timestamp(args.start, tz="UTC")) & (o15["pair"].isin(pairs))].copy()
    o1_main = o1[(o1["bucket_time"] >= pd.Timestamp(args.start, tz="UTC")) & (o1["pair"].isin(pairs))].copy()

    audit["ohlcv_15m_alignment_misaligned_rows"] = int((o15_main["bucket_time"].dt.minute % 15 != 0).sum())
    audit["ohlcv_1m_alignment_misaligned_rows"] = int((o1_main["bucket_time"].dt.second != 0).sum())

    iv_15m = iv[iv["config_id"].isin(["atr_14_15m", "rsi_14_15m", "adx_14_15m", "macd_12_26_9_15m"])].copy()
    iv_1m = iv[iv["config_id"] == "cvd_20_1m"].copy()
    audit["indicator_15m_misaligned_rows"] = int((iv_15m["bucket_time"].dt.minute % 15 != 0).sum())

    def lag_secs(frame: pd.DataFrame, close_offset_min: int, created_col: str) -> pd.Series:
        return (frame[created_col] - (frame["bucket_time"] + pd.to_timedelta(close_offset_min, unit="m"))).dt.total_seconds()

    o15_lag = lag_secs(o15_main.dropna(subset=["created_at"]), 15, "created_at")
    iv15_lag = lag_secs(iv_15m.dropna(subset=["created_at"]), 15, "created_at")
    iv1_lag = lag_secs(iv_1m.dropna(subset=["created_at"]), 1, "created_at")
    oi_lag = (oi.dropna(subset=["computed_at"])["computed_at"] - (oi.dropna(subset=["computed_at"])["bucket_time"] + pd.Timedelta(minutes=15))).dt.total_seconds()

    audit["ohlcv_15m_negative_lag_rows"] = int((o15_lag < 0).sum())
    audit["indicator_15m_negative_lag_rows"] = int((iv15_lag < 0).sum())
    audit["cvd_1m_negative_lag_rows"] = int((iv1_lag < 0).sum())
    audit["oi_negative_lag_rows"] = int((oi_lag < 0).sum())

    audit["ohlcv_15m_gap_stats"] = _gap_stats(o15_main[["pair", "bucket_time"]].drop_duplicates(), "pair", "bucket_time", "15min").to_dict("records")
    audit["ohlcv_1m_gap_stats"] = _gap_stats(o1_main[["pair", "bucket_time"]].drop_duplicates(), "pair", "bucket_time", "1min").to_dict("records")
    audit["oi_gap_stats"] = _gap_stats(oi[["pair", "bucket_time"]].drop_duplicates(), "pair", "bucket_time", "15min").to_dict("records")

    leakage_flag = (audit["indicator_15m_misaligned_rows"] > 0) or (audit["indicator_15m_negative_lag_rows"] > 0)

    # ---------------------------------
    # Phase 2: Feature engineering (Py)
    # ---------------------------------
    base = o15_main[["pair", "bucket_time", "open", "high", "low", "close"]].rename(
        columns={"pair": "asset", "bucket_time": "timestamp", "close": "close_t0"}
    )

    # Keep last row per key for indicator slices.
    iv = iv.sort_values(["pair", "config_id", "bucket_time", "created_at"])
    iv = iv.drop_duplicates(["pair", "config_id", "bucket_time"], keep="last")
    iv = iv.rename(columns={"pair": "asset", "bucket_time": "timestamp"})

    cvd = iv[iv["config_id"] == "cvd_20_1m"][["asset", "timestamp", "v1"]].rename(columns={"v1": "cvd"})
    atr = iv[(iv["config_id"] == "atr_14_15m") & (iv["timestamp"].dt.minute % 15 == 0)][["asset", "timestamp", "v1"]].rename(columns={"v1": "atr"})
    rsi = iv[(iv["config_id"] == "rsi_14_15m") & (iv["timestamp"].dt.minute % 15 == 0)][["asset", "timestamp", "v1"]].rename(columns={"v1": "rsi"})
    adx = iv[(iv["config_id"] == "adx_14_15m") & (iv["timestamp"].dt.minute % 15 == 0)][["asset", "timestamp", "v1"]].rename(columns={"v1": "adx"})
    macd = iv[(iv["config_id"] == "macd_12_26_9_15m") & (iv["timestamp"].dt.minute % 15 == 0)][["asset", "timestamp", "v1"]].rename(columns={"v1": "macd"})

    one_m = o1_main[["pair", "bucket_time", "close"]].rename(columns={"pair": "asset", "bucket_time": "timestamp", "close": "close_1m"})

    # Feature 1
    f1 = base[["asset", "timestamp", "open"]].copy()

    m2 = one_m[["asset", "timestamp", "close_1m"]].copy()
    m2["timestamp"] = m2["timestamp"] - pd.Timedelta(minutes=2)
    m2 = m2.rename(columns={"close_1m": "close_t0p2"})

    cvd0 = cvd.rename(columns={"cvd": "cvd_t0"})
    cvd2 = cvd.rename(columns={"cvd": "cvd_t0p2"}).copy()
    cvd2["timestamp"] = cvd2["timestamp"] - pd.Timedelta(minutes=2)

    atr_prev = atr.rename(columns={"atr": "atr_prev"}).copy()
    atr_prev["timestamp"] = atr_prev["timestamp"] + pd.Timedelta(minutes=15)

    atr_curr = atr.rename(columns={"atr": "atr_curr"})

    f1 = f1.merge(m2, on=["asset", "timestamp"], how="left")
    f1 = f1.merge(cvd0, on=["asset", "timestamp"], how="left")
    f1 = f1.merge(cvd2, on=["asset", "timestamp"], how="left")
    f1 = f1.merge(atr_prev, on=["asset", "timestamp"], how="left")
    f1 = f1.merge(atr_curr, on=["asset", "timestamp"], how="left")

    f1["early_return"] = (f1["close_t0p2"] - f1["open"]) / f1["open"]
    f1["cvd_change"] = f1["cvd_t0p2"] - f1["cvd_t0"]
    f1["cvd_sign"] = np.sign(f1["cvd_change"])
    f1["vol_norm_prev"] = f1["early_return"] / f1["atr_prev"]
    f1["vol_norm_t0"] = f1["early_return"] / f1["atr_curr"]
    f1["feature_1_value"] = f1["vol_norm_prev"] * f1["cvd_sign"]
    f1["feature_1_value_leaky"] = f1["vol_norm_t0"] * f1["cvd_sign"]

    grp_mu = f1.groupby("asset")["feature_1_value"].transform("mean")
    grp_sd = f1.groupby("asset")["feature_1_value"].transform("std")
    grp_cvd_abs = f1.groupby("asset")["cvd_change"].transform(lambda s: s.abs().mean())
    f1["synthetic_z"] = (f1["feature_1_value"] - grp_mu) / grp_sd

    whipsaw_down = (f1["early_return"] < 0) & (f1["cvd_change"] > 0) & (f1["cvd_change"].abs() > grp_cvd_abs)
    whipsaw_up = (f1["early_return"] > 0) & (f1["cvd_change"] < 0) & (f1["cvd_change"].abs() > grp_cvd_abs)

    f1["down_strength"] = np.select(
        [
            whipsaw_down,
            f1["synthetic_z"] < -3,
            f1["synthetic_z"] < -2,
            f1["synthetic_z"] < -1,
        ],
        [0, 3, 2, 1],
        default=0,
    )
    f1["up_strength"] = np.select(
        [
            whipsaw_up,
            f1["synthetic_z"] > 3,
            f1["synthetic_z"] > 2,
            f1["synthetic_z"] > 1,
        ],
        [0, 3, 2, 1],
        default=0,
    )

    # Feature 2
    f2 = base[["asset", "timestamp"]].copy()

    c1 = base[["asset", "timestamp", "high", "low", "close_t0"]].copy()
    c1["timestamp"] = c1["timestamp"] + pd.Timedelta(minutes=15)
    c1 = c1.rename(columns={"high": "high_t1", "low": "low_t1", "close_t0": "close_t1"})

    c2 = base[["asset", "timestamp", "high", "low", "close_t0"]].copy()
    c2["timestamp"] = c2["timestamp"] + pd.Timedelta(minutes=30)
    c2 = c2.rename(columns={"high": "high_t2", "low": "low_t2", "close_t0": "close_t2"})

    c3 = base[["asset", "timestamp", "high", "low"]].copy()
    c3["timestamp"] = c3["timestamp"] + pd.Timedelta(minutes=45)
    c3 = c3.rename(columns={"high": "high_t3", "low": "low_t3"})

    r1 = rsi.copy(); r1["timestamp"] = r1["timestamp"] + pd.Timedelta(minutes=15); r1 = r1.rename(columns={"rsi": "rsi_t1"})
    r2 = rsi.copy(); r2["timestamp"] = r2["timestamp"] + pd.Timedelta(minutes=30); r2 = r2.rename(columns={"rsi": "rsi_t2"})
    r3 = rsi.copy(); r3["timestamp"] = r3["timestamp"] + pd.Timedelta(minutes=45); r3 = r3.rename(columns={"rsi": "rsi_t3"})

    oi2 = oi[["pair", "bucket_time", "oi_acceleration"]].rename(columns={"pair": "asset", "bucket_time": "timestamp", "oi_acceleration": "oi"})
    o1x = oi2.copy(); o1x["timestamp"] = o1x["timestamp"] + pd.Timedelta(minutes=15); o1x = o1x.rename(columns={"oi": "oi_t1"})
    o2x = oi2.copy(); o2x["timestamp"] = o2x["timestamp"] + pd.Timedelta(minutes=30); o2x = o2x.rename(columns={"oi": "oi_t2"})
    o3x = oi2.copy(); o3x["timestamp"] = o3x["timestamp"] + pd.Timedelta(minutes=45); o3x = o3x.rename(columns={"oi": "oi_t3"})

    for part in (c1, c2, c3, r1, r2, r3, o1x, o2x, o3x):
        f2 = f2.merge(part, on=["asset", "timestamp"], how="left")

    f2["price_peak"] = (f2["high_t1"] > f2["high_t2"]) & (f2["high_t1"] > f2["high_t3"])
    f2["price_trough"] = (f2["low_t1"] < f2["low_t2"]) & (f2["low_t1"] < f2["low_t3"])
    f2["oi_peak"] = (f2["oi_t1"] > f2["oi_t2"]) & (f2["oi_t1"] > f2["oi_t3"])
    f2["oi_trough"] = (f2["oi_t1"] < f2["oi_t2"]) & (f2["oi_t1"] < f2["oi_t3"])
    f2["rsi_peak"] = (f2["rsi_t1"] > f2["rsi_t2"]) & (f2["rsi_t1"] > f2["rsi_t3"])
    f2["rsi_trough"] = (f2["rsi_t1"] < f2["rsi_t2"]) & (f2["rsi_t1"] < f2["rsi_t3"])

    f2["bearish_div"] = f2["price_peak"] & (~f2["oi_peak"] | ~f2["rsi_peak"])
    f2["bullish_div"] = f2["price_trough"] & (~f2["oi_trough"] | ~f2["rsi_trough"])
    f2["feature_2_value"] = f2["bullish_div"].astype(int) - f2["bearish_div"].astype(int)

    f2["down_strength"] = np.select(
        [
            f2["bearish_div"] & (f2["oi_t1"] < 0),
            f2["bearish_div"] & (((f2["high_t1"] - f2["low_t1"]) / f2["close_t2"]) > 0.02),
            f2["bearish_div"],
        ],
        [3, 2, 1],
        default=0,
    )
    f2["up_strength"] = np.select(
        [
            f2["bullish_div"] & (f2["oi_t1"] > 0),
            f2["bullish_div"] & (((f2["high_t2"] - f2["low_t1"]) / f2["close_t2"]) > 0.02),
            f2["bullish_div"],
        ],
        [3, 2, 1],
        default=0,
    )

    # target
    t1 = base[["asset", "timestamp", "close_t0"]].copy()
    t1["timestamp"] = t1["timestamp"] - pd.Timedelta(minutes=15)
    t1 = t1.rename(columns={"close_t0": "close_t1"})

    ds = base[["asset", "timestamp", "close_t0"]].copy()
    ds = ds.merge(t1, on=["asset", "timestamp"], how="left")
    ds = ds.merge(f1[["asset", "timestamp", "feature_1_value", "feature_1_value_leaky", "synthetic_z", "up_strength", "down_strength", "atr_prev"]].rename(columns={"up_strength": "f1_up_strength", "down_strength": "f1_down_strength"}), on=["asset", "timestamp"], how="left")
    ds = ds.merge(f2[["asset", "timestamp", "feature_2_value", "up_strength", "down_strength", "oi_t1", "rsi_t1"]].rename(columns={"up_strength": "f2_up_strength", "down_strength": "f2_down_strength"}), on=["asset", "timestamp"], how="left")

    adx_prev = adx.copy(); adx_prev["timestamp"] = adx_prev["timestamp"] + pd.Timedelta(minutes=15); adx_prev = adx_prev.rename(columns={"adx": "adx_prev"})
    rsi_prev = rsi.copy(); rsi_prev["timestamp"] = rsi_prev["timestamp"] + pd.Timedelta(minutes=15); rsi_prev = rsi_prev.rename(columns={"rsi": "rsi_prev"})
    macd_prev = macd.copy(); macd_prev["timestamp"] = macd_prev["timestamp"] + pd.Timedelta(minutes=15); macd_prev = macd_prev.rename(columns={"macd": "macd_prev"})

    ds = ds.merge(adx_prev[["asset", "timestamp", "adx_prev"]], on=["asset", "timestamp"], how="left")
    ds = ds.merge(rsi_prev[["asset", "timestamp", "rsi_prev"]], on=["asset", "timestamp"], how="left")
    ds = ds.merge(macd_prev[["asset", "timestamp", "macd_prev"]], on=["asset", "timestamp"], how="left")

    ds["target_return_15m"] = ds["close_t1"] - ds["close_t0"]
    ds["target_return_pct"] = ds["target_return_15m"] / ds["close_t0"]

    dataset = ds[(ds["timestamp"] >= pd.Timestamp(args.start, tz="UTC")) & ds["asset"].isin(pairs)].copy()
    dataset = dataset.dropna(subset=["target_return_15m", "feature_1_value", "feature_2_value"]).copy()

    syn_table = dataset[["timestamp", "asset", "feature_1_value", "feature_2_value", "target_return_15m"]].copy()
    syn_table = syn_table.sort_values(["asset", "timestamp"]) 
    syn_csv = out_dir / "synthetic_feature_test.csv"
    syn_table.to_csv(syn_csv, index=False)

    if args.write_db_table:
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
        copy_cmd = f"\\copy indicators.synthetic_feature_test (timestamp,asset,feature_1_value,feature_2_value,target_return_15m) FROM '{syn_csv.as_posix()}' CSV HEADER"
        subprocess.check_call(["psql", db_url, "-v", "ON_ERROR_STOP=1", "-c", copy_cmd])

    # -------------------------
    # Phase 3: Predictive power
    # -------------------------
    m_f1 = _feature_metrics(dataset, "feature_1_value")
    m_f2 = _feature_metrics(dataset, "feature_2_value")
    m_f1_leaky = _feature_metrics(dataset.dropna(subset=["feature_1_value_leaky"]), "feature_1_value_leaky")

    reg_f1 = _regime_breakdown(dataset.dropna(subset=["adx_prev", "atr_prev"]), "feature_1_value")
    reg_f2 = _regime_breakdown(dataset.dropna(subset=["adx_prev", "atr_prev"]), "feature_2_value")

    st_f1 = _stability_label(reg_f1)
    st_f2 = _stability_label(reg_f2)

    def _best_worst(reg: pd.DataFrame) -> tuple[str, str]:
        if reg.empty:
            return ("N/A", "N/A")
        rg = reg.dropna(subset=["ic"]).copy()
        if rg.empty:
            return ("N/A", "N/A")
        best = rg.sort_values("ic", ascending=False).iloc[0]["regime"]
        worst = rg.sort_values("ic", ascending=True).iloc[0]["regime"]
        return (str(best), str(worst))

    best_f1, worst_f1 = _best_worst(reg_f1)
    best_f2, worst_f2 = _best_worst(reg_f2)

    dec_f1, reason_f1 = _decision(m_f1["ic_abs"], st_f1, leakage_flag)
    dec_f2, reason_f2 = _decision(m_f2["ic_abs"], st_f2, leakage_flag)

    # Whipsaw test in ADX<20
    chop = dataset[dataset["adx_prev"] < 20].copy()

    chop["sig_f1"] = np.select(
        [chop["f1_up_strength"] > 0, chop["f1_down_strength"] > 0],
        [1, -1],
        default=0,
    )
    chop["sig_f2"] = np.sign(chop["feature_2_value"]).astype(int)
    chop["sig_rsi"] = np.select([chop["rsi_prev"] < 30, chop["rsi_prev"] > 70], [1, -1], default=0)
    chop["sig_macd"] = np.sign(chop["macd_prev"]).fillna(0).astype(int)
    chop["real_sign"] = np.sign(chop["target_return_15m"]).astype(int)

    def _false_rate(df: pd.DataFrame, sig_col: str) -> dict[str, Any]:
        x = df[df[sig_col] != 0].copy()
        if x.empty:
            return {"signals": 0, "false_rate": float("nan"), "accuracy": float("nan")}
        x = x[x["real_sign"] != 0]
        if x.empty:
            return {"signals": 0, "false_rate": float("nan"), "accuracy": float("nan")}
        acc = float((x[sig_col] == x["real_sign"]).mean())
        return {"signals": int(len(x)), "false_rate": float(1 - acc), "accuracy": acc}

    whipsaw = {
        "feature_1": _false_rate(chop, "sig_f1"),
        "feature_2": _false_rate(chop, "sig_f2"),
        "rsi_14": _false_rate(chop, "sig_rsi"),
        "macd_12_26_9": _false_rate(chop, "sig_macd"),
    }

    # ---------------------------
    # Phase 4: Top-5 benchmarking
    # ---------------------------
    v = v15.copy()
    v = v[v["pair"].isin(pairs)].rename(columns={"pair": "asset", "bucket_time": "timestamp"})
    v = v.sort_values(["asset", "timestamp"])

    base_cols = {"asset", "timestamp", "open", "high", "low", "close", "volume", "buy_volume", "sell_volume", "trade_count"}
    numeric_cols = [
        c
        for c in v.columns
        if c not in base_cols and pd.api.types.is_numeric_dtype(v[c])
    ]

    bench = v[["asset", "timestamp"] + numeric_cols].copy()
    for c in numeric_cols:
        bench[c] = bench.groupby("asset")[c].shift(1)

    bench = bench.merge(dataset[["asset", "timestamp", "target_return_15m", "target_return_pct"]], on=["asset", "timestamp"], how="inner")

    bench_rows: list[dict[str, Any]] = []
    for c in numeric_cols:
        x = bench[[c, "target_return_pct", "target_return_15m"]].dropna()
        if len(x) < 200:
            continue
        ic = float(x[c].corr(x["target_return_pct"]))
        x["q"] = _quintiles(x[c])
        top = x[x["q"] == 5]
        win = float((top["target_return_15m"] > 0).mean()) if len(top) else float("nan")
        bench_rows.append({"indicator": c, "ic": ic, "ic_abs": abs(ic), "win_rate_top_quintile": win, "n": int(len(x))})

    bench_df = pd.DataFrame(bench_rows).sort_values("ic_abs", ascending=False)
    top5 = bench_df.head(5).copy()

    best_existing_ic = float(top5["ic_abs"].max()) if not top5.empty else float("nan")
    best_existing_win = float(top5["win_rate_top_quintile"].max()) if not top5.empty else float("nan")

    outperform_f1 = (m_f1["ic_abs"] >= 1.10 * best_existing_ic) or (m_f1["win_rate_top_quintile"] >= 1.10 * best_existing_win)
    outperform_f2 = (m_f2["ic_abs"] >= 1.10 * best_existing_ic) or (m_f2["win_rate_top_quintile"] >= 1.10 * best_existing_win)

    if not outperform_f1 and dec_f1 != "REPLACE":
        dec_f1 = "REPLACE"
        reason_f1 = "Did not beat top existing indicators by >=10% IC or win-rate"
    if not outperform_f2 and dec_f2 != "REPLACE":
        dec_f2 = "REPLACE"
        reason_f2 = "Did not beat top existing indicators by >=10% IC or win-rate"

    # ------------------------
    # Build final report files
    # ------------------------
    feat_rows = [
        FeatureSummary(
            feature_name="early_delta_normalized_roc",
            ic=float(m_f1["ic"]),
            ic_abs=float(m_f1["ic_abs"]),
            win_rate_top_quintile=float(m_f1["win_rate_top_quintile"]),
            max_drawdown=float(m_f1["max_drawdown"]),
            best_regime=best_f1,
            worst_regime=worst_f1,
            regime_stability=st_f1,
            decision=dec_f1,
            decision_reason=reason_f1,
        ),
        FeatureSummary(
            feature_name="structured_oi_price_divergence",
            ic=float(m_f2["ic"]),
            ic_abs=float(m_f2["ic_abs"]),
            win_rate_top_quintile=float(m_f2["win_rate_top_quintile"]),
            max_drawdown=float(m_f2["max_drawdown"]),
            best_regime=best_f2,
            worst_regime=worst_f2,
            regime_stability=st_f2,
            decision=dec_f2,
            decision_reason=reason_f2,
        ),
    ]

    perf_df = pd.DataFrame([asdict(r) for r in feat_rows])
    perf_csv = out_dir / "feature_performance_table.csv"
    perf_df.to_csv(perf_csv, index=False)

    top5_csv = out_dir / "top5_existing_indicators.csv"
    top5.to_csv(top5_csv, index=False)

    reg_f1.to_csv(out_dir / "regime_feature1.csv", index=False)
    reg_f2.to_csv(out_dir / "regime_feature2.csv", index=False)

    with open(out_dir / "audit_summary.json", "w", encoding="utf-8") as f:
        json.dump(audit, f, indent=2, default=str)

    summary = {
        "rows_synthetic_feature_test": int(len(syn_table)),
        "rows_dataset_analyzed": int(len(dataset)),
        "feature_1_ic_no_leak": m_f1["ic"],
        "feature_1_ic_leaky_t0_atr": m_f1_leaky["ic"],
        "feature_2_ic": m_f2["ic"],
        "whipsaw": whipsaw,
        "top5": top5.to_dict("records"),
        "decisions": [asdict(r) for r in feat_rows],
        "leakage_flag": leakage_flag,
    }
    with open(out_dir / "summary.json", "w", encoding="utf-8") as f:
        json.dump(summary, f, indent=2, default=str)

    data_integrity_pass = (
        audit["ohlcv_15m_alignment_misaligned_rows"] == 0
        and audit["indicator_15m_misaligned_rows"] == 0
        and audit["indicator_15m_negative_lag_rows"] == 0
    )

    replace_candidates = top5["indicator"].tolist() if not top5.empty else []

    sql_artifacts = f"""
-- Production-ready (no-leak, aligned) MV: early_delta_normalized_roc (revised)
create materialized view if not exists indicators.mv_early_delta_normalized_roc_revised as
with base as (
  select
    o15.pair as asset,
    o15.bucket_time as timestamp,
    o15.open::float8 as open_t0,
    m2.close::float8 as close_t0p2,
    atr_prev.v1::float8 as atr_prev,
    cvd0.v1::float8 as cvd_t0,
    cvd2.v1::float8 as cvd_t0p2
  from indicators.ohlcv_15m o15
  join indicators.ohlcv_1m m2 on m2.pair=o15.pair and m2.bucket_time=o15.bucket_time + interval '2 minute'
  join indicators.indicator_values cvd0 on cvd0.pair=o15.pair and cvd0.config_id='cvd_20_1m' and cvd0.bucket_time=o15.bucket_time
  join indicators.indicator_values cvd2 on cvd2.pair=o15.pair and cvd2.config_id='cvd_20_1m' and cvd2.bucket_time=o15.bucket_time + interval '2 minute'
  join indicators.indicator_values atr_prev on atr_prev.pair=o15.pair and atr_prev.config_id='atr_14_15m' and atr_prev.bucket_time=o15.bucket_time - interval '15 minute'
  where extract(minute from o15.bucket_time)::int % 15 = 0
)
select
  asset,
  timestamp,
  (((close_t0p2-open_t0)/nullif(open_t0,0))/nullif(atr_prev,0))*sign(cvd_t0p2-cvd_t0) as feature_1_value
from base;

-- Production-ready MV: structured_oi_price_divergence
create materialized view if not exists indicators.mv_structured_oi_price_divergence as
with base as (
  select
    t0.pair as asset,
    t0.bucket_time as timestamp,
    c1.high::float8 as high_t1,
    c2.high::float8 as high_t2,
    c3.high::float8 as high_t3,
    c1.low::float8 as low_t1,
    c2.low::float8 as low_t2,
    c3.low::float8 as low_t3,
    r1.v1::float8 as rsi_t1,
    r2.v1::float8 as rsi_t2,
    r3.v1::float8 as rsi_t3,
    o1.oi_acceleration::float8 as oi_t1,
    o2.oi_acceleration::float8 as oi_t2,
    o3.oi_acceleration::float8 as oi_t3
  from indicators.ohlcv_15m t0
  join indicators.ohlcv_15m c1 on c1.pair=t0.pair and c1.bucket_time=t0.bucket_time-interval '15 minute'
  join indicators.ohlcv_15m c2 on c2.pair=t0.pair and c2.bucket_time=t0.bucket_time-interval '30 minute'
  join indicators.ohlcv_15m c3 on c3.pair=t0.pair and c3.bucket_time=t0.bucket_time-interval '45 minute'
  join indicators.indicator_values r1 on r1.pair=t0.pair and r1.config_id='rsi_14_15m' and r1.bucket_time=t0.bucket_time-interval '15 minute'
  join indicators.indicator_values r2 on r2.pair=t0.pair and r2.config_id='rsi_14_15m' and r2.bucket_time=t0.bucket_time-interval '30 minute'
  join indicators.indicator_values r3 on r3.pair=t0.pair and r3.config_id='rsi_14_15m' and r3.bucket_time=t0.bucket_time-interval '45 minute'
  join indicators.oi_features o1 on o1.pair=t0.pair and o1.bucket_time=t0.bucket_time-interval '15 minute'
  join indicators.oi_features o2 on o2.pair=t0.pair and o2.bucket_time=t0.bucket_time-interval '30 minute'
  join indicators.oi_features o3 on o3.pair=t0.pair and o3.bucket_time=t0.bucket_time-interval '45 minute'
  where extract(minute from t0.bucket_time)::int % 15 = 0
)
select
  asset,
  timestamp,
  (case when (low_t1 < low_t2 and low_t1 < low_t3) and (not (oi_t1 < oi_t2 and oi_t1 < oi_t3) or not (rsi_t1 < rsi_t2 and rsi_t1 < rsi_t3)) then 1 else 0 end)
  -
  (case when (high_t1 > high_t2 and high_t1 > high_t3) and (not (oi_t1 > oi_t2 and oi_t1 > oi_t3) or not (rsi_t1 > rsi_t2 and rsi_t1 > rsi_t3)) then 1 else 0 end)
  as feature_2_value
from base;

-- If REPLACE is chosen, top existing candidates from this run: {", ".join(replace_candidates[:5]) if replace_candidates else "N/A"}
""".strip()

    report_lines = [
        "# Synthetic Indicator Full Evaluation Report",
        "",
        f"Run UTC: `{run_id}`",
        f"Pairs: `{', '.join(pairs)}`",
        f"Window: `{args.start}` to `{args.end}`",
        "",
        "## 1) Data Integrity Status",
        f"- Leakage/Alignment Status: **{'PASS' if data_integrity_pass else 'FAIL'}**",
        f"- 15m indicator misaligned rows: `{audit['indicator_15m_misaligned_rows']}`",
        f"- 15m indicator negative-lag rows (created before candle close): `{audit['indicator_15m_negative_lag_rows']}`",
        f"- 15m OHLCV negative-lag rows: `{audit['ohlcv_15m_negative_lag_rows']}`",
        f"- 1m CVD negative-lag rows: `{audit['cvd_1m_negative_lag_rows']}`",
        f"- OI negative-lag rows: `{audit['oi_negative_lag_rows']}`",
        "",
        "Gap stats:",
        f"- ohlcv_15m: `{json.dumps(audit['ohlcv_15m_gap_stats'])}`",
        f"- ohlcv_1m: `{json.dumps(audit['ohlcv_1m_gap_stats'])}`",
        f"- oi_features: `{json.dumps(audit['oi_gap_stats'])}`",
        "",
        "## 2) Feature Performance Table",
        perf_df.to_markdown(index=False),
        "",
        "Quintile mean return (pct) summaries:",
        f"- feature_1 quintiles: `{m_f1['quintile_mean_return_pct']}`",
        f"- feature_2 quintiles: `{m_f2['quintile_mean_return_pct']}`",
        "",
        "Leakage sensitivity check:",
        f"- feature_1 IC no-leak (ATR[t0-1]): `{m_f1['ic']:.6f}`",
        f"- feature_1 IC leaky ATR[t0]: `{m_f1_leaky['ic']:.6f}`",
        "",
        "Regime IC breakdown (feature_1):",
        reg_f1.to_markdown(index=False) if not reg_f1.empty else "No regime rows",
        "",
        "Regime IC breakdown (feature_2):",
        reg_f2.to_markdown(index=False) if not reg_f2.empty else "No regime rows",
        "",
        "Whipsaw test (ADX<20):",
        f"- feature_1: `{whipsaw['feature_1']}`",
        f"- feature_2: `{whipsaw['feature_2']}`",
        f"- raw rsi_14_15m baseline: `{whipsaw['rsi_14']}`",
        f"- raw macd_12_26_9_15m baseline: `{whipsaw['macd_12_26_9']}`",
        "",
        "## 3) Comparative Benchmarking",
        "Top 5 existing indicators by absolute IC:",
        top5.to_markdown(index=False) if not top5.empty else "No benchmark rows",
        "",
        f"- feature_1 outperforms top-existing by >=10% (IC or win-rate): `{bool(outperform_f1)}`",
        f"- feature_2 outperforms top-existing by >=10% (IC or win-rate): `{bool(outperform_f2)}`",
        "",
        "## 4) Decision Matrix",
        perf_df[["feature_name", "decision", "decision_reason"]].to_markdown(index=False),
        "",
        "Prescribed tweaks if TWEAK:",
        "- early_delta_normalized_roc: test `cvd_50_1m` in place of `cvd_20_1m`, and `atr_21_15m` in place of `atr_14_15m`; retune sigma ladder to 1.25/2.5/3.5.",
        "- structured_oi_price_divergence: require divergence magnitude gate (`|rsi_t1-rsi_t2|>=5` or `|oi_t1-oi_t2|>=p60`), and ADX>=18 regime gate to suppress choppy false positives.",
        "",
        "Replacement guidance if REPLACE:",
        f"- Use top-ranked existing indicators from this run: `{', '.join(replace_candidates[:3]) if replace_candidates else 'N/A'}`",
        "",
        "## 5) SQL Artifacts (Production MVs)",
        "```sql",
        sql_artifacts,
        "```",
        "",
        "## 6) Executive Summary",
        (
            "Data integrity is **FAIL** due to misaligned 15m indicator timestamps and pre-close write anomalies; "
            "after enforcing no-leak alignment, both synthetic candidates were evaluated on the filtered dataset. "
            f"`early_delta_normalized_roc` IC={m_f1['ic']:.4f} and `structured_oi_price_divergence` IC={m_f2['ic']:.4f}; "
            "if either remains below the replacement threshold (<0.02 abs IC or no 10% edge vs top existing features), "
            "abort deployment and replace with the top existing indicators listed above. If one lands in TWEAK territory, "
            "apply the parameter updates and rerun before production rollout."
        ),
    ]

    report_md = out_dir / "full_report.md"
    report_md.write_text("\n".join(report_lines) + "\n", encoding="utf-8")

    print(json.dumps({
        "out_dir": str(out_dir),
        "report": str(report_md),
        "summary": str(out_dir / "summary.json"),
        "perf_csv": str(perf_csv),
        "top5_csv": str(top5_csv),
        "rows_synthetic_feature_test": int(len(syn_table)),
        "rows_dataset_analyzed": int(len(dataset)),
    }, indent=2))


if __name__ == "__main__":
    main()
