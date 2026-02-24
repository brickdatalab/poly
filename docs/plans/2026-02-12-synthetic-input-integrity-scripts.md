# Synthetic Input Integrity Scripts Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Build per-indicator Python validators (working out of `/Users/vitolo/Desktop/projects/poly/syn`) that prove every required input is present at evaluation time, with deterministic output and zero silent missing-input failures.

**Architecture:** Create one hardcoded validator script per synthetic indicator plus one orchestrator for concurrent execution. Each script shares a strict contract: fetch required series/snapshots for a target bucket, compute all intermediate terms needed for decision logic, and emit `PASS` only when all required inputs are present and fresh. A shared core module handles DB access, time-bucket math, freshness checks, and uniform result schemas.

**Tech Stack:** Python 3.11, `psycopg`/Supabase Postgres connection via `.env`, standard library (`concurrent.futures`, `argparse`, `json`, `datetime`), pytest.

---

### Task 0: Finalize Indicator Scope and File Map

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/syn/INDICATOR_SCOPE.md`

**Step 1: Write explicit scope doc**
```markdown
# Indicator Scope
- Included: 10 non-window-edge indicators
- Excluded: window_edge_57to01_nonrolling_eth
- Rationale: user requested no window-edge indicators
```

**Step 2: Verify scope is unambiguous**
Run: `cat /Users/vitolo/Desktop/projects/poly/syn/INDICATOR_SCOPE.md`
Expected: list of included indicators and explicit exclusion.

**Step 3: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/INDICATOR_SCOPE.md
git commit -m "docs: define non-window-edge synthetic indicator scope"
```

### Task 1: Scaffold Syn-Local Project Structure

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/__init__.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/common.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_common_contract.py`

**Step 1: Write failing contract test**
```python
def test_result_contract_has_required_keys():
    required = {"indicator", "pair", "bucket_time", "status", "missing_inputs", "inputs"}
    payload = build_empty_result("x", "BTC-USD", "2026-02-12T00:00:00Z")
    assert required.issubset(payload.keys())
```

**Step 2: Run test to verify failure**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_common_contract.py -v`
Expected: FAIL (helpers not implemented).

**Step 3: Implement minimal shared core**
```python
def build_empty_result(indicator, pair, bucket):
    return {
        "indicator": indicator,
        "pair": pair,
        "bucket_time": bucket,
        "status": "missing_inputs",
        "missing_inputs": [],
        "inputs": {},
        "calc": {},
    }
```

**Step 4: Re-run test**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_common_contract.py -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/scripts /Users/vitolo/Desktop/projects/poly/syn/tests/test_common_contract.py
git commit -m "feat: scaffold syn-local validator core"
```

### Task 2: Add Strict Input Presence + Freshness Primitives

**Files:**
- Modify: `/Users/vitolo/Desktop/projects/poly/syn/scripts/common.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_freshness_and_missing.py`

**Step 1: Write failing freshness tests**
```python
def test_marks_missing_when_any_required_input_absent():
    res = evaluate_required_inputs({"a": 1}, ["a", "b"])
    assert res["missing"] == ["b"]
```

**Step 2: Run tests (fail expected)**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_freshness_and_missing.py -v`
Expected: FAIL.

**Step 3: Implement strict check helpers**
```python
def evaluate_required_inputs(found: dict, required: list[str]) -> dict:
    missing = [k for k in required if found.get(k) is None]
    return {"missing": missing, "ok": len(missing) == 0}
```

**Step 4: Re-run tests**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_freshness_and_missing.py -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/scripts/common.py /Users/vitolo/Desktop/projects/poly/syn/tests/test_freshness_and_missing.py
git commit -m "feat: add strict missing-input and freshness primitives"
```

### Task 3: Implement Per-Indicator Validators (10 non-window-edge)

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_mtf_signed_efficiency_ratio.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_rsi_velocity_5m.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_early_impulse_liquidity_alignment_2m.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_oi_funding_impulse_confirmation_2m.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_early_momentum_divergence_score.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_order_flow_acceleration_regime.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_cvd_price_divergence_velocity.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_atr_normalized_reversal_pressure.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_multitimeframe_trend_confluence.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_rsi_volatility_normalized_velocity.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_indicator_required_inputs.py`

**Step 1: Write failing table-driven tests for required input maps**
```python
@pytest.mark.parametrize("indicator,required", [
    ("mtf_signed_efficiency_ratio", ["ohlcv_5m.close", "ohlcv_15m.close"]),
    ("rsi_velocity_5m", ["rsi_7_5m.v1", "rsi_14_1h.v1"]),
])
def test_indicator_required_input_map(indicator, required):
    assert REQUIRED_INPUTS[indicator] == required
```

**Step 2: Run tests (fail expected)**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_indicator_required_inputs.py -v`
Expected: FAIL.

**Step 3: Implement each validator with hardcoded formula dependencies**
```python
REQUIRED = ["rsi_7_5m.v1", "rsi_14_1h.v1"]
found = fetch_inputs(conn, pair, bucket_time, REQUIRED)
check = evaluate_required_inputs(found, REQUIRED)
status = "ready" if check["ok"] else "missing_inputs"
```

**Step 4: Re-run tests**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_indicator_required_inputs.py -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_*.py /Users/vitolo/Desktop/projects/poly/syn/tests/test_indicator_required_inputs.py
git commit -m "feat: add per-indicator strict input validators"
```

