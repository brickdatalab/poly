#!/usr/bin/env python3
"""Hardcoded synthetic-indicator and codex-rule evaluator.

Purpose:
- Evaluate ALL synthetic indicator formulas in one Python script.
- Pull required variables from Supabase at runtime.
- Evaluate active codex rules against computed synthetic values.

Usage:
  python3 scripts/synthetic_indicators/evaluate_synthetic_rules_hardcoded.py
  python3 scripts/synthetic_indicators/evaluate_synthetic_rules_hardcoded.py --bucket-time "2026-02-12T15:00:00Z"
  python3 scripts/synthetic_indicators/evaluate_synthetic_rules_hardcoded.py --pairs BTC-USD,ETH-USD,SOL-USD --pretty
"""

from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from dataclasses import asdict, dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable


EPS = 1e-9

# Hardcoded thresholds used by the deployed ETH window-edge synthetic.
ETH_WINDOW_UP_T = 0.0719108856117475
ETH_WINDOW_DOWN_T = -0.0639929141611394
ETH_WINDOW_UP_ACC = 0.676471
ETH_WINDOW_DOWN_ACC = 0.592593


def parse_args() -> argparse.Namespace:
    ap = argparse.ArgumentParser(description="Evaluate hardcoded synthetic formulas and active codex rules.")
    ap.add_argument("--bucket-time", default=None, help="UTC bucket_time (15m boundary). Default: infer from now at t+2 logic.")
    ap.add_argument("--pairs", default="BTC-USD,ETH-USD,SOL-USD", help="Comma-separated pairs.")
    ap.add_argument("--pretty", action="store_true", help="Pretty-print JSON output.")
    ap.add_argument("--out", default=None, help="Optional explicit output JSON path.")
    return ap.parse_args()


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


def build_db_url(env: dict[str, str]) -> str:
    direct = (env.get("SUPABASE_DB_URL") or "").strip()
    if direct:
        return direct
    supabase_url = (env.get("SUPABASE_URL") or "").strip()
    password = (env.get("SUPABASE_DB_PASSWORD") or "").strip()
    if not supabase_url or not password:
        raise SystemExit("Missing DB config: set SUPABASE_DB_URL or SUPABASE_URL + SUPABASE_DB_PASSWORD")
    host = supabase_url.replace("https://", "").replace("http://", "").split("/")[0]
    ref = host.split(".")[0]
    return f"postgresql://postgres:{password}@db.{ref}.supabase.co:5432/postgres"


def psql_json(db_url: str, sql: str) -> list[dict[str, Any]]:
    wrapped = f"select coalesce(json_agg(t), '[]'::json)::text from ({sql.strip().rstrip(';')}) t"
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-t", "-c", wrapped],
        text=True,
    ).strip()
    if not out:
        return []
    return json.loads(out)


