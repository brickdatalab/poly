#!/usr/bin/env python3
from __future__ import annotations

import argparse
import json
import math
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable

EPS = 1e-9
DEFAULT_PAIRS = ["BTC-USD", "ETH-USD", "SOL-USD"]

REQUIRED_INPUT_CONTRACTS: dict[str, list[str]] = {
    "mtf_signed_efficiency_ratio": [
        "ohlcv_5m.close[12]",
        "ohlcv_15m.close[8]",
    ],
    "rsi_velocity_5m": [
        "iv.rsi_7_5m.v1[>=23]",
        "iv.rsi_14_1h.v1",
    ],
    "early_impulse_liquidity_alignment_2m": [
        "ohlcv_15m.open[t0]",
        "ohlcv_1m.close[t0+2m]",
        "iv.atr_14_1m.v1[t0+2m]",
        "ob.imbalance",
        "ob.bid_depth_25bps",
        "ob.ask_depth_25bps",
        "ob.slippage_buy_100",
        "ob.slippage_sell_100",
        "ob.spread_pct",
        "ob.spread_history[>=20]",
        "r_vol_z",
    ],
    "oi_funding_impulse_confirmation_2m": [
        "ohlcv_15m.open[t0]",
        "ohlcv_1m.close[t0+2m]",
        "iv.atr_14_1m.v1[t0+2m]",
        "oi.oi_acceleration",
        "oi.oi_roc_1h",
        "oi.funding_oi_pressure",
        "oi.basis_pct",
        "oi.history[>=20]",
        "r_vol_z",
    ],
    "early_momentum_divergence_score": [
        "ohlcv_1m.close[t0+1m]",
        "ohlcv_1m.close[t0-3m..t0-1m]",
        "iv.rsi_7_5m.v1[now,prev]",
        "iv.macd_8_17_9_5m.v3[now,prev]",
        "iv.cvd_20_1m.v1[t0+1m]",
        "iv.cvd_20_1m.v1[t0-4m]",
    ],
    "order_flow_acceleration_regime": [
        "iv.cvd_50_5m.v1[3]",
        "ob.now.bid_25",
        "ob.now.ask_25",
        "ob.prev.bid_25",
        "ob.prev.ask_25",
        "ohlcv_15m.volume[4]",
        "ohlcv_1m.close[t0]",
        "ohlcv_1m.close[t0+2m]",
    ],
    "cvd_price_divergence_velocity": [
        "iv.cvd_50_15m.v1[20]",
        "ohlcv_15m.close[20]",
        "iv.atr_14_15m.v1",
    ],
    "atr_normalized_reversal_pressure": [
        "iv.atr_14_5m.v1",
        "iv.macd_12_26_9_5m.v1[3]",
        "iv.macd_12_26_9_5m.v2[3]",
        "ohlcv_5m.close[4]",
        "ohlcv_15m.open[t0]",
        "ohlcv_1m.close[t0+1m]",
    ],
    "multitimeframe_trend_confluence": [
        "iv.supertrend_10_3_5m.v1",
        "iv.supertrend_10_3_15m.v1",
        "iv.ema_9_15m.v1[2]",
        "iv.ema_21_15m.v1[2]",
        "ohlcv_5m.close[t0]",
        "ohlcv_5m.high[t0]",
        "ohlcv_5m.low[t0]",
        "ohlcv_15m.close[t0]",
        "ohlcv_1m.close[t0+1m]",
    ],
    "rsi_volatility_normalized_velocity": [
        "iv.rsi_14_15m.v1[4]",
        "iv.atr_14_15m.v1",
        "ohlcv_15m.close[t0]",
        "ohlcv_1m.close[t0+1m]",
    ],
    "window_edge_57to01_nonrolling": [
        "ohlcv_1m.open[t0-3m]",
        "ohlcv_1m.close[t0+1m]",
    ],
}


@dataclass
class IndicatorSpec:
    name: str
    decision_phase_minutes: int
    evaluator: Callable[[str, str, datetime, datetime], dict[str, Any]]


def parse_dt(value: str) -> datetime:
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(timezone.utc)


def iso_z(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).replace(microsecond=0).isoformat().replace("+00:00", "Z")