### Task 4: Add High-Readability CLI Output and JSON Artifacts

**Files:**
- Modify: all `/Users/vitolo/Desktop/projects/poly/syn/scripts/check_inputs_*.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_cli_output_shape.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/output/.gitkeep`

**Step 1: Write failing CLI output test**
```python
def test_cli_prints_pair_summary_headers(capsys):
    run_cli_for_fixture()
    out = capsys.readouterr().out
    assert "PAIR SUMMARY" in out
```

**Step 2: Run tests (fail expected)**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_cli_output_shape.py -v`
Expected: FAIL.

**Step 3: Implement readable output format**
```python
print("PAIR SUMMARY")
print("pair | indicator | status | missing_count")
```

**Step 4: Re-run tests**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_cli_output_shape.py -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/scripts /Users/vitolo/Desktop/projects/poly/syn/tests/test_cli_output_shape.py /Users/vitolo/Desktop/projects/poly/syn/output/.gitkeep
git commit -m "feat: add human-readable output and json artifact contract"
```

### Task 5: Add Orchestrator for Full Parallel Run (All Indicators, All Pairs)

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/syn/scripts/run_all_input_checks.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_orchestrator_parallel.py`

**Step 1: Write failing parallel orchestration test**
```python
def test_orchestrator_runs_all_scripts_once():
    result = run_all_for_bucket("2026-02-12T15:15:00Z")
    assert result["script_count"] == 10
```

**Step 2: Run tests (fail expected)**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_orchestrator_parallel.py -v`
Expected: FAIL.

**Step 3: Implement process-level parallel execution**
```python
with ProcessPoolExecutor(max_workers=min(16, len(SCRIPTS))) as ex:
    futures = [ex.submit(run_one, script, args) for script in SCRIPTS]
```

**Step 4: Re-run tests**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests/test_orchestrator_parallel.py -v`
Expected: PASS.

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/scripts/run_all_input_checks.py /Users/vitolo/Desktop/projects/poly/syn/tests/test_orchestrator_parallel.py
git commit -m "feat: add parallel orchestrator for all indicator input checks"
```

### Task 6: End-to-End Verification Against Live Supabase

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/syn/tests/test_live_smoke_optional.py`
- Create: `/Users/vitolo/Desktop/projects/poly/syn/README.md`

**Step 1: Add optional live smoke test (skips without env)**
```python
def test_live_smoke_runs_without_missing_inputs_if_data_present():
    # skip if env missing
    # run orchestrator against latest bucket
```

**Step 2: Run full test suite**
Run: `pytest /Users/vitolo/Desktop/projects/poly/syn/tests -v`
Expected: PASS (or explicit SKIP for live tests).

**Step 3: Run live orchestrator command**
Run:
```bash
python3 /Users/vitolo/Desktop/projects/poly/syn/scripts/run_all_input_checks.py --bucket latest --pairs BTC-USD ETH-USD SOL-USD --pretty
```
Expected:
- one section per pair
- one row per indicator
- `status=ready` only when every required input is present
- explicit `missing_inputs=[...]` otherwise

**Step 4: Document runbook**
Include in `/Users/vitolo/Desktop/projects/poly/syn/README.md`:
- exact run commands
- expected output interpretation
- troubleshooting for missing inputs

**Step 5: Commit**
```bash
git add /Users/vitolo/Desktop/projects/poly/syn/tests /Users/vitolo/Desktop/projects/poly/syn/README.md
git commit -m "test: verify full synthetic input integrity workflow"
```

---

## Indicator-to-Script Matrix (No Window Edge)
1. `mtf_signed_efficiency_ratio` -> `check_inputs_mtf_signed_efficiency_ratio.py`
2. `rsi_velocity_5m` -> `check_inputs_rsi_velocity_5m.py`
3. `early_impulse_liquidity_alignment_2m` -> `check_inputs_early_impulse_liquidity_alignment_2m.py`
4. `oi_funding_impulse_confirmation_2m` -> `check_inputs_oi_funding_impulse_confirmation_2m.py`
5. `early_momentum_divergence_score` -> `check_inputs_early_momentum_divergence_score.py`
6. `order_flow_acceleration_regime` -> `check_inputs_order_flow_acceleration_regime.py`
7. `cvd_price_divergence_velocity` -> `check_inputs_cvd_price_divergence_velocity.py`
8. `atr_normalized_reversal_pressure` -> `check_inputs_atr_normalized_reversal_pressure.py`
9. `multitimeframe_trend_confluence` -> `check_inputs_multitimeframe_trend_confluence.py`
10. `rsi_volatility_normalized_velocity` -> `check_inputs_rsi_volatility_normalized_velocity.py`

## Validation Standard (Hard Requirement)
- Any missing required field => `status=missing_inputs` and explicit field name list.
- No fallback defaults for missing market data.
- Freshness checks are indicator-specific and hardcoded.
- Scripts are deterministic for same `pair + bucket_time` input.