def parse_dt(text: str) -> datetime:
    return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def floor_15m(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def infer_bucket(now_utc: datetime) -> datetime:
    b = floor_15m(now_utc)
    # This script is intended to run at t+2m. If run earlier, evaluate previous bucket.
    if now_utc < b + timedelta(minutes=2):
        b = b - timedelta(minutes=15)
    return b


def to_float(v: Any) -> float | None:
    if v is None:
        return None
    try:
        return float(v)
    except Exception:
        return None


def sign(x: float | None) -> float:
    if x is None:
        return 0.0
    if x > 0:
        return 1.0
    if x < 0:
        return -1.0
    return 0.0


def stddev_samp(vals: list[float]) -> float | None:
    n = len(vals)
    if n < 2:
        return None
    mu = sum(vals) / n
    var = sum((v - mu) ** 2 for v in vals) / (n - 1)
    return math.sqrt(var)


@dataclass
class SyntheticResult:
    config_id: str
    pair: str
    bucket_time: str
    v1: float | None
    v2: float | None
    v3: float | None
    v4: float | None
    v5: float | None
    missing: list[str]


class DataStore:
    def __init__(self, rows: dict[str, list[dict[str, Any]]]) -> None:
        self.ohlcv_1m: dict[tuple[str, datetime], dict[str, Any]] = {}
        self.ohlcv_5m: dict[tuple[str, datetime], dict[str, Any]] = {}
        self.ohlcv_15m: dict[tuple[str, datetime], dict[str, Any]] = {}
        self.iv_exact: dict[tuple[str, str, datetime], dict[str, Any]] = {}
        self.iv_by_pc: dict[tuple[str, str], list[dict[str, Any]]] = {}
        self.ob_by_pair: dict[str, list[dict[str, Any]]] = {}
        self.oi_exact: dict[tuple[str, datetime], dict[str, Any]] = {}
        self.oi_by_pair: dict[str, list[dict[str, Any]]] = {}

        for r in rows["ohlcv_1m"]:
            bt = parse_dt(r["bucket_time"])
            self.ohlcv_1m[(r["pair"], bt)] = r
        for r in rows["ohlcv_5m"]:
            bt = parse_dt(r["bucket_time"])
            self.ohlcv_5m[(r["pair"], bt)] = r
        for r in rows["ohlcv_15m"]:
            bt = parse_dt(r["bucket_time"])
            self.ohlcv_15m[(r["pair"], bt)] = r
        for r in rows["indicator_values"]:
            bt = parse_dt(r["bucket_time"])
            k = (r["pair"], r["config_id"], bt)
            self.iv_exact[k] = r
            pc = (r["pair"], r["config_id"])
            self.iv_by_pc.setdefault(pc, []).append(r)
        for pc in list(self.iv_by_pc):
            self.iv_by_pc[pc].sort(key=lambda x: parse_dt(x["bucket_time"]))

        for r in rows["order_book_indicators"]:
            self.ob_by_pair.setdefault(r["pair"], []).append(r)
        for p in list(self.ob_by_pair):
            self.ob_by_pair[p].sort(key=lambda x: parse_dt(x["captured_at"]))

        for r in rows["oi_features"]:
            bt = parse_dt(r["bucket_time"])
            self.oi_exact[(r["pair"], bt)] = r
            self.oi_by_pair.setdefault(r["pair"], []).append(r)
        for p in list(self.oi_by_pair):
            self.oi_by_pair[p].sort(key=lambda x: parse_dt(x["bucket_time"]))

    def ohlcv(self, tf: str, pair: str, bt: datetime) -> dict[str, Any] | None:
        key = (pair, bt)
        if tf == "1m":
            return self.ohlcv_1m.get(key)
        if tf == "5m":
            return self.ohlcv_5m.get(key)
        if tf == "15m":
            return self.ohlcv_15m.get(key)
        return None

    def indicator_value(
        self,
        pair: str,
        config_id: str,
        bt: datetime,
        col: str = "v1",
        exact: bool = False,
    ) -> float | None:
        if exact:
            row = self.iv_exact.get((pair, config_id, bt))
            return to_float(row.get(col) if row else None)
        rows = self.iv_by_pc.get((pair, config_id), [])
        out: dict[str, Any] | None = None
        for r in rows:
            rbt = parse_dt(r["bucket_time"])
            if rbt <= bt:
                out = r
            else:
                break
        return to_float(out.get(col) if out else None)

    def order_book_latest(
        self,
        pair: str,
        le_ts: datetime,
        gt_ts: datetime | None = None,
    ) -> dict[str, Any] | None:
        rows = self.ob_by_pair.get(pair, [])
        for r in reversed(rows):
            ts = parse_dt(r["captured_at"])
            if ts <= le_ts and (gt_ts is None or ts > gt_ts):
                return r
        return None

    def order_book_spread_history(self, pair: str, lt_ts: datetime, limit: int) -> list[float]:
        rows = self.ob_by_pair.get(pair, [])
        vals: list[float] = []
        for r in reversed(rows):
            ts = parse_dt(r["captured_at"])
            if ts < lt_ts:
                s = to_float(r.get("spread_pct"))
                if s is not None:
                    vals.append(s)
                if len(vals) >= limit:
                    break
        vals.reverse()
        return vals

    def oi_row(self, pair: str, bt: datetime) -> dict[str, Any] | None:
        return self.oi_exact.get((pair, bt))

    def oi_history(self, pair: str, lt_ts: datetime, limit: int) -> list[dict[str, Any]]:
        rows = self.oi_by_pair.get(pair, [])
        out: list[dict[str, Any]] = []
        for r in reversed(rows):
            ts = parse_dt(r["bucket_time"])
            if ts < lt_ts:
                out.append(r)
                if len(out) >= limit:
                    break
        out.reverse()
        return out


def compute_syn_mtf_signed_efficiency_ratio(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    s5: list[dict[str, Any]] = []
    for i in range(0, 72):  # enough to pick 12 bars
        ts = bucket - timedelta(minutes=5 * i)
        row = ds.ohlcv("5m", pair, ts)
        if row is not None:
            s5.append({"bucket_time": ts, "close": to_float(row["close"])})
        if len(s5) >= 12:
            break
    s5 = sorted(s5, key=lambda x: x["bucket_time"])
    s15: list[dict[str, Any]] = []
    for i in range(0, 40):  # enough to pick 8 bars
        ts = bucket - timedelta(minutes=15 * i)
        row = ds.ohlcv("15m", pair, ts)
        if row is not None:
            s15.append({"bucket_time": ts, "close": to_float(row["close"])})
        if len(s15) >= 8:
            break
    s15 = sorted(s15, key=lambda x: x["bucket_time"])

    er5: float | None = None
    er15: float | None = None

    if len(s5) < 12:
        miss.append("missing_5m_history")
    else:
        c = [x["close"] for x in s5 if x["close"] is not None]
        if len(c) == 12:
            num5 = c[-1] - c[0]
            den5 = sum(abs(c[i] - c[i - 1]) for i in range(1, len(c)))
            if den5 == 0:
                miss.append("zero_path_5m")
            else:
                er5 = num5 / den5
        else:
            miss.append("missing_5m_close_values")

    if len(s15) < 8:
        miss.append("missing_15m_history")
    else:
        c = [x["close"] for x in s15 if x["close"] is not None]
        if len(c) == 8:
            num15 = c[-1] - c[0]
            den15 = sum(abs(c[i] - c[i - 1]) for i in range(1, len(c)))
            if den15 == 0:
                miss.append("zero_path_15m")
            else:
                er15 = num15 / den15
        else:
            miss.append("missing_15m_close_values")

    sig = (er5 * er15) if er5 is not None and er15 is not None else None
    return SyntheticResult(
        config_id="syn_mtf_signed_efficiency_ratio_5m12_15m8",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=sig,
        v2=er5,
        v3=er15,
        v4=abs(er5) if er5 is not None else None,
        v5=abs(er15) if er15 is not None else None,
        missing=miss,
    )


def compute_syn_rsi_velocity(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    rows = ds.iv_by_pc.get((pair, "rsi_7_5m"), [])
    rows = [r for r in rows if parse_dt(r["bucket_time"]) <= bucket][-30:]
    rows = sorted(rows, key=lambda x: parse_dt(x["bucket_time"]))
    rsi = [to_float(r.get("v1")) for r in rows]
    rsi = [x for x in rsi if x is not None]

    raw: float | None = None
    mu: float | None = None
    sd: float | None = None
    z: float | None = None
    rsi5_last: float | None = None

    if len(rsi) < 4:
        miss.append("missing_rsi_7_5m_history")
    else:
        rsi5_last = rsi[-1]
        raw = rsi[-1] - rsi[-4]
        diff3 = []
        for i in range(3, len(rsi)):
            diff3.append(rsi[i] - rsi[i - 3])
        if diff3:
            mu = sum(diff3) / len(diff3)
            sd = stddev_samp(diff3)
            sd_used = max(sd or 0.0, 0.5)
            z = (raw - mu) / sd_used if raw is not None and mu is not None else None
        else:
            miss.append("missing_diff3_history")
        sd_used = max(sd or 0.0, 0.5)
    if len(rsi) < 4:
        sd_used = 0.5

    rsi1h_last = ds.indicator_value(pair, "rsi_14_1h", bucket, "v1", exact=False)
    if rsi1h_last is None:
        miss.append("missing_rsi_14_1h")

    return SyntheticResult(
        config_id="syn_rsi_velocity_5m_3bar_z20",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=z,
        v2=raw,
        v3=rsi5_last,
        v4=rsi1h_last,
        v5=sd_used,
        missing=miss,
    )


def compute_syn_early_impulse_liq_align(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    t_eval = bucket + timedelta(minutes=2)

    o15 = ds.ohlcv("15m", pair, bucket)
    o1_eval = ds.ohlcv("1m", pair, t_eval)
    v_open15 = to_float(o15.get("open") if o15 else None)
    v_close2 = to_float(o1_eval.get("close") if o1_eval else None)
    atr1m = ds.indicator_value(pair, "atr_14_1m", t_eval, "v1", exact=True)

    if v_open15 is None:
        miss.append("missing_open_15m")
    if v_close2 is None:
        miss.append("missing_close_tplus2")
    if atr1m is None:
        miss.append("missing_atr_14_1m")

    r_early = math.log(v_close2 / v_open15) if v_open15 and v_close2 else None
    atr_pct = (atr1m / v_close2) if atr1m is not None and v_close2 not in (None, 0.0) else None
    r_vol = (r_early / atr_pct) if r_early is not None and atr_pct not in (None, 0.0) else None

    hist: list[float] = []
    for i in range(1, 721):
        ts = t_eval - timedelta(minutes=i)
        c = ds.ohlcv("1m", pair, ts)
        if not c:
            continue
        open_v = to_float(c.get("open"))
        close_v = to_float(c.get("close"))
        atr_v = ds.indicator_value(pair, "atr_14_1m", ts, "v1", exact=True)
        if open_v in (None, 0.0) or close_v in (None, 0.0) or atr_v in (None, 0.0):
            continue
        num = (close_v - open_v) / open_v
        den = atr_v / close_v
        if den != 0:
            hist.append(num / den)
    mu_r = (sum(hist) / len(hist)) if hist else None
    sd_r = stddev_samp(hist) if hist else None

    if r_vol is not None and sd_r not in (None, 0.0):
        z_r = (r_vol - mu_r) / sd_r if mu_r is not None else None
    else:
        z_r = r_vol

    ob = ds.order_book_latest(pair, t_eval, t_eval - timedelta(minutes=5))
    if ob is None:
        miss.append("missing_order_book")
        return SyntheticResult(
            config_id="syn_early_impulse_liq_align_tplus2",
            pair=pair,
            bucket_time=iso_z(bucket),
            v1=None,
            v2=z_r,
            v3=None,
            v4=None,
            v5=None,
            missing=miss,
        )

    imb = to_float(ob.get("imbalance"))
    spread = to_float(ob.get("spread_pct"))
    bid25 = to_float(ob.get("bid_depth_25bps"))
    ask25 = to_float(ob.get("ask_depth_25bps"))
    slip_sell = to_float(ob.get("slippage_sell_100"))
    slip_buy = to_float(ob.get("slippage_buy_100"))

    depth_skew = math.log(((bid25 or 0.0) + EPS) / ((ask25 or 0.0) + EPS))
    slip_skew = math.log(((slip_sell or 0.0) + EPS) / ((slip_buy or 0.0) + EPS))

    spread_hist = ds.order_book_spread_history(pair, t_eval, 720)
    mu_spread = (sum(spread_hist) / len(spread_hist)) if spread_hist else None
    sd_spread = stddev_samp(spread_hist) if spread_hist else None
    z_spread = ((spread - mu_spread) / sd_spread) if (spread is not None and mu_spread is not None and sd_spread not in (None, 0.0)) else 0.0

    if z_r is None or imb is None:
        v_liq = None
        signal = None
    else:
        v_liq = (
            0.60 * math.tanh(imb)
            + 0.30 * math.tanh(depth_skew)
            - 0.20 * math.tanh(slip_skew)
            - 0.30 * math.tanh(z_spread)
        )
        signal = z_r * v_liq

    return SyntheticResult(
        config_id="syn_early_impulse_liq_align_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=signal,
        v2=z_r,
        v3=v_liq,
        v4=depth_skew if ob else None,
        v5=z_spread if ob else None,
        missing=miss,
    )


def compute_syn_oi_funding_impulse(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    t_eval = bucket + timedelta(minutes=2)
    base = compute_syn_early_impulse_liq_align(ds, pair, bucket)
    z_r = base.v2

    oi_row = ds.oi_row(pair, bucket)
    if oi_row is None:
        miss.append("missing_oi_features")
        return SyntheticResult(
            config_id="syn_oi_funding_impulse_tplus2",
            pair=pair,
            bucket_time=iso_z(bucket),
            v1=None,
            v2=z_r,
            v3=None,
            v4=None,
            v5=None,
            missing=miss,
        )

    oi_acc = to_float(oi_row.get("oi_acceleration"))
    oi_roc = to_float(oi_row.get("oi_roc_1h"))
    fund = to_float(oi_row.get("funding_oi_pressure"))
    basis = to_float(oi_row.get("basis_pct"))

    hist = ds.oi_history(pair, bucket, 96)
    def col_vals(col: str) -> list[float]:
        vals = [to_float(r.get(col)) for r in hist]
        return [v for v in vals if v is not None]

    acc_h = col_vals("oi_acceleration")
    roc_h = col_vals("oi_roc_1h")
    fund_h = col_vals("funding_oi_pressure")
    basis_h = col_vals("basis_pct")

    def z(val: float | None, hist_vals: list[float]) -> float:
        if val is None:
            return 0.0
        mu = (sum(hist_vals) / len(hist_vals)) if hist_vals else None
        sd = stddev_samp(hist_vals) if hist_vals else None
        if mu is None or sd in (None, 0.0):
            return 0.0
        return (val - mu) / sd

    z_oi_acc = z(oi_acc, acc_h)
    z_oi_roc = z(oi_roc, roc_h)
    z_fund = z(fund, fund_h)
    z_basis = z(basis, basis_h)

    oi_support = 0.7 * z_oi_acc + 0.3 * z_oi_roc
    crowding = 0.6 * z_fund + 0.4 * z_basis

    signal = None
    if z_r is not None:
        signal = z_r * math.tanh(oi_support) - 0.50 * abs(z_r) * math.tanh(max(crowding, 0.0)) * sign(z_r)

    if oi_acc is None or oi_roc is None:
        miss.append("missing_oi_features_core")
    if fund is None or basis is None:
        miss.append("missing_funding_basis")

    return SyntheticResult(
        config_id="syn_oi_funding_impulse_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=signal,
        v2=z_r,
        v3=oi_support,
        v4=crowding,
        v5=z_oi_acc,
        missing=miss,
    )


def compute_syn_early_momentum_divergence(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    t_eval = bucket + timedelta(minutes=1)

    peak_rows: list[float] = []
    for off in (3, 2, 1):
        r = ds.ohlcv("1m", pair, bucket - timedelta(minutes=off))
        peak_rows.append(to_float(r.get("close") if r else None) or float("-inf"))
    peak3 = max(peak_rows) if peak_rows else None
    if peak3 in (None, float("-inf")):
        peak3 = None
    close_eval = to_float((ds.ohlcv("1m", pair, t_eval) or {}).get("close"))
    price_roc = ((close_eval - peak3) / peak3) if close_eval is not None and peak3 not in (None, 0.0) else None
    if price_roc is None:
        miss.append("missing_price_boundary")

    rsi_now = ds.indicator_value(pair, "rsi_7_5m", bucket, "v1", exact=False)
    rsi_prev = ds.indicator_value(pair, "rsi_7_5m", bucket - timedelta(minutes=5), "v1", exact=False)
    rsi_roc = ((rsi_now - rsi_prev) / 100.0) if rsi_now is not None and rsi_prev is not None else None

    macd_now = ds.indicator_value(pair, "macd_8_17_9_5m", bucket, "v3", exact=False)
    macd_prev = ds.indicator_value(pair, "macd_8_17_9_5m", bucket - timedelta(minutes=5), "v3", exact=False)
    macd_accel = (macd_now - macd_prev) if macd_now is not None and macd_prev is not None else None

    cvd_now = ds.indicator_value(pair, "cvd_20_1m", t_eval, "v1", exact=True)
    cvd_prev = ds.indicator_value(pair, "cvd_20_1m", t_eval - timedelta(minutes=5), "v1", exact=True)
    cvd_roc = ((cvd_now - cvd_prev) / (abs(cvd_prev) + EPS)) if cvd_now is not None and cvd_prev is not None else None

    if rsi_now is None:
        miss.append("missing_rsi_7_5m")
    if macd_now is None:
        miss.append("missing_macd_hist_5m")
    if cvd_now is None:
        miss.append("missing_cvd_20_1m")

    indicator_mom = None
    if rsi_roc is not None and macd_accel is not None and cvd_roc is not None:
        indicator_mom = (rsi_roc + sign(macd_accel) * 0.5 + cvd_roc) / 2.5

    emds = None
    if indicator_mom is not None and price_roc is not None:
        div_raw = indicator_mom - sign(price_roc)
        emds = div_raw * abs(price_roc) * 100.0

    return SyntheticResult(
        config_id="syn_early_momentum_divergence_tplus1",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=emds,
        v2=price_roc,
        v3=rsi_roc,
        v4=macd_accel,
        v5=cvd_roc,
        missing=miss,
    )


def compute_syn_order_flow_accel(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    t_eval = bucket + timedelta(minutes=2)

    cvd_now = ds.indicator_value(pair, "cvd_50_5m", bucket, "v1", exact=False)
    cvd_prev = ds.indicator_value(pair, "cvd_50_5m", bucket - timedelta(minutes=5), "v1", exact=False)
    cvd_prev2 = ds.indicator_value(pair, "cvd_50_5m", bucket - timedelta(minutes=10), "v1", exact=False)
    cvd_vel_now = (cvd_now - cvd_prev) if cvd_now is not None and cvd_prev is not None else None
    cvd_vel_prev = (cvd_prev - cvd_prev2) if cvd_prev is not None and cvd_prev2 is not None else None
    cvd_accel = (cvd_vel_now - cvd_vel_prev) if cvd_vel_now is not None and cvd_vel_prev is not None else None

    ob_now = ds.order_book_latest(pair, t_eval, t_eval - timedelta(minutes=5))
    ob_prev = ds.order_book_latest(pair, t_eval - timedelta(minutes=1), t_eval - timedelta(minutes=6))
    bid25 = to_float(ob_now.get("bid_depth_25bps") if ob_now else None)
    ask25 = to_float(ob_now.get("ask_depth_25bps") if ob_now else None)
    bid25_prev = to_float(ob_prev.get("bid_depth_25bps") if ob_prev else None)
    ask25_prev = to_float(ob_prev.get("ask_depth_25bps") if ob_prev else None)
    depth_ratio = to_float(ob_now.get("depth_ratio") if ob_now else None)

    ob_pressure_now = (
        ((bid25 - ask25) / (bid25 + ask25 + EPS))
        if bid25 is not None and ask25 is not None
        else None
    )
    ob_pressure_prev = (
        ((bid25_prev - ask25_prev) / (bid25_prev + ask25_prev + EPS))
        if bid25_prev is not None and ask25_prev is not None
        else None
    )
    ob_pressure_roc = (
        ob_pressure_now - ob_pressure_prev
        if ob_pressure_now is not None and ob_pressure_prev is not None
        else None
    )

    v_t0 = to_float((ds.ohlcv("15m", pair, bucket) or {}).get("volume"))
    prev_vols = []
    for off in (15, 30, 45):
        prev_vols.append(to_float((ds.ohlcv("15m", pair, bucket - timedelta(minutes=off)) or {}).get("volume")))
    prev_vols = [v for v in prev_vols if v is not None]
    v_avg3 = (sum(prev_vols) / len(prev_vols)) if len(prev_vols) == 3 else None
    vol_surge = ((v_t0 - v_avg3) / v_avg3) if v_t0 is not None and v_avg3 not in (None, 0.0) else None

    c_t0 = to_float((ds.ohlcv("1m", pair, bucket) or {}).get("close"))
    c_t2 = to_float((ds.ohlcv("1m", pair, t_eval) or {}).get("close"))
    price_roc = ((c_t2 - c_t0) / c_t0) if c_t0 not in (None, 0.0) and c_t2 is not None else None

    if cvd_now is None:
        miss.append("missing_cvd_50_5m")
    if ob_now is None:
        miss.append("missing_order_book")
    if v_t0 is None or v_avg3 is None:
        miss.append("missing_volume_context")
    if price_roc is None:
        miss.append("missing_price_boundary")

    flow_mom = None
    if cvd_accel is not None and ob_pressure_roc is not None and vol_surge is not None:
        flow_mom = cvd_accel * 0.4 + ob_pressure_roc * 0.3 + vol_surge * 0.3
    ofar = flow_mom * sign(price_roc) * 10.0 if flow_mom is not None and price_roc is not None else None

    return SyntheticResult(
        config_id="syn_order_flow_accel_regime_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=ofar,
        v2=cvd_accel,
        v3=ob_pressure_roc,
        v4=vol_surge,
        v5=depth_ratio,
        missing=miss,
    )


def compute_syn_window_edge_eth_nonrolling(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    if pair != "ETH-USD":
        return SyntheticResult(
            config_id="syn_window_edge_57to01_eth_nonrolling_tplus2",
            pair=pair,
            bucket_time=iso_z(bucket),
            v1=None,
            v2=None,
            v3=None,
            v4=ETH_WINDOW_UP_T,
            v5=ETH_WINDOW_DOWN_T,
            missing=["pair_scope_eth_only"],
        )

    open57 = to_float((ds.ohlcv("1m", pair, bucket - timedelta(minutes=3)) or {}).get("open"))
    close01 = to_float((ds.ohlcv("1m", pair, bucket + timedelta(minutes=1)) or {}).get("close"))
    if open57 is None:
        miss.append("missing_open_57")
    if close01 is None:
        miss.append("missing_close_01")
    pct = ((close01 - open57) / open57) * 100.0 if open57 not in (None, 0.0) and close01 is not None else None

    direction = None
    selected_acc = None
    if pct is not None:
        if pct > ETH_WINDOW_UP_T:
            direction = 1.0
            selected_acc = ETH_WINDOW_UP_ACC
        elif pct < ETH_WINDOW_DOWN_T:
            direction = -1.0
            selected_acc = ETH_WINDOW_DOWN_ACC
        else:
            direction = 0.0

    return SyntheticResult(
        config_id="syn_window_edge_57to01_eth_nonrolling_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=pct,
        v2=direction,
        v3=selected_acc,
        v4=ETH_WINDOW_UP_T,
        v5=ETH_WINDOW_DOWN_T,
        missing=miss,
    )


def compute_syn_cvd_divergence(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    cvd_t0 = ds.indicator_value(pair, "cvd_50_15m", bucket, "v1", exact=True)
    cvd_t5 = ds.indicator_value(pair, "cvd_50_15m", bucket - timedelta(minutes=75), "v1", exact=True)
    close_t0 = to_float((ds.ohlcv("15m", pair, bucket) or {}).get("close"))
    close_t5 = to_float((ds.ohlcv("15m", pair, bucket - timedelta(minutes=75)) or {}).get("close"))
    atr_15 = ds.indicator_value(pair, "atr_14_15m", bucket, "v1", exact=True)
    if cvd_t0 is None:
        miss.append("missing_cvd_t0")
    if cvd_t5 is None:
        miss.append("missing_cvd_t5")
    if close_t0 is None:
        miss.append("missing_close_t0")
    if close_t5 is None:
        miss.append("missing_close_t5")
    if atr_15 is None:
        miss.append("missing_atr_14_15m")

    # Last 20 CVD(15m) values.
    rows = ds.iv_by_pc.get((pair, "cvd_50_15m"), [])
    cvd_hist = [to_float(r.get("v1")) for r in rows if parse_dt(r["bucket_time"]) <= bucket]
    cvd_hist = [v for v in cvd_hist if v is not None][-20:]
    cvd_sd20 = stddev_samp(cvd_hist)
    if cvd_sd20 is None:
        miss.append("low_cvd_history")

    cvd_norm = None
    price_norm = None
    value = None
    if cvd_t0 is not None and cvd_t5 is not None:
        cvd_norm = (cvd_t0 - cvd_t5) / ((cvd_sd20 or 0.0) + EPS)
    if close_t0 is not None and close_t5 is not None and atr_15 is not None:
        price_norm = (close_t0 - close_t5) / ((atr_15 * math.sqrt(5.0)) + EPS)
    if cvd_norm is not None and price_norm is not None:
        value = cvd_norm - price_norm

    return SyntheticResult(
        config_id="syn_cvd_price_divergence_velocity_15m5_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=value,
        v2=cvd_norm,
        v3=price_norm,
        v4=cvd_sd20,
        v5=atr_15,
        missing=miss,
    )


def compute_syn_mtf_trend_confluence(ds: DataStore, pair: str, bucket: datetime) -> SyntheticResult:
    miss: list[str] = []
    st5 = ds.indicator_value(pair, "supertrend_10_3_5m", bucket, "v1", exact=True)
    st15 = ds.indicator_value(pair, "supertrend_10_3_15m", bucket, "v1", exact=True)
    ema9_t0 = ds.indicator_value(pair, "ema_9_15m", bucket, "v1", exact=True)
    ema9_t1 = ds.indicator_value(pair, "ema_9_15m", bucket - timedelta(minutes=15), "v1", exact=True)
    ema21_t0 = ds.indicator_value(pair, "ema_21_15m", bucket, "v1", exact=True)
    ema21_t1 = ds.indicator_value(pair, "ema_21_15m", bucket - timedelta(minutes=15), "v1", exact=True)

    o5 = ds.ohlcv("5m", pair, bucket)
    c5 = to_float((o5 or {}).get("close"))
    h5 = to_float((o5 or {}).get("high"))
    l5 = to_float((o5 or {}).get("low"))
    c15 = to_float((ds.ohlcv("15m", pair, bucket) or {}).get("close"))

    if st5 is None:
        miss.append("missing_supertrend_5m")
    if st15 is None:
        miss.append("missing_supertrend_15m")
    if ema9_t0 is None or ema9_t1 is None or ema21_t0 is None or ema21_t1 is None:
        miss.append("missing_ema_context")
    if c5 is None or h5 is None or l5 is None:
        miss.append("missing_ohlcv_5m")
    if c15 is None:
        miss.append("missing_ohlcv_15m_close")

    st5_dir = (1.0 if st5 < c5 else -1.0) if st5 is not None and c5 is not None else None
    st15_dir = (1.0 if st15 < c15 else -1.0) if st15 is not None and c15 is not None else None
    ema_slope = (
        (ema9_t0 - ema9_t1) - (ema21_t0 - ema21_t1)
        if None not in (ema9_t0, ema9_t1, ema21_t0, ema21_t1)
        else None
    )
    ema_dir = (1.0 if ema_slope > 0 else -1.0) if ema_slope is not None else None

    raw_score = (st5_dir + st15_dir + ema_dir) if None not in (st5_dir, st15_dir, ema_dir) else None
    atr_simple = (h5 - l5) if None not in (h5, l5) else None
    atr_pct = (atr_simple / c5) if atr_simple is not None and c5 not in (None, 0.0) else None
    vol_filter = (1.0 if atr_simple > 0.0012 * c5 else 0.2) if atr_simple is not None and c5 is not None else None
    value = (raw_score * vol_filter) if raw_score is not None and vol_filter is not None else None

    return SyntheticResult(
        config_id="syn_multitimeframe_trend_confluence_tplus2",
        pair=pair,
        bucket_time=iso_z(bucket),
        v1=value,
        v2=raw_score,
        v3=vol_filter,
        v4=ema_slope,
        v5=atr_pct,
        missing=miss,
    )


FORMULA_REGISTRY: dict[str, Callable[[DataStore, str, datetime], SyntheticResult]] = {
    "syn_mtf_signed_efficiency_ratio_5m12_15m8": compute_syn_mtf_signed_efficiency_ratio,
    "syn_rsi_velocity_5m_3bar_z20": compute_syn_rsi_velocity,
    "syn_early_impulse_liq_align_tplus2": compute_syn_early_impulse_liq_align,
    "syn_oi_funding_impulse_tplus2": compute_syn_oi_funding_impulse,
    "syn_early_momentum_divergence_tplus1": compute_syn_early_momentum_divergence,
    "syn_order_flow_accel_regime_tplus2": compute_syn_order_flow_accel,
    "syn_window_edge_57to01_eth_nonrolling_tplus2": compute_syn_window_edge_eth_nonrolling,
    "syn_cvd_price_divergence_velocity_15m5_tplus2": compute_syn_cvd_divergence,
    "syn_multitimeframe_trend_confluence_tplus2": compute_syn_mtf_trend_confluence,
}


def fetch_data(db_url: str, pairs: list[str], bucket: datetime) -> tuple[DataStore, list[dict[str, Any]], list[dict[str, Any]]]:
    pair_sql = ",".join(f"'{p}'" for p in pairs)
    t_eval = bucket + timedelta(minutes=2)
    start_1m = bucket - timedelta(hours=14)
    start_5m = bucket - timedelta(hours=8)
    start_15m = bucket - timedelta(hours=30)
    start_iv = bucket - timedelta(hours=30)
    start_ob = t_eval - timedelta(hours=14)
    start_oi = bucket - timedelta(hours=30)

    q_rules = f"""
      select rule_id,pair,config_id,operator,threshold,prediction,base_accuracy,is_active
      from indicators.codex_signal_rules
      where pair in ({pair_sql})
      order by pair, rule_id
    """
    q_configs = """
      select config_id, indicator_name, category, timeframe, decision_phase, is_active
      from indicators.synthetic_indicator_configs
      order by config_id
    """
    q_1m = f"""
      select pair,bucket_time,open,high,low,close,volume
      from indicators.ohlcv_1m
      where pair in ({pair_sql})
        and bucket_time >= '{iso_z(start_1m)}'::timestamptz
        and bucket_time <= '{iso_z(t_eval)}'::timestamptz
      order by pair,bucket_time
    """
    q_5m = f"""
      select pair,bucket_time,open,high,low,close,volume
      from indicators.ohlcv_5m
      where pair in ({pair_sql})
        and bucket_time >= '{iso_z(start_5m)}'::timestamptz
        and bucket_time <= '{iso_z(bucket)}'::timestamptz
      order by pair,bucket_time
    """
    q_15m = f"""
      select pair,bucket_time,open,high,low,close,volume
      from indicators.ohlcv_15m
      where pair in ({pair_sql})
        and bucket_time >= '{iso_z(start_15m)}'::timestamptz
        and bucket_time <= '{iso_z(bucket)}'::timestamptz
      order by pair,bucket_time
    """
    q_iv = f"""
      select pair,bucket_time,config_id,v1,v2,v3,v4,v5
      from indicators.indicator_values
      where pair in ({pair_sql})
        and bucket_time >= '{iso_z(start_iv)}'::timestamptz
        and bucket_time <= '{iso_z(t_eval)}'::timestamptz
      order by pair,config_id,bucket_time
    """
    q_ob = f"""
      select pair,captured_at,imbalance,spread_pct,bid_depth_25bps,ask_depth_25bps,slippage_buy_100,slippage_sell_100,depth_ratio
      from indicators.order_book_indicators
      where pair in ({pair_sql})
        and captured_at >= '{iso_z(start_ob)}'::timestamptz
        and captured_at <= '{iso_z(t_eval)}'::timestamptz
      order by pair,captured_at
    """
    q_oi = f"""
      select pair,bucket_time,oi_acceleration,oi_roc_1h,funding_oi_pressure,basis_pct
      from indicators.oi_features
      where pair in ({pair_sql})
        and bucket_time >= '{iso_z(start_oi)}'::timestamptz
        and bucket_time <= '{iso_z(bucket)}'::timestamptz
      order by pair,bucket_time
    """

    rules = psql_json(db_url, q_rules)
    configs = psql_json(db_url, q_configs)
    rows = {
        "ohlcv_1m": psql_json(db_url, q_1m),
        "ohlcv_5m": psql_json(db_url, q_5m),
        "ohlcv_15m": psql_json(db_url, q_15m),
        "indicator_values": psql_json(db_url, q_iv),
        "order_book_indicators": psql_json(db_url, q_ob),
        "oi_features": psql_json(db_url, q_oi),
    }
    return DataStore(rows), rules, configs


def evaluate_rules(
    rules: list[dict[str, Any]],
    synth: dict[tuple[str, str], SyntheticResult],
) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for r in rules:
        if not r.get("is_active"):
            continue
        pair = r["pair"]
        config_id = r["config_id"]
        sr = synth.get((pair, config_id))
        v1 = sr.v1 if sr else None
        threshold = to_float(r.get("threshold"))
        op = r.get("operator")
        passes = False
        if v1 is not None and threshold is not None:
            if op == ">=":
                passes = v1 >= threshold
            elif op == "<=":
                passes = v1 <= threshold
        out.append(
            {
                "rule_id": r["rule_id"],
                "pair": pair,
                "config_id": config_id,
                "operator": op,
                "threshold": threshold,
                "prediction": r.get("prediction"),
                "base_accuracy": to_float(r.get("base_accuracy")),
                "value_v1": v1,
                "has_input": v1 is not None,
                "passes": passes,
                "missing_formula_inputs": (sr.missing if sr else ["no_formula_result"]),
            }
        )
    out.sort(key=lambda x: (x["pair"], x["rule_id"]))
    return out


def summarize_by_pair(rule_eval: list[dict[str, Any]]) -> dict[str, dict[str, int]]:
    sums: dict[str, dict[str, int]] = {}
    for r in rule_eval:
        p = r["pair"]
        s = sums.setdefault(p, {"active_rules": 0, "with_input": 0, "passed": 0, "missing_input": 0})
        s["active_rules"] += 1
        if r["has_input"]:
            s["with_input"] += 1
        else:
            s["missing_input"] += 1
        if r["passes"]:
            s["passed"] += 1
    return sums


def fmt_float(v: float | None, digits: int = 8) -> str:
    if v is None:
        return "-"
    return f"{v:.{digits}g}"


def render_table(headers: list[str], rows: list[list[str]]) -> str:
    if not rows:
        rows = [["-" for _ in headers]]
    widths = [len(h) for h in headers]
    for r in rows:
        for i, c in enumerate(r):
            widths[i] = max(widths[i], len(c))
    sep = "+" + "+".join("-" * (w + 2) for w in widths) + "+"
    out = [sep]
    out.append("| " + " | ".join(headers[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    out.append(sep)
    for r in rows:
        out.append("| " + " | ".join(r[i].ljust(widths[i]) for i in range(len(headers))) + " |")
    out.append(sep)
    return "\n".join(out)


def short_missing(missing: list[str], limit: int = 3) -> str:
    if not missing:
        return "-"
    if len(missing) <= limit:
        return ", ".join(missing)
    return ", ".join(missing[:limit]) + f", +{len(missing) - limit} more"


def print_console_report(
    bucket: datetime,
    decision: datetime,
    out_path: Path,
    pair_summary: dict[str, dict[str, int]],
    rule_eval: list[dict[str, Any]],
) -> None:
    print("")
    print("Synthetic Rule Evaluation")
    print("=========================")
    print(f"Bucket Time   : {iso_z(bucket)}")
    print(f"Decision Time : {iso_z(decision)}")
    print(f"Output JSON   : {out_path}")
    print("")

    pair_rows: list[list[str]] = []
    for pair in sorted(pair_summary):
        s = pair_summary[pair]
        coverage = (100.0 * s["with_input"] / s["active_rules"]) if s["active_rules"] else 0.0
        pass_rate = (100.0 * s["passed"] / s["active_rules"]) if s["active_rules"] else 0.0
        pair_rows.append(
            [
                pair,
                str(s["active_rules"]),
                str(s["with_input"]),
                str(s["missing_input"]),
                f"{coverage:.1f}%",
                str(s["passed"]),
                f"{pass_rate:.1f}%",
            ]
        )
    print("Pair Summary")
    print(render_table(
        ["Pair", "Active", "With Input", "Missing", "Input Coverage", "Passed", "Pass Rate"],
        pair_rows,
    ))
    print("")

    by_pair: dict[str, list[dict[str, Any]]] = {}
    for r in rule_eval:
        by_pair.setdefault(r["pair"], []).append(r)

    for pair in sorted(by_pair):
        rows: list[list[str]] = []
        for r in by_pair[pair]:
            if not r["has_input"]:
                status = "NO_INPUT"
            elif r["passes"]:
                status = "PASS"
            else:
                status = "FAIL"
            rows.append(
                [
                    status,
                    r["rule_id"],
                    fmt_float(r["value_v1"]),
                    f"{r['operator']} {fmt_float(r['threshold'])}",
                    r["prediction"] or "-",
                    fmt_float(r["base_accuracy"], 6),
                    short_missing(r["missing_formula_inputs"]),
                ]
            )
        print(f"{pair} Rules")
        print(render_table(
            ["Status", "Rule", "Value(v1)", "Threshold", "Pred", "BaseAcc", "Missing Inputs"],
            rows,
        ))
        print("")

    fired = [r for r in rule_eval if r["passes"]]
    fired_rows = [
        [r["pair"], r["rule_id"], fmt_float(r["value_v1"]), r["prediction"] or "-", fmt_float(r["base_accuracy"], 6)]
        for r in fired
    ]
    print("Triggered Signals")
    print(render_table(["Pair", "Rule", "Value(v1)", "Prediction", "BaseAcc"], fired_rows))
    print("")


def main() -> None:
    args = parse_args()
    root = Path(__file__).resolve().parents[2]
    env = load_env(root)
    db_url = build_db_url(env)

    now_utc = datetime.now(timezone.utc)
    if args.bucket_time:
        bucket = parse_dt(args.bucket_time)
    else:
        bucket = infer_bucket(now_utc)

    pairs = [p.strip().upper() for p in args.pairs.split(",") if p.strip()]
    ds, rules, configs = fetch_data(db_url, pairs, bucket)

    synth_results: dict[tuple[str, str], SyntheticResult] = {}
    unknown_configs: set[str] = set()

    # Evaluate every active synthetic config for each pair.
    active_configs = [c["config_id"] for c in configs if c.get("is_active")]
    for pair in pairs:
        for cfg in active_configs:
            fn = FORMULA_REGISTRY.get(cfg)
            if fn is None:
                unknown_configs.add(cfg)
                continue
            synth_results[(pair, cfg)] = fn(ds, pair, bucket)

    rule_eval = evaluate_rules(rules, synth_results)
    pair_summary = summarize_by_pair(rule_eval)

    payload = {
        "generated_at_utc": iso_z(now_utc),
        "bucket_time_utc": iso_z(bucket),
        "decision_minute_utc": iso_z(bucket + timedelta(minutes=2)),
        "pairs": pairs,
        "unknown_configs_not_implemented": sorted(unknown_configs),
        "synthetic_results": [asdict(v) for v in sorted(synth_results.values(), key=lambda x: (x.pair, x.config_id))],
        "active_rule_evaluation": rule_eval,
        "summary_by_pair": pair_summary,
    }

    run_id = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    out_path = Path(args.out) if args.out else root / "scripts" / "output" / "synthetic_indicators" / f"hardcoded_eval_{run_id}.json"
    out_path.parent.mkdir(parents=True, exist_ok=True)
    out_path.write_text(json.dumps(payload, indent=2 if args.pretty else None))
    print_console_report(
        bucket=bucket,
        decision=bucket + timedelta(minutes=2),
        out_path=out_path,
        pair_summary=pair_summary,
        rule_eval=rule_eval,
    )


if __name__ == "__main__":
    main()
