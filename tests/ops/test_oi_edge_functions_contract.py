from pathlib import Path


def _read(path: str) -> str:
    return Path(path).read_text()


def test_oi_ingestor_contract() -> None:
    src = _read("supabase/functions/oi-ingestor/index.ts")
    assert "api/v5/public/open-interest" in src
    assert "api/v5/public/funding-rate" in src
    assert "api/v5/public/mark-price" in src
    assert ".from(\"open_interest\")" in src
    assert ".rpc(\"fn_compute_oi_features_for_bucket\"" in src
    assert "missing_ohlcv_15m_bucket" in src


def test_oi_backfill_contract() -> None:
    src = _read("supabase/functions/oi-backfill/index.ts")
    assert "api/v5/rubik/stat/contracts/open-interest-history" in src
    assert ".from(\"ohlcv_15m\")" in src
    assert ".from(\"open_interest\")" in src
    assert ".rpc(\"fn_compute_oi_features_for_bucket\"" in src
    assert "skipped_missing_candle" in src


def test_supabase_function_config_has_oi_functions() -> None:
    cfg = _read("supabase/config.toml")
    lowered = cfg.lower()
    assert "[functions.oi-ingestor]" in lowered
    assert "[functions.oi-backfill]" in lowered
