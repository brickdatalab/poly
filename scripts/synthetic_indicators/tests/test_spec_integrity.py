from pathlib import Path


def test_synthetic_spec_has_six_indicators_and_required_fields():
    text = Path("docs/discoveries/synthetic_indicators_spec.md").read_text()
    for required in [
        "mtf_signed_efficiency_ratio",
        "rsi_velocity_5m",
        "early_impulse_liquidity_alignment_2m",
        "oi_funding_impulse_confirmation_2m",
        "early_momentum_divergence_score",
        "order_flow_acceleration_regime",
        "decision_phase",
        "lookback_requirements",
        "source_columns",
        "synthetic_indicator_purpose",
    ]:
        assert required in text
