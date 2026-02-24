# Precision Dual Regime Indicator Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add one new standalone synthetic indicator script in `syn-final/scripts` that backtests at >=75% accuracy from 2026-01-23 to now with multiple triggers.

**Architecture:** Build a pair-specific composite indicator (`BTC-USD` down setup, `ETH-USD` up setup) using existing no-leak synthetic components computed at `t+1`/`t+2` (`early_momentum_divergence_score`, `oi_funding_impulse_confirmation_2m`, `rsi_velocity_5m`). Integrate it into the shared `engine.py` evaluator/decision path and expose a self-aware wrapper like existing `check_inputs_*` scripts.

**Tech Stack:** Python 3, existing `syn-final/scripts/engine.py` data access helpers (`psql`), `pytest`.

---

### Task 1: Lock Thresholds and Backtest Spec

**Files:**
- Create: `syn-final/output/precision_dual_regime_backtest_*.json` (runtime output)

1. Derive exact thresholds from Jan 23→now quantiles:
- BTC: `emd >= q70` and `oii >= q94` => predict `down`
- ETH: `rsi_v >= q85` and `emd <= q15` => predict `up`
2. Confirm combined metrics on the same period.

### Task 2: TDD for New Decision Logic

**Files:**
- Modify: `syn-final/tests/test_decision_logic.py`

1. Add failing tests for new indicator name:
- BTC branch triggers `down` when thresholds pass.
- ETH branch triggers `up` when thresholds pass.
- Non-matching inputs return `no_signal`.
2. Run tests and verify failure before implementation.

### Task 3: Implement New Evaluator in Engine

**Files:**
- Modify: `syn-final/scripts/engine.py`

1. Add new required contract key.
2. Add evaluator function that composes existing evaluators:
- `early_momentum_divergence_score` at `t+1`
- `oi_funding_impulse_confirmation_2m` at `t+2`
- `rsi_velocity_5m` at `t+1`
3. Add decision logic branch with pair-specific thresholds.
4. Register indicator in `EVALUATORS`.

### Task 4: Add Standalone Self-Aware Script

**Files:**
- Create: `syn-final/scripts/check_inputs_precision_dual_regime_gate.py`

1. Match the pattern of existing wrappers:
- auto-derive current UTC quarter-hour bucket
- evaluate BTC/ETH
- pretty output via `print_payload`

### Task 5: Add Reproducible Backtest Script

**Files:**
- Create: `syn-final/scripts/backtest_precision_dual_regime_gate.py`

1. Backtest from `2026-01-23 00:00:00+00` to now.
2. Emit per-pair + combined triggered/correct/accuracy and thresholds used.
3. Write JSON and markdown report under `syn-final/output/`.

### Task 6: Verification

**Files:**
- No additional source edits expected.

1. Run targeted tests:
- `pytest syn-final/tests/test_decision_logic.py -q`
2. Run the new standalone evaluator:
- `python3 syn-final/scripts/check_inputs_precision_dual_regime_gate.py`
3. Run backtest:
- `python3 syn-final/scripts/backtest_precision_dual_regime_gate.py`
4. Confirm output remains >=75% accuracy with multiple triggers.
