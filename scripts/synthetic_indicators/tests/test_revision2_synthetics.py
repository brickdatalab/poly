from __future__ import annotations

import importlib.util
from pathlib import Path
import sys

import pytest


def _load_module():
    mod_path = Path("scripts/synthetic_indicators/analyze_revision2_synthetics.py")
    spec = importlib.util.spec_from_file_location("analyze_revision2_synthetics", mod_path)
    if spec is None or spec.loader is None:
        raise RuntimeError("Unable to load analyze_revision2_synthetics module")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


def test_aroon_pvt_confidence_formula():
    m = _load_module()
    val = m.compute_aroon_pvt_confidence(aroon_osc_t1=40.0, pvt_t1=1200.0, pvt_t2=1000.0)
    assert val == pytest.approx(1.35, rel=1e-9)

    val2 = m.compute_aroon_pvt_confidence(aroon_osc_t1=-20.0, pvt_t1=900.0, pvt_t2=1000.0)
    assert val2 == pytest.approx(-1.05, rel=1e-9)


def test_adx_roc_regime_filter_formula():
    m = _load_module()
    trending = m.compute_adx_roc_regime_filter(
        adx_t1=30.0,
        plus_di_t1=35.0,
        minus_di_t1=15.0,
        roc_t1=2.0,
    )
    # trending => base roc + di spread adjustment
    assert trending == pytest.approx(4.0, rel=1e-9)

    choppy = m.compute_adx_roc_regime_filter(
        adx_t1=15.0,
        plus_di_t1=20.0,
        minus_di_t1=30.0,
        roc_t1=2.0,
    )
    # choppy => fade roc + di spread adjustment
    assert choppy == pytest.approx(-3.0, rel=1e-9)


def test_sql_contract_uses_t0_minus_1_lags():
    m = _load_module()
    sql = m.build_revision2_dataset_sql(
        start_ts="2026-01-22T00:00:00Z",
        end_ts="now",
        pairs=["BTC-USD", "ETH-USD"],
    )
    for needle in [
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
    ]:
        assert needle in sql
