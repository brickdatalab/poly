from __future__ import annotations

from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from engine import REQUIRED_INPUT_CONTRACTS, evaluate_indicator, list_indicators  # noqa: E402


EXPECTED_CONTRACTS = {
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


def _latest_fully_closed_bucket() -> str:
    now = datetime.now(timezone.utc).replace(second=0, microsecond=0)
    base = now.replace(minute=(now.minute // 15) * 15)
    # Use previous 15m bucket to avoid in-flight decisions.
    bucket = base - timedelta(minutes=15)
    return bucket.isoformat().replace("+00:00", "Z")


def test_required_input_contracts_match_expected_docs() -> None:
    assert REQUIRED_INPUT_CONTRACTS == EXPECTED_CONTRACTS


@pytest.mark.integration
def test_live_all_indicators_have_no_missing_inputs() -> None:
    bucket = _latest_fully_closed_bucket()
    pairs = ["BTC-USD", "ETH-USD", "SOL-USD"]
    indicators = list_indicators()
    failures = []

    for indicator in indicators:
        payload = evaluate_indicator(indicator, pairs, bucket)
        for row in payload["results"]:
            if row["missing_count"] != 0 or row["status"] != "ready":
                failures.append(
                    {
                        "indicator": indicator,
                        "pair": row["pair"],
                        "status": row["status"],
                        "missing_inputs": row["missing_inputs"],
                    }
                )

    assert not failures, failures
