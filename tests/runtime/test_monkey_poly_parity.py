from __future__ import annotations

import hashlib
from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
RUNTIME_SYNTHETIC_DIR = REPO_ROOT / "runtime" / "synthetic"
MONKEY_SYNTHETIC_DIR = Path("/Users/vitolo/Desktop/projects/monkey/syn-final/scripts")

RUNTIME_SHA256 = {
    "engine.py": "aa5f7af4c3773fc14e363ee488d847e8dcd8b6d93b851af291087a63f8f25b13",
    "run_all_signal_producers.py": "bc45666b5776aa7f9d20e703f5ef309dd29e2e496be116391ac6a211bda092da",
    "t0_cvd_price_divergence_velocity.py": "085b88184c3c1c2a6a0e334b283b029be0480c9f7e4ceb5f470a4e4fa29cc8a8",
    "t0_mtf_signed_efficiency_ratio.py": "7cac9e6151d94e5d462c07f27ad9900847d9dccc0b69592b4c766219f8e26a7a",
    "t0_rsi_velocity_5m.py": "7c90b4f967662c25d631a186747244092191cbb855267976dead5ae141320266",
    "t1_atr_normalized_reversal_pressure.py": "1faf0b0aeb0f6f3431b503c92959abaf87043166293d8e61417f95e64871d1ee",
    "t1_early_momentum_divergence_score.py": "219d2bfe2152fb77e0e1d0b642ac1983f7888b65e90973966425ec8e1bf9b1ef",
    "t1_multitimeframe_trend_confluence.py": "8f1737f96d1b9452f2e0aaaec12f5f45fca89e7ca63f3380763bd40c6caa4be6",
    "t1_rsi_volatility_normalized_velocity.py": "0d2496829ce72e2a465a65830a79e19a4316dc036e40c4639cacba138071704e",
    "t1_window_edge_57to01_nonrolling.py": "10382839ae4e0506bbf25fd00f7cc5cd8b1a767b0c122d3af52c0887a1302825",
    "t2_early_impulse_liquidity_alignment_2m.py": "7fddc4a9eb75eed353e9222c63b79c7f7c9740b07376048978e71b33f9203c99",
    "t2_oi_funding_impulse_confirmation_2m.py": "f24d88cca57448ed6e7813a88793a878c3fa9174cc7753747ec0ad6eb48eb5df",
    "t2_order_flow_acceleration_regime.py": "a328f74e4c0eed5e94af8a13aa6a88e9047734b326b53f11a9747945c394ec45",
}


def _sha256(file_path: Path) -> str:
    return hashlib.sha256(file_path.read_bytes()).hexdigest()


def test_runtime_script_set_is_complete() -> None:
    actual = {p.name for p in RUNTIME_SYNTHETIC_DIR.glob("*.py")}
    assert set(RUNTIME_SHA256) <= actual


def test_runtime_script_hashes_match_known_good_baseline() -> None:
    for filename, expected_hash in RUNTIME_SHA256.items():
        actual_hash = _sha256(RUNTIME_SYNTHETIC_DIR / filename)
        assert actual_hash == expected_hash, f"Hash mismatch for {filename}"


def test_runtime_scripts_match_monkey_reference_when_available() -> None:
    if not MONKEY_SYNTHETIC_DIR.exists():
        pytest.skip("Local monkey reference repo not present")

    for filename in sorted(RUNTIME_SHA256):
        monkey_hash = _sha256(MONKEY_SYNTHETIC_DIR / filename)
        poly_hash = _sha256(RUNTIME_SYNTHETIC_DIR / filename)
        assert monkey_hash == poly_hash, f"Parity drift vs monkey for {filename}"


def test_legacy_wrappers_forward_to_runtime_paths() -> None:
    legacy_engine = (REPO_ROOT / "syn-final" / "scripts" / "engine.py").read_text()
    legacy_runner = (REPO_ROOT / "syn-final" / "scripts" / "run_all_signal_producers.py").read_text()

    assert 'Path(__file__).resolve().parents[2] / "runtime" / "synthetic" / "engine.py"' in legacy_engine
    assert 'Path(__file__).resolve().parents[2] / "runtime" / "synthetic" / "run_all_signal_producers.py"' in legacy_runner
