from __future__ import annotations

from pathlib import Path
import sys

SCRIPTS_DIR = Path(__file__).resolve().parents[1] / "scripts"
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))

from engine import apply_decision_logic


def _row(pair: str = "BTC-USD", calc: dict | None = None, inputs: dict | None = None) -> dict:
    return {
        "pair": pair,
        "status": "ready",
        "calc": calc or {},
        "inputs": inputs or {},
    }


def test_mtf_signed_efficiency_ratio_down_trigger() -> None:
    out = apply_decision_logic(
        "mtf_signed_efficiency_ratio",
        _row(calc={"v1": -0.25, "er_5m": -0.3, "er_15m": 0.4}),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_rsi_velocity_5m_up_trigger() -> None:
    out = apply_decision_logic(
        "rsi_velocity_5m",
        _row(calc={"v1": 1.6, "rsi_14_1h": 50}),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_early_impulse_liquidity_alignment_2m_down_trigger() -> None:
    out = apply_decision_logic(
        "early_impulse_liquidity_alignment_2m",
        _row(calc={"v1": -1.5, "spread_z": 1.2}),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_oi_funding_impulse_confirmation_2m_up_trigger() -> None:
    out = apply_decision_logic(
        "oi_funding_impulse_confirmation_2m",
        _row(calc={"v1": 1.2}),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_early_momentum_divergence_score_down_trigger() -> None:
    out = apply_decision_logic(
        "early_momentum_divergence_score",
        _row(calc={"v1": -1.6}),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_order_flow_acceleration_regime_up_trigger() -> None:
    out = apply_decision_logic(
        "order_flow_acceleration_regime",
        _row(calc={"v1": 1.0}, inputs={"ob.now.depth_ratio": 1.2}),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_cvd_price_divergence_velocity_up_trigger() -> None:
    out = apply_decision_logic(
        "cvd_price_divergence_velocity",
        _row(calc={"v1": 1.5, "price_vel": -10}),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_atr_normalized_reversal_pressure_down_trigger() -> None:
    out = apply_decision_logic(
        "atr_normalized_reversal_pressure",
        _row(
            calc={"price_extension": 2.0, "is_hist_peak": True},
            inputs={"ohlcv_1m.close[t0+1m]": 90.0, "ohlcv_15m.open[t0]": 100.0, "iv.atr_14_5m.v1": 10.0},
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_multitimeframe_trend_confluence_up_trigger() -> None:
    out = apply_decision_logic(
        "multitimeframe_trend_confluence",
        _row(calc={"v1": 2.1}, inputs={"ohlcv_1m.close[t0+1m]": 105.0, "iv.ema_9_15m.v1[2]": [100.0, 101.0]}),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_rsi_volatility_normalized_velocity_down_trigger() -> None:
    out = apply_decision_logic(
        "rsi_volatility_normalized_velocity",
        _row(calc={"v1": -1.2}, inputs={"iv.rsi_14_15m.v1[4]": [40.0, 41.0, 42.0, 43.0]}),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_window_edge_scope_eth_only() -> None:
    btc_out = apply_decision_logic(
        "window_edge_57to01_nonrolling",
        _row(pair="BTC-USD", calc={"v1": 0.2}),
    )
    eth_out = apply_decision_logic(
        "window_edge_57to01_nonrolling",
        _row(pair="ETH-USD", calc={"v1": 0.2}),
    )
    assert btc_out["signal"] == "no_signal"
    assert eth_out["signal"] == "up"


def test_codex_btc_down_trigger() -> None:
    out = apply_decision_logic(
        "CODEX",
        _row(
            pair="BTC-USD",
            calc={"v1": 0.2},
            inputs={
                "sub.early_momentum_divergence_score.v1": 0.2,
                "sub.oi_funding_impulse_confirmation_2m.v1": 1.5,
                "sub.rsi_velocity_5m.v1": 0.5,
            },
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_codex_eth_up_trigger() -> None:
    out = apply_decision_logic(
        "CODEX",
        _row(
            pair="ETH-USD",
            calc={"v1": 0.3},
            inputs={
                "sub.early_momentum_divergence_score.v1": -0.2,
                "sub.oi_funding_impulse_confirmation_2m.v1": 0.2,
                "sub.rsi_velocity_5m.v1": 1.5,
            },
        ),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_codex_no_signal_when_thresholds_fail() -> None:
    out = apply_decision_logic(
        "CODEX",
        _row(
            pair="ETH-USD",
            calc={"v1": -0.1},
            inputs={
                "sub.early_momentum_divergence_score.v1": 0.1,
                "sub.oi_funding_impulse_confirmation_2m.v1": 0.2,
                "sub.rsi_velocity_5m.v1": 0.9,
            },
        ),
    )
    assert out["signal"] == "no_signal"
    assert out["triggered"] is False


def test_glm_1_down_trigger() -> None:
    out = apply_decision_logic(
        "GLM-1",
        _row(
            pair="BTC-USD",
            calc={"v1": 1.2, "absorption_signal": -1.0, "early_price_move": -0.8, "slip_sell_roc": 0.2, "slip_buy_roc": -0.1},
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_glm_1_up_trigger() -> None:
    out = apply_decision_logic(
        "GLM-1",
        _row(
            pair="ETH-USD",
            calc={"v1": 1.1, "absorption_signal": 1.0, "early_price_move": 0.7, "slip_sell_roc": -0.1, "slip_buy_roc": 0.4},
        ),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_glm_2_down_trigger() -> None:
    out = apply_decision_logic(
        "GLM-2",
        _row(
            pair="BTC-USD",
            calc={"v1": -1.0, "squeeze": 1.0, "cvd_delta": -5.0, "cvd_baseline": 1.0, "trend_ready": 1.0, "break_lower": 1.0, "break_upper": 0.0},
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_glm_2_up_trigger() -> None:
    out = apply_decision_logic(
        "GLM-2",
        _row(
            pair="ETH-USD",
            calc={"v1": 1.0, "squeeze": 1.0, "cvd_delta": 6.0, "cvd_baseline": 1.2, "trend_ready": 1.0, "break_lower": 0.0, "break_upper": 1.0},
        ),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_ob_imbalance_acceleration_3p_up_trigger() -> None:
    out = apply_decision_logic(
        "OB_Imbalance_Acceleration_3p",
        _row(
            pair="ETH-USD",
            calc={
                "v1": 1.35,
                "imbalance_delta": 1.0,
                "bid_slope_delta": 0.7,
            },
        ),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_ob_imbalance_acceleration_3p_down_trigger() -> None:
    out = apply_decision_logic(
        "OB_Imbalance_Acceleration_3p",
        _row(
            pair="ETH-USD",
            calc={
                "v1": -1.45,
                "imbalance_delta": -1.1,
                "bid_slope_delta": -0.7,
            },
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True


def test_oi_price_divergence_4h_up_trigger() -> None:
    out = apply_decision_logic(
        "OI_Price_Divergence_4h",
        _row(
            pair="ETH-USD",
            calc={
                "v1": 1.0,
                "oi_spike": 1.0,
                "momentum_value": 12.0,
                "momentum_slope": 1.5,
                "momentum_stalling": 0.0,
                "corr_collapse": 0.0,
            },
        ),
    )
    assert out["signal"] == "up"
    assert out["triggered"] is True


def test_oi_price_divergence_4h_down_trigger() -> None:
    out = apply_decision_logic(
        "OI_Price_Divergence_4h",
        _row(
            pair="ETH-USD",
            calc={
                "v1": -1.0,
                "oi_spike": 1.0,
                "momentum_value": 3.0,
                "momentum_slope": -0.8,
                "momentum_stalling": 1.0,
                "corr_collapse": 1.0,
            },
        ),
    )
    assert out["signal"] == "down"
    assert out["triggered"] is True