def floor_15m(dt: datetime) -> datetime:
    return dt.replace(minute=(dt.minute // 15) * 15, second=0, microsecond=0)


def infer_bucket(now_utc: datetime, phase_min: int) -> datetime:
    bucket = floor_15m(now_utc)
    if now_utc < bucket + timedelta(minutes=phase_min):
        bucket -= timedelta(minutes=15)
    return bucket


def load_env(project_root: Path) -> dict[str, str]:
    env = dict(os.environ)
    env_file = project_root / ".env"
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


def quote(text: str) -> str:
    return "'" + text.replace("'", "''") + "'"


def psql_json(db_url: str, sql: str) -> list[dict[str, Any]]:
    wrapped = f"select coalesce(json_agg(t), '[]'::json)::text from ({sql.strip().rstrip(';')}) t"
    out = subprocess.check_output(
        ["psql", db_url, "-v", "ON_ERROR_STOP=1", "-P", "pager=off", "-A", "-t", "-c", wrapped],
        text=True,
    ).strip()
    if not out:
        return []
    return json.loads(out)


def to_float(value: Any) -> float | None:
    if value is None:
        return None
    try:
        return float(value)
    except Exception:
        return None


def sign(value: float | None) -> float:
    if value is None:
        return 0.0
    if value > 0:
        return 1.0
    if value < 0:
        return -1.0
    return 0.0


def mean(values: list[float]) -> float | None:
    if not values:
        return None
    return sum(values) / len(values)


def stddev_samp(values: list[float]) -> float | None:
    n = len(values)
    if n < 2:
        return None
    mu = sum(values) / n
    var = sum((v - mu) ** 2 for v in values) / (n - 1)
    return math.sqrt(var)


def table(headers: list[str], rows: list[list[Any]]) -> str:
    str_rows = [["" if c is None else str(c) for c in row] for row in rows]
    widths = [len(h) for h in headers]
    for row in str_rows:
        for i, cell in enumerate(row):
            widths[i] = max(widths[i], len(cell))
    sep = " | "
    out = []
    out.append(sep.join(h.ljust(widths[i]) for i, h in enumerate(headers)))
    out.append("-+-".join("-" * w for w in widths))
    for row in str_rows:
        out.append(sep.join(row[i].ljust(widths[i]) for i in range(len(headers))))
    return "\n".join(out)


def fetch_ohlcv(
    db_url: str,
    timeframe: str,
    pair: str,
    ts: datetime,
    *,
    exact: bool = False,
) -> dict[str, Any] | None:
    table_name = f"indicators.ohlcv_{timeframe}"
    comp = "=" if exact else "<="
    sql = f"""
      select bucket_time, open, high, low, close, volume
      from {table_name}
      where pair = {quote(pair)}
        and bucket_time {comp} {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit 1
    """
    rows = psql_json(db_url, sql)
    return rows[0] if rows else None


def fetch_event_open(db_url: str, pair: str, bucket: datetime) -> tuple[float | None, str | None]:
    """Return event open at t0, preferring 15m open and falling back to 1m open."""
    row_15m = fetch_ohlcv(db_url, "15m", pair, bucket, exact=True)
    open_15m = to_float(row_15m.get("open")) if row_15m else None
    if open_15m is not None:
        return open_15m, "ohlcv_15m.open[t0]"
    row_1m = fetch_ohlcv(db_url, "1m", pair, bucket, exact=True)
    open_1m = to_float(row_1m.get("open")) if row_1m else None
    if open_1m is not None:
        return open_1m, "ohlcv_1m.open[t0]"
    return None, None


def fetch_ohlcv_series(
    db_url: str,
    timeframe: str,
    pair: str,
    ts: datetime,
    limit: int,
) -> list[dict[str, Any]]:
    table_name = f"indicators.ohlcv_{timeframe}"
    sql = f"""
      select bucket_time, open, high, low, close, volume
      from {table_name}
      where pair = {quote(pair)}
        and bucket_time <= {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit {int(limit)}
    """
    rows = psql_json(db_url, sql)
    return list(reversed(rows))


def fetch_indicator_value(
    db_url: str,
    pair: str,
    config_id: str,
    ts: datetime,
    *,
    col: str = "v1",
    exact: bool = False,
) -> float | None:
    comp = "=" if exact else "<="
    sql = f"""
      select bucket_time, {col} as value
      from indicators.indicator_values
      where pair = {quote(pair)}
        and config_id = {quote(config_id)}
        and bucket_time {comp} {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit 1
    """
    rows = psql_json(db_url, sql)
    if not rows:
        return None
    return to_float(rows[0].get("value"))


def fetch_indicator_series(
    db_url: str,
    pair: str,
    config_id: str,
    ts: datetime,
    *,
    col: str = "v1",
    limit: int,
) -> list[float]:
    sql = f"""
      select bucket_time, {col} as value
      from indicators.indicator_values
      where pair = {quote(pair)}
        and config_id = {quote(config_id)}
        and bucket_time <= {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit {int(limit)}
    """
    rows = list(reversed(psql_json(db_url, sql)))
    vals: list[float] = []
    for r in rows:
        v = to_float(r.get("value"))
        if v is not None:
            vals.append(v)
    return vals


def fetch_orderbook_latest(db_url: str, pair: str, ts: datetime) -> dict[str, Any] | None:
    sql = f"""
      select captured_at, depth_ratio, imbalance, spread_pct,
             bid_depth_10bps, ask_depth_10bps,
             bid_depth_25bps, ask_depth_25bps,
             bid_depth_50bps, ask_depth_50bps,
             slippage_buy_100, slippage_sell_100
      from indicators.order_book_indicators
      where pair = {quote(pair)}
        and captured_at <= {quote(iso_z(ts))}::timestamptz
      order by captured_at desc
      limit 1
    """
    rows = psql_json(db_url, sql)
    return rows[0] if rows else None


def fetch_orderbook_prev(db_url: str, pair: str, ts: datetime) -> dict[str, Any] | None:
    sql = f"""
      select captured_at, depth_ratio, imbalance, spread_pct,
             bid_depth_10bps, ask_depth_10bps,
             bid_depth_25bps, ask_depth_25bps,
             bid_depth_50bps, ask_depth_50bps,
             slippage_buy_100, slippage_sell_100
      from indicators.order_book_indicators
      where pair = {quote(pair)}
        and captured_at < {quote(iso_z(ts))}::timestamptz
      order by captured_at desc
      limit 1
    """
    rows = psql_json(db_url, sql)
    return rows[0] if rows else None


def fetch_orderbook_series(db_url: str, pair: str, ts: datetime, limit: int) -> list[dict[str, Any]]:
    sql = f"""
      select captured_at, depth_ratio, imbalance, spread_pct,
             bid_depth_10bps, ask_depth_10bps,
             bid_depth_25bps, ask_depth_25bps,
             bid_depth_50bps, ask_depth_50bps,
             slippage_buy_100, slippage_sell_100
      from indicators.order_book_indicators
      where pair = {quote(pair)}
        and captured_at <= {quote(iso_z(ts))}::timestamptz
      order by captured_at desc
      limit {int(limit)}
    """
    return list(reversed(psql_json(db_url, sql)))


def fetch_oi_latest(db_url: str, pair: str, ts: datetime) -> dict[str, Any] | None:
    sql = f"""
      select bucket_time, oi_acceleration, oi_roc_1h, funding_oi_pressure, basis_pct
      from indicators.oi_features
      where pair = {quote(pair)}
        and bucket_time <= {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit 1
    """
    rows = psql_json(db_url, sql)
    return rows[0] if rows else None


def fetch_oi_series(db_url: str, pair: str, ts: datetime, limit: int) -> list[dict[str, Any]]:
    sql = f"""
      select bucket_time, oi_acceleration, oi_roc_1h, funding_oi_pressure, basis_pct
      from indicators.oi_features
      where pair = {quote(pair)}
        and bucket_time <= {quote(iso_z(ts))}::timestamptz
      order by bucket_time desc
      limit {int(limit)}
    """
    return list(reversed(psql_json(db_url, sql)))


def compute_r_vol_z(db_url: str, pair: str, decision_time: datetime, sample_limit: int = 720) -> tuple[float | None, float | None]:
    sql = f"""
      with joined as (
        select
          o15.bucket_time,
          o15.open as open15,
          o1.close as close1,
          iv.v1 as atr
        from indicators.ohlcv_15m o15
        join indicators.ohlcv_1m o1
          on o1.pair = o15.pair
         and o1.bucket_time = o15.bucket_time + interval '2 minute'
        join indicators.indicator_values iv
          on iv.pair = o15.pair
         and iv.config_id = 'atr_14_1m'
         and iv.bucket_time = o15.bucket_time + interval '2 minute'
        where o15.pair = {quote(pair)}
          and o15.bucket_time + interval '2 minute' <= {quote(iso_z(decision_time))}::timestamptz
        order by o15.bucket_time desc
        limit {int(sample_limit)}
      )
      select
        bucket_time,
        case when open15 = 0 or close1 is null then null else ln(close1 / open15) end as r_early,
        case when close1 = 0 or atr is null then null else atr / close1 end as atr_pct,
        case when open15 = 0 or close1 = 0 or atr is null then null else (ln(close1 / open15)) / nullif((atr / close1), 0) end as r_vol
      from joined
      order by bucket_time
    """
    rows = psql_json(db_url, sql)
    vals = [to_float(r.get("r_vol")) for r in rows]
    vals = [v for v in vals if v is not None]
    if not vals:
        return None, None
    latest = vals[-1]
    mu = mean(vals)
    sd = stddev_samp(vals)
    if mu is None or sd is None or sd <= EPS:
        return latest, None
    return latest, (latest - mu) / sd


def result_payload(
    indicator: str,
    pair: str,
    bucket: datetime,
    decision_time: datetime,
    required_inputs: list[str],
    inputs: dict[str, Any],
    calc: dict[str, Any],
    missing: list[str],
) -> dict[str, Any]:
    return {
        "indicator": indicator,
        "pair": pair,
        "bucket_time_utc": iso_z(bucket),
        "decision_time_utc": iso_z(decision_time),
        "status": "ready" if not missing else "missing_inputs",
        "required_inputs": required_inputs,
        "required_count": len(required_inputs),
        "present_count": len(required_inputs) - len(missing),
        "missing_count": len(missing),
        "missing_inputs": missing,
        "inputs": inputs,
        "calc": calc,
    }


def finalize_missing(inputs: dict[str, Any], required: list[str]) -> list[str]:
    missing = []
    for k in required:
        v = inputs.get(k)
        if v is None:
            missing.append(k)
    return missing


def evaluate_mtf_signed_efficiency_ratio(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    _ = decision_time
    required = REQUIRED_INPUT_CONTRACTS["mtf_signed_efficiency_ratio"]
    s5 = fetch_ohlcv_series(db_url, "5m", pair, bucket, 12)
    s15 = fetch_ohlcv_series(db_url, "15m", pair, bucket, 8)
    closes5 = [to_float(r.get("close")) for r in s5 if to_float(r.get("close")) is not None]
    closes15 = [to_float(r.get("close")) for r in s15 if to_float(r.get("close")) is not None]
    inputs = {
        "ohlcv_5m.close[12]": closes5 if len(closes5) >= 12 else None,
        "ohlcv_15m.close[8]": closes15 if len(closes15) >= 8 else None,
    }
    calc: dict[str, Any] = {}
    missing = finalize_missing(inputs, required)
    if not missing:
        num5 = closes5[-1] - closes5[0]
        den5 = sum(abs(closes5[i] - closes5[i - 1]) for i in range(1, len(closes5)))
        num15 = closes15[-1] - closes15[0]
        den15 = sum(abs(closes15[i] - closes15[i - 1]) for i in range(1, len(closes15)))
        er5 = num5 / max(den5, EPS)
        er15 = num15 / max(den15, EPS)
        calc = {"er_5m": er5, "er_15m": er15, "v1": er5 * er15}
    return result_payload("mtf_signed_efficiency_ratio", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_rsi_velocity_5m(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    _ = decision_time
    required = REQUIRED_INPUT_CONTRACTS["rsi_velocity_5m"]
    rsi7 = fetch_indicator_series(db_url, pair, "rsi_7_5m", bucket, col="v1", limit=24)
    rsi14_1h = fetch_indicator_value(db_url, pair, "rsi_14_1h", bucket, col="v1")
    inputs = {
        "iv.rsi_7_5m.v1[>=23]": rsi7 if len(rsi7) >= 23 else None,
        "iv.rsi_14_1h.v1": rsi14_1h,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        raw_series = [rsi7[i] - rsi7[i - 3] for i in range(3, len(rsi7))]
        raw = raw_series[-1]
        mu = mean(raw_series) or 0.0
        sd = stddev_samp(raw_series) or 0.0
        sd_used = max(sd, 0.5)
        calc = {
            "raw": raw,
            "mu": mu,
            "sd_used": sd_used,
            "v1": (raw - mu) / sd_used,
            "rsi_14_1h": rsi14_1h,
        }
    return result_payload("rsi_velocity_5m", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_early_impulse_liquidity_alignment_2m(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["early_impulse_liquidity_alignment_2m"]
    event_open, event_open_source = fetch_event_open(db_url, pair, bucket)
    o1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)
    atr = fetch_indicator_value(db_url, pair, "atr_14_1m", decision_time, col="v1", exact=True)
    ob_now = fetch_orderbook_latest(db_url, pair, decision_time)
    ob_hist = fetch_orderbook_series(db_url, pair, decision_time - timedelta(seconds=1), 60)
    spread_hist = [to_float(r.get("spread_pct")) for r in ob_hist]
    spread_hist = [v for v in spread_hist if v is not None]
    r_vol, z_r = compute_r_vol_z(db_url, pair, decision_time, sample_limit=720)

    inputs = {
        "ohlcv_15m.open[t0]": event_open,
        "ohlcv_1m.close[t0+2m]": to_float(o1.get("close")) if o1 else None,
        "iv.atr_14_1m.v1[t0+2m]": atr,
        "ob.imbalance": to_float(ob_now.get("imbalance")) if ob_now else None,
        "ob.bid_depth_25bps": to_float(ob_now.get("bid_depth_25bps")) if ob_now else None,
        "ob.ask_depth_25bps": to_float(ob_now.get("ask_depth_25bps")) if ob_now else None,
        "ob.slippage_buy_100": to_float(ob_now.get("slippage_buy_100")) if ob_now else None,
        "ob.slippage_sell_100": to_float(ob_now.get("slippage_sell_100")) if ob_now else None,
        "ob.spread_pct": to_float(ob_now.get("spread_pct")) if ob_now else None,
        "ob.spread_history[>=20]": spread_hist if len(spread_hist) >= 20 else None,
        "r_vol_z": z_r,
        "event_open_source": event_open_source,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        open15 = inputs["ohlcv_15m.open[t0]"]
        close1 = inputs["ohlcv_1m.close[t0+2m]"]
        imbalance = inputs["ob.imbalance"]
        bid25 = inputs["ob.bid_depth_25bps"]
        ask25 = inputs["ob.ask_depth_25bps"]
        s_buy = inputs["ob.slippage_buy_100"]
        s_sell = inputs["ob.slippage_sell_100"]
        spread = inputs["ob.spread_pct"]
        spread_mu = mean(spread_hist) or 0.0
        spread_sd = max(stddev_samp(spread_hist) or 0.0, EPS)
        spread_z = (spread - spread_mu) / spread_sd
        depth_skew = (bid25 - ask25) / max(abs(bid25) + abs(ask25), EPS)
        slippage_skew = (s_buy - s_sell) / max(abs(s_buy) + abs(s_sell), EPS)
        atr_pct = inputs["iv.atr_14_1m.v1[t0+2m]"] / max(close1, EPS)
        r_early = math.log(max(close1, EPS) / max(open15, EPS))
        r_vol_local = r_early / max(atr_pct, EPS)
        liq_align = (
            0.60 * math.tanh(imbalance)
            + 0.30 * math.tanh(depth_skew)
            - 0.20 * math.tanh(slippage_skew)
            - 0.30 * math.tanh(spread_z)
        )
        calc = {
            "r_early": r_early,
            "atr_pct": atr_pct,
            "r_vol_local": r_vol_local,
            "z_r": z_r,
            "depth_skew": depth_skew,
            "slippage_skew": slippage_skew,
            "spread_z": spread_z,
            "liq_align": liq_align,
            "v1": z_r * liq_align,
            "r_vol_series_latest": r_vol,
        }
    return result_payload("early_impulse_liquidity_alignment_2m", pair, bucket, decision_time, required, inputs, calc, missing)


def z_from_series(values: list[float], current: float) -> float | None:
    if len(values) < 3:
        return None
    mu = mean(values)
    sd = stddev_samp(values)
    if mu is None or sd is None or sd <= EPS:
        return None
    return (current - mu) / sd


def evaluate_oi_funding_impulse_confirmation_2m(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["oi_funding_impulse_confirmation_2m"]
    event_open, event_open_source = fetch_event_open(db_url, pair, bucket)
    o1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)
    atr = fetch_indicator_value(db_url, pair, "atr_14_1m", decision_time, col="v1", exact=True)
    oi_now = fetch_oi_latest(db_url, pair, decision_time)
    oi_hist = fetch_oi_series(db_url, pair, decision_time, 96)
    r_vol, z_r = compute_r_vol_z(db_url, pair, decision_time, sample_limit=720)

    inputs = {
        "ohlcv_15m.open[t0]": event_open,
        "ohlcv_1m.close[t0+2m]": to_float(o1.get("close")) if o1 else None,
        "iv.atr_14_1m.v1[t0+2m]": atr,
        "oi.oi_acceleration": to_float(oi_now.get("oi_acceleration")) if oi_now else None,
        "oi.oi_roc_1h": to_float(oi_now.get("oi_roc_1h")) if oi_now else None,
        "oi.funding_oi_pressure": to_float(oi_now.get("funding_oi_pressure")) if oi_now else None,
        "oi.basis_pct": to_float(oi_now.get("basis_pct")) if oi_now else None,
        "oi.history[>=20]": oi_hist if len(oi_hist) >= 20 else None,
        "r_vol_z": z_r,
        "event_open_source": event_open_source,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        acc_hist = [to_float(r.get("oi_acceleration")) for r in oi_hist]
        roc_hist = [to_float(r.get("oi_roc_1h")) for r in oi_hist]
        f_hist = [to_float(r.get("funding_oi_pressure")) for r in oi_hist]
        b_hist = [to_float(r.get("basis_pct")) for r in oi_hist]
        acc_vals = [v for v in acc_hist if v is not None]
        roc_vals = [v for v in roc_hist if v is not None]
        f_vals = [v for v in f_hist if v is not None]
        b_vals = [v for v in b_hist if v is not None]
        z_acc = z_from_series(acc_vals, inputs["oi.oi_acceleration"])
        z_roc = z_from_series(roc_vals, inputs["oi.oi_roc_1h"])
        z_f = z_from_series(f_vals, inputs["oi.funding_oi_pressure"])
        z_b = z_from_series(b_vals, inputs["oi.basis_pct"])
        if None in (z_acc, z_roc, z_f, z_b):
            missing.extend([
                k for k, v in {
                    "z_oi_acceleration": z_acc,
                    "z_oi_roc_1h": z_roc,
                    "z_funding_oi_pressure": z_f,
                    "z_basis_pct": z_b,
                }.items() if v is None
            ])
        else:
            oi_support = 0.7 * z_acc + 0.3 * z_roc
            crowding = 0.6 * z_f + 0.4 * z_b
            v1 = z_r * math.tanh(oi_support) - 0.50 * abs(z_r) * math.tanh(max(crowding, 0.0)) * sign(z_r)
            calc = {
                "z_r": z_r,
                "oi_support": oi_support,
                "crowding": crowding,
                "z_oi_acceleration": z_acc,
                "z_oi_roc_1h": z_roc,
                "z_funding_oi_pressure": z_f,
                "z_basis_pct": z_b,
                "v1": v1,
                "r_vol_series_latest": r_vol,
            }
    missing = sorted(set(missing))
    status_missing = missing if missing else []
    return result_payload("oi_funding_impulse_confirmation_2m", pair, bucket, decision_time, required, inputs, calc, status_missing)


def evaluate_early_momentum_divergence_score(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["early_momentum_divergence_score"]
    close_plus1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)
    prior = fetch_ohlcv_series(db_url, "1m", pair, bucket - timedelta(minutes=1), 3)
    rsi_series = fetch_indicator_series(db_url, pair, "rsi_7_5m", bucket, col="v1", limit=2)
    macd_hist_series = fetch_indicator_series(db_url, pair, "macd_8_17_9_5m", bucket, col="v3", limit=2)
    cvd_plus1 = fetch_indicator_value(db_url, pair, "cvd_20_1m", decision_time, col="v1", exact=True)
    cvd_minus4 = fetch_indicator_value(db_url, pair, "cvd_20_1m", bucket - timedelta(minutes=4), col="v1", exact=True)

    prior_closes = [to_float(r.get("close")) for r in prior if to_float(r.get("close")) is not None]
    inputs = {
        "ohlcv_1m.close[t0+1m]": to_float(close_plus1.get("close")) if close_plus1 else None,
        "ohlcv_1m.close[t0-3m..t0-1m]": prior_closes if len(prior_closes) == 3 else None,
        "iv.rsi_7_5m.v1[now,prev]": rsi_series if len(rsi_series) >= 2 else None,
        "iv.macd_8_17_9_5m.v3[now,prev]": macd_hist_series if len(macd_hist_series) >= 2 else None,
        "iv.cvd_20_1m.v1[t0+1m]": cvd_plus1,
        "iv.cvd_20_1m.v1[t0-4m]": cvd_minus4,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        price_roc = (inputs["ohlcv_1m.close[t0+1m]"] - max(prior_closes)) / max(max(prior_closes), EPS)
        rsi_roc = (rsi_series[-1] - rsi_series[-2]) / 100.0
        macd_accel = macd_hist_series[-1] - macd_hist_series[-2]
        cvd_roc = (cvd_plus1 - cvd_minus4) / max(abs(cvd_minus4), EPS)
        indicator_mom = (rsi_roc + 0.5 * sign(macd_accel) + cvd_roc) / 2.5
        v1 = (indicator_mom - sign(price_roc)) * abs(price_roc) * 100.0
        calc = {
            "price_roc": price_roc,
            "rsi_roc": rsi_roc,
            "macd_accel": macd_accel,
            "cvd_roc": cvd_roc,
            "indicator_mom": indicator_mom,
            "v1": v1,
        }
    return result_payload("early_momentum_divergence_score", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_order_flow_acceleration_regime(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["order_flow_acceleration_regime"]
    cvd5 = fetch_indicator_series(db_url, pair, "cvd_50_5m", bucket, col="v1", limit=3)
    ob_now = fetch_orderbook_latest(db_url, pair, decision_time)
    ob_prev = fetch_orderbook_prev(db_url, pair, decision_time)
    vol15_rows = fetch_ohlcv_series(db_url, "15m", pair, bucket, 4)
    vol15 = [to_float(r.get("volume")) for r in vol15_rows if to_float(r.get("volume")) is not None]
    c0 = fetch_ohlcv(db_url, "1m", pair, bucket, exact=True)
    c2 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)

    inputs = {
        "iv.cvd_50_5m.v1[3]": cvd5 if len(cvd5) >= 3 else None,
        "ob.now.bid_25": to_float(ob_now.get("bid_depth_25bps")) if ob_now else None,
        "ob.now.ask_25": to_float(ob_now.get("ask_depth_25bps")) if ob_now else None,
        "ob.prev.bid_25": to_float(ob_prev.get("bid_depth_25bps")) if ob_prev else None,
        "ob.prev.ask_25": to_float(ob_prev.get("ask_depth_25bps")) if ob_prev else None,
        "ohlcv_15m.volume[4]": vol15 if len(vol15) >= 4 else None,
        "ohlcv_1m.close[t0]": to_float(c0.get("close")) if c0 else None,
        "ohlcv_1m.close[t0+2m]": to_float(c2.get("close")) if c2 else None,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        cvd_accel = (cvd5[-1] - cvd5[-2]) - (cvd5[-2] - cvd5[-3])
        ob_now_pressure = (inputs["ob.now.bid_25"] - inputs["ob.now.ask_25"]) / max(
            abs(inputs["ob.now.bid_25"]) + abs(inputs["ob.now.ask_25"]), EPS
        )
        ob_prev_pressure = (inputs["ob.prev.bid_25"] - inputs["ob.prev.ask_25"]) / max(
            abs(inputs["ob.prev.bid_25"]) + abs(inputs["ob.prev.ask_25"]), EPS
        )
        ob_pressure_roc = ob_now_pressure - ob_prev_pressure
        vol_surge = (vol15[-1] - mean(vol15[-4:-1])) / max(abs(mean(vol15[-4:-1]) or 0.0), EPS)
        flow_mom = 0.4 * cvd_accel + 0.3 * ob_pressure_roc + 0.3 * vol_surge
        price_roc_2m = (inputs["ohlcv_1m.close[t0+2m]"] - inputs["ohlcv_1m.close[t0]"]) / max(inputs["ohlcv_1m.close[t0]"], EPS)
        calc = {
            "cvd_accel": cvd_accel,
            "ob_pressure_roc": ob_pressure_roc,
            "vol_surge": vol_surge,
            "flow_mom": flow_mom,
            "price_roc_2m": price_roc_2m,
            "v1": flow_mom * sign(price_roc_2m) * 10.0,
        }
    return result_payload("order_flow_acceleration_regime", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_cvd_price_divergence_velocity(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    _ = decision_time
    required = REQUIRED_INPUT_CONTRACTS["cvd_price_divergence_velocity"]
    cvd = fetch_indicator_series(db_url, pair, "cvd_50_15m", bucket, col="v1", limit=20)
    o15 = fetch_ohlcv_series(db_url, "15m", pair, bucket, 20)
    closes = [to_float(r.get("close")) for r in o15 if to_float(r.get("close")) is not None]
    atr = fetch_indicator_value(db_url, pair, "atr_14_15m", bucket, col="v1")
    inputs = {
        "iv.cvd_50_15m.v1[20]": cvd if len(cvd) >= 20 else None,
        "ohlcv_15m.close[20]": closes if len(closes) >= 20 else None,
        "iv.atr_14_15m.v1": atr,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        cvd_vel = cvd[-1] - cvd[-6]
        price_vel = closes[-1] - closes[-6]
        cvd_std = max(stddev_samp(cvd) or 0.0, EPS)
        cvd_norm = cvd_vel / cvd_std
        price_norm = price_vel / max(atr * math.sqrt(5.0), EPS)
        calc = {
            "cvd_vel": cvd_vel,
            "price_vel": price_vel,
            "cvd_std": cvd_std,
            "cvd_norm": cvd_norm,
            "price_norm": price_norm,
            "v1": cvd_norm - price_norm,
        }
    return result_payload("cvd_price_divergence_velocity", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_atr_normalized_reversal_pressure(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["atr_normalized_reversal_pressure"]
    atr = fetch_indicator_value(db_url, pair, "atr_14_5m", bucket, col="v1")
    macd_line = fetch_indicator_series(db_url, pair, "macd_12_26_9_5m", bucket, col="v1", limit=3)
    macd_signal = fetch_indicator_series(db_url, pair, "macd_12_26_9_5m", bucket, col="v2", limit=3)
    c5_rows = fetch_ohlcv_series(db_url, "5m", pair, bucket, 4)
    c5 = [to_float(r.get("close")) for r in c5_rows if to_float(r.get("close")) is not None]
    event_open, event_open_source = fetch_event_open(db_url, pair, bucket)
    c1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)

    inputs = {
        "iv.atr_14_5m.v1": atr,
        "iv.macd_12_26_9_5m.v1[3]": macd_line if len(macd_line) >= 3 else None,
        "iv.macd_12_26_9_5m.v2[3]": macd_signal if len(macd_signal) >= 3 else None,
        "ohlcv_5m.close[4]": c5 if len(c5) >= 4 else None,
        "ohlcv_15m.open[t0]": event_open,
        "ohlcv_1m.close[t0+1m]": to_float(c1.get("close")) if c1 else None,
        "event_open_source": event_open_source,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        price_extension = (c5[-1] - c5[-4]) / max(atr, EPS)
        hist = [macd_line[i] - macd_signal[i] for i in range(3)]
        is_hist_peak = hist[1] > hist[0] and hist[1] > hist[2]
        immediate_reversal = (price_extension > 0 and inputs["ohlcv_1m.close[t0+1m]"] < inputs["ohlcv_15m.open[t0]"]) or (
            price_extension < 0 and inputs["ohlcv_1m.close[t0+1m]"] > inputs["ohlcv_15m.open[t0]"]
        )
        reversal_pressure = abs(price_extension) * (1.0 if is_hist_peak else 0.4) * (1.5 if immediate_reversal else 0.7)
        calc = {
            "price_extension": price_extension,
            "macd_hist_t2": hist[0],
            "macd_hist_t1": hist[1],
            "macd_hist_t0": hist[2],
            "is_hist_peak": is_hist_peak,
            "immediate_reversal": immediate_reversal,
            "v1": reversal_pressure,
        }
    return result_payload("atr_normalized_reversal_pressure", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_multitimeframe_trend_confluence(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["multitimeframe_trend_confluence"]
    st5 = fetch_indicator_value(db_url, pair, "supertrend_10_3_5m", bucket, col="v1")
    st15 = fetch_indicator_value(db_url, pair, "supertrend_10_3_15m", bucket, col="v1")
    ema9 = fetch_indicator_series(db_url, pair, "ema_9_15m", bucket, col="v1", limit=2)
    ema21 = fetch_indicator_series(db_url, pair, "ema_21_15m", bucket, col="v1", limit=2)
    o5 = fetch_ohlcv(db_url, "5m", pair, bucket, exact=False)
    o15 = fetch_ohlcv(db_url, "15m", pair, bucket, exact=False)
    c1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)

    inputs = {
        "iv.supertrend_10_3_5m.v1": st5,
        "iv.supertrend_10_3_15m.v1": st15,
        "iv.ema_9_15m.v1[2]": ema9 if len(ema9) >= 2 else None,
        "iv.ema_21_15m.v1[2]": ema21 if len(ema21) >= 2 else None,
        "ohlcv_5m.close[t0]": to_float(o5.get("close")) if o5 else None,
        "ohlcv_5m.high[t0]": to_float(o5.get("high")) if o5 else None,
        "ohlcv_5m.low[t0]": to_float(o5.get("low")) if o5 else None,
        "ohlcv_15m.close[t0]": to_float(o15.get("close")) if o15 else None,
        "ohlcv_1m.close[t0+1m]": to_float(c1.get("close")) if c1 else None,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        st_5m_dir = 1.0 if st5 < inputs["ohlcv_5m.close[t0]"] else -1.0
        st_15m_dir = 1.0 if st15 < inputs["ohlcv_15m.close[t0]"] else -1.0
        ema_slope = (ema9[-1] - ema9[-2]) - (ema21[-1] - ema21[-2])
        ema_dir = 1.0 if ema_slope > 0 else -1.0
        score = st_5m_dir + st_15m_dir + ema_dir
        atr_5m = inputs["ohlcv_5m.high[t0]"] - inputs["ohlcv_5m.low[t0]"]
        vol_filter = 1.0 if atr_5m > 0.0012 * inputs["ohlcv_5m.close[t0]"] else 0.2
        confluence = score * vol_filter
        calc = {
            "st_5m_dir": st_5m_dir,
            "st_15m_dir": st_15m_dir,
            "ema_slope": ema_slope,
            "ema_dir": ema_dir,
            "score": score,
            "atr_5m": atr_5m,
            "vol_filter": vol_filter,
            "v1": confluence,
        }
    return result_payload("multitimeframe_trend_confluence", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_rsi_volatility_normalized_velocity(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["rsi_volatility_normalized_velocity"]
    rsi = fetch_indicator_series(db_url, pair, "rsi_14_15m", bucket, col="v1", limit=4)
    atr = fetch_indicator_value(db_url, pair, "atr_14_15m", bucket, col="v1")
    o15 = fetch_ohlcv(db_url, "15m", pair, bucket, exact=False)
    c1 = fetch_ohlcv(db_url, "1m", pair, decision_time, exact=True)
    inputs = {
        "iv.rsi_14_15m.v1[4]": rsi if len(rsi) >= 4 else None,
        "iv.atr_14_15m.v1": atr,
        "ohlcv_15m.close[t0]": to_float(o15.get("close")) if o15 else None,
        "ohlcv_1m.close[t0+1m]": to_float(c1.get("close")) if c1 else None,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        rsi_vel = (rsi[-1] - rsi[-4]) / 3.0
        vol_norm = atr / max(inputs["ohlcv_15m.close[t0]"], EPS)
        early_confirm = sign(inputs["ohlcv_1m.close[t0+1m]"] - inputs["ohlcv_15m.close[t0]"])
        calc = {
            "rsi_vel": rsi_vel,
            "vol_norm": vol_norm,
            "early_confirm": early_confirm,
            "v1": (rsi_vel / max(vol_norm, EPS)) * early_confirm,
        }
    return result_payload("rsi_volatility_normalized_velocity", pair, bucket, decision_time, required, inputs, calc, missing)


def evaluate_window_edge_57to01_nonrolling(db_url: str, pair: str, bucket: datetime, decision_time: datetime) -> dict[str, Any]:
    required = REQUIRED_INPUT_CONTRACTS["window_edge_57to01_nonrolling"]
    open_row = fetch_ohlcv(db_url, "1m", pair, bucket - timedelta(minutes=3), exact=True)
    close_row = fetch_ohlcv(db_url, "1m", pair, decision_time - timedelta(minutes=1), exact=True)
    open_1m = to_float(open_row.get("open")) if open_row else None
    close_1m = to_float(close_row.get("close")) if close_row else None

    inputs = {
        "ohlcv_1m.open[t0-3m]": open_1m,
        "ohlcv_1m.close[t0+1m]": close_1m,
    }
    missing = finalize_missing(inputs, required)
    calc: dict[str, Any] = {}
    if not missing:
        v1 = ((close_1m - open_1m) / max(open_1m, EPS)) * 100.0
        direction_code = 0
        if v1 > 0:
            direction_code = 1
        elif v1 < 0:
            direction_code = -1
        calc = {
            "v1": v1,
            "v2": direction_code,
        }
    return result_payload("window_edge_57to01_nonrolling", pair, bucket, decision_time, required, inputs, calc, missing)


EVALUATORS: dict[str, IndicatorSpec] = {
    "mtf_signed_efficiency_ratio": IndicatorSpec("mtf_signed_efficiency_ratio", 1, evaluate_mtf_signed_efficiency_ratio),
    "rsi_velocity_5m": IndicatorSpec("rsi_velocity_5m", 1, evaluate_rsi_velocity_5m),
    "early_impulse_liquidity_alignment_2m": IndicatorSpec(
        "early_impulse_liquidity_alignment_2m", 2, evaluate_early_impulse_liquidity_alignment_2m
    ),
    "oi_funding_impulse_confirmation_2m": IndicatorSpec(
        "oi_funding_impulse_confirmation_2m", 2, evaluate_oi_funding_impulse_confirmation_2m
    ),
    "early_momentum_divergence_score": IndicatorSpec("early_momentum_divergence_score", 1, evaluate_early_momentum_divergence_score),
    "order_flow_acceleration_regime": IndicatorSpec("order_flow_acceleration_regime", 2, evaluate_order_flow_acceleration_regime),
    "cvd_price_divergence_velocity": IndicatorSpec("cvd_price_divergence_velocity", 2, evaluate_cvd_price_divergence_velocity),
    "atr_normalized_reversal_pressure": IndicatorSpec("atr_normalized_reversal_pressure", 1, evaluate_atr_normalized_reversal_pressure),
    "multitimeframe_trend_confluence": IndicatorSpec("multitimeframe_trend_confluence", 1, evaluate_multitimeframe_trend_confluence),
    "rsi_volatility_normalized_velocity": IndicatorSpec("rsi_volatility_normalized_velocity", 1, evaluate_rsi_volatility_normalized_velocity),
    "window_edge_57to01_nonrolling": IndicatorSpec("window_edge_57to01_nonrolling", 2, evaluate_window_edge_57to01_nonrolling),
}


def evaluate_indicator(indicator: str, pairs: list[str], bucket_time: str | None = None) -> dict[str, Any]:
    if indicator not in EVALUATORS:
        raise SystemExit(f"Unsupported indicator: {indicator}")
    spec = EVALUATORS[indicator]
    project_root = Path(__file__).resolve().parents[2]
    syn_root = Path(__file__).resolve().parents[1]
    env = load_env(project_root)
    db_url = build_db_url(env)
    now = datetime.now(timezone.utc)
    bucket = parse_dt(bucket_time) if bucket_time else infer_bucket(now, spec.decision_phase_minutes)
    decision_time = bucket + timedelta(minutes=spec.decision_phase_minutes)

    results = [spec.evaluator(db_url, pair, bucket, decision_time) for pair in pairs]
    payload = {
        "indicator": indicator,
        "decision_phase_minutes": spec.decision_phase_minutes,
        "bucket_time_utc": iso_z(bucket),
        "decision_time_utc": iso_z(decision_time),
        "generated_at_utc": iso_z(now),
        "results": results,
    }
    out_dir = syn_root / "output"
    out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y%m%dT%H%M%SZ")
    out_path = out_dir / f"{indicator}_input_check_{stamp}.json"
    out_path.write_text(json.dumps(payload, indent=2))
    payload["output_path"] = str(out_path)
    return payload


def print_payload(payload: dict[str, Any]) -> None:
    print(f"indicator={payload['indicator']}")
    print(f"bucket_time_utc={payload['bucket_time_utc']}")
    print(f"decision_time_utc={payload['decision_time_utc']}")
    print(f"output={payload['output_path']}")
    print()

    headers = ["pair", "status", "required", "present", "missing"]
    rows = []
    for r in payload["results"]:
        rows.append([r["pair"], r["status"], r["required_count"], r["present_count"], r["missing_count"]])
    print(table(headers, rows))

    detail_rows = []
    for r in payload["results"]:
        if r["missing_inputs"]:
            for m in r["missing_inputs"]:
                detail_rows.append([r["pair"], m])
    if detail_rows:
        print("\nMISSING INPUT DETAILS")
        print(table(["pair", "missing_input"], detail_rows))
    else:
        print("\nMISSING INPUT DETAILS")
        print("none")


def parse_pairs(text: str) -> list[str]:
    pairs = [p.strip() for p in text.split(",") if p.strip()]
    return pairs if pairs else list(DEFAULT_PAIRS)


def run_indicator_cli(indicator: str) -> int:
    ap = argparse.ArgumentParser(description=f"Input-integrity validator for {indicator}")
    ap.add_argument("--pairs", default=",".join(DEFAULT_PAIRS), help="Comma-separated pairs")
    ap.add_argument("--bucket-time", default=None, help="Optional UTC bucket_time override")
    ap.add_argument("--pretty", action="store_true", help="Print table output")
    ap.add_argument("--strict", action="store_true", help="Exit non-zero if any pair has missing input")
    args = ap.parse_args()

    payload = evaluate_indicator(indicator, parse_pairs(args.pairs), args.bucket_time)
    if args.pretty:
        print_payload(payload)
    else:
        print(json.dumps(payload, indent=2))

    any_missing = any(r["missing_count"] > 0 for r in payload["results"])
    return 1 if args.strict and any_missing else 0


def list_indicators() -> list[str]:
    return list(EVALUATORS.keys())
