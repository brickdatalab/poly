from pathlib import Path


def test_docs_include_synthetic_tables_functions_and_fields():
    text = Path("docs/SYNTHETIC_INDICATORS_SCHEMA.md").read_text()
    for token in [
        "synthetic_indicator_configs",
        "synthetic_indicator_values",
        "synthetic_job_queue",
        "v_synthetic_signal_inputs",
        "fn_backfill_synthetic_indicators",
        "syn_mtf_signed_efficiency_ratio_5m12_15m8",
        "syn_order_flow_accel_regime_tplus2",
    ]:
        assert token in text
