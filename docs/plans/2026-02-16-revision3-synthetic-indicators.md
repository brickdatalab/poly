# Revision 3 Synthetic Indicators Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Implement and validate `adaptive_regime_alpha` and `volume_strength_confirmation` in `indicators.synthetic_feature_test` with strict no-leak indexing and regime-split IC reporting.

**Architecture:** Build a dedicated Python analysis runner that computes features from `indicators.v_model_15m` using SQL lag windows (`t0-1`, `t0-2`) and forward return target (`t0 -> t0+15m`). Persist compact outputs to Supabase and JSON/CSV artifacts. Gate promotion SQL generation on success criteria.

**Tech Stack:** Python 3, pandas/numpy, psql CLI, Supabase Postgres.

---

### Task 1: Add failing tests for Revision 3 formulas and leakage SQL contract

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_revision3_synthetics.py`

**Step 1:** Add tests for:
- `adaptive_regime_alpha` trend/chop/neutral behavior
- `volume_strength_confirmation` ATR gating behavior
- SQL contract checks for `lag(...,1/2)` and ATR average window excluding `t0`

**Step 2:** Run test file and confirm initial failure due missing module.

### Task 2: Implement Revision 3 analyzer

**Files:**
- Create: `scripts/synthetic_indicators/analyze_revision3_synthetics.py`

**Step 1:** Implement formula helpers and SQL dataset builder with strict lag windows.

**Step 2:** Implement metrics:
- overall IC
- regime IC split (`ADX20 > 25`, `< 20`, `20-25`)
- max drawdown
- combined strategy IC

**Step 3:** Persist `indicators.synthetic_feature_test` with the new two features.

### Task 3: Run validations and produce artifacts

**Files:**
- Output dir under `scripts/output/synthetic_indicators/revision3_eval_<run_id>/`

**Step 1:** Run unit tests and full analysis script.

**Step 2:** Validate leakage checks and drawdown-vs-rev2 baseline (`-0.3463`).

**Step 3:** If success criteria pass, generate migration SQL file to promote synthetic features into production indicator storage.

### Task 4: Summarize results

**Step 1:** Report metrics and whether targets passed:
- Combined IC > 0.035
- `adaptive_regime_alpha` choppy IC > 0.040 flag

**Step 2:** Provide exact artifact paths and verification commands.
