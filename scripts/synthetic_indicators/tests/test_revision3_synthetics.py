from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_module():
    mod_path = Path("scripts/synthetic_indicators/analyze_revision3_synthetics.py")
    spec = importlib.util.spec_from_file_location("analyze_revision3_synthetics", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load analyze_revision3_synthetics module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_adaptive_regime_alpha_formula_behavior():
    m = _load_module()
    trend = m.compute_adaptive_regime_alpha(
        adx_t1=30.0,
        aroon_osc_t1=60.0,
        pvt_t1=1005.0,
        pvt_t2=1000.0,
        roc_t1=2.0,
    )
    assert trend == pytest.approx(1.1, rel=1e-9)

    chop = m.compute_adaptive_regime_alpha(
        adx_t1=15.0,
        aroon_osc_t1=60.0,
        pvt_t1=1005.0,
        pvt_t2=1000.0,
        roc_t1=4.0,
    )
    assert chop == pytest.approx(-0.4, rel=1e-9)

    neutral = m.compute_adaptive_regime_alpha(
        adx_t1=22.0,
        aroon_osc_t1=60.0,
        pvt_t1=1005.0,
        pvt_t2=1000.0,
        roc_t1=4.0,
    )
    assert neutral == pytest.approx(0.0, rel=1e-9)


def test_volume_strength_confirmation_formula_behavior():
    m = _load_module()
    active = m.compute_volume_strength_confirmation(
        pvt_t1=1010.0,
        pvt_t2=1000.0,
        atr_t1=2.0,
        atr_avg_t15_to_t2=2.0,
    )
    assert active == pytest.approx(10.0, rel=1e-9)

    gated = m.compute_volume_strength_confirmation(
        pvt_t1=1010.0,
        pvt_t2=1000.0,
        atr_t1=1.4,
        atr_avg_t15_to_t2=2.0,
    )
    assert gated == pytest.approx(0.0, rel=1e-9)


def test_revision3_sql_contract_uses_strict_lags_and_atr_window():
    m = _load_module()
    sql = m.build_revision3_dataset_sql(
        start_ts="2026-01-22T00:00:00Z",
        end_ts="now",
        pairs=["BTC-USD", "ETH-USD"],
    ).lower()
    for needle in [
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
    ]:
        assert needle in sql

