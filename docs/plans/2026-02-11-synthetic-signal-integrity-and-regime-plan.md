# Synthetic Signal Integrity + Regime Gating Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Validate and harden BTC/ETH 15m synthetic signal quality under adversarial conditions, then activate only robust >=60% signals with regime-aware gating in realtime.

**Architecture:** Two-layer approach. Layer 1 is an offline integrity/research pipeline that builds canonical event datasets and runs leakage/regime/decay tests. Layer 2 is production rule orchestration in `indicators.codex_signal_rules` and `indicators.codex_signals`, extended with regime-aware activation and health checks. No changes to existing ingestion workflows; only additive migrations, functions, and scripts.

**Tech Stack:** Postgres (Supabase SQL functions/views), Python 3.11 scripts (`psql` subprocess + pandas/numpy), pytest integration checks.

---

## Scope and Constraints
- Pairs in objective scope: `BTC-USD`, `ETH-USD`.
- Event definition: 15m market windows starting at `t0 in {:00,:15,:30,:45}`.
- Decision timing constraints: only features available at `t0+1` or `t0+2` per synthetic `decision_phase`.
- Hard accuracy gate: reject rules/signals < `60%` observed accuracy.
- Data policy:
  - If all upstream components of a synthetic are present in training schema, use training+indicator split.
  - Else use indicator schema only (`2026-01-22` to now) with strict walk-forward segmentation.

## Current State Snapshot (from live DB)
- Active synthetic configs: `9`
- Active synthetic configs with active codex rules: `8`
- Active rule configs that emitted at least one signal in last 24h: `7`
- Quarter-hour coverage since each config’s first bucket:
  - Legacy 6 configs: ~`99.95%` on BTC/ETH
  - New 2 configs + ETH window-edge: ~`96.00%` (newly deployed window)

---

### Task 1: Build canonical signal research dataset contract

**Files:**
- Create: `scripts/synthetic_indicators/research/build_canonical_signal_dataset.py`
- Create: `scripts/synthetic_indicators/research/sql/canonical_signal_dataset.sql`
- Create: `scripts/output/signal_integrity/README.md`

**Step 1: Add feature-availability mapper**
- Build a config-to-source-column mapper from:
  - `indicators.synthetic_indicator_configs.params`
  - compute function dependency list (explicit mapping dictionary in script)
- Output matrix per config:
  - `available_in_training: true/false`
  - `fallback_source: training|indicators`

**Step 2: Build canonical event rows (no leakage)**
- One row per `(pair, t0, config_id)` for BTC/ETH.
- Join synthetic value at correct decision phase timestamp.
- Join target label:
  - `y_dir = sign(close_15m[t0] - open_15m[t0])`
  - `y_mag = pct_change(open_15m[t0], close_15m[t0])`
- Enforce timestamp guards:
  - feature source times must be `<= decision_time`.

**Step 3: Persist reproducible artifacts**
- Write parquet/csv + metadata JSON to `scripts/output/signal_integrity/<run_id>/`.

---

### Task 2: Adversarial leakage tests (critical gate)

**Files:**
- Create: `scripts/synthetic_indicators/research/leakage_tests.py`
- Create: `scripts/synthetic_indicators/research/sql/leakage_probes.sql`
- Create: `scripts/synthetic_indicators/tests/test_signal_integrity_leakage.py`

**Step 1: Future-peek probe**
- Compare baseline accuracy vs intentionally leaked variant (`t0+15m` feature shift).
- If leaked uplift is small/none, investigate data alignment bug.

**Step 2: Placebo probe**
- Randomly permute targets within day bucket; accuracy should collapse toward ~50%.

**Step 3: Timestamp invariants**
- Assert all rows satisfy phase availability (`t_plus_1m` and `t_plus_2m`).
- Fail pipeline if any violation found.

**Step 4: CI tests**
- Add pytest integration tests that run SQL probes and enforce invariants.

---

### Task 3: Regime decomposition tests

**Files:**
- Create: `scripts/synthetic_indicators/research/regime_decomposition.py`
- Create: `scripts/synthetic_indicators/research/sql/regime_features.sql`
- Create: `docs/discoveries/signal_integrity_regimes.md`

**Step 1: Define regimes (simple and auditable)**
- Volatility regime: ATR/price tertiles.
- Trend/chop regime: signed ER or ADX proxy buckets.
- Liquidity regime: spread + depth imbalance buckets.
- OI regime: OI acceleration / funding pressure buckets.

**Step 2: Score per signal per regime**
- Metrics:
  - accuracy, precision(up/down), support count, trigger rate
  - Wilson CI 95% for accuracy

**Step 3: Gate rules**
- Mark signal-regime combinations as deployable only if:
  - accuracy >= 60%
  - lower CI bound >= 55%
  - support >= minimum threshold

---

### Task 4: Support-decay and stability tests

**Files:**
- Create: `scripts/synthetic_indicators/research/support_decay.py`
- Create: `scripts/synthetic_indicators/research/rolling_walkforward.py`
- Create: `docs/discoveries/signal_support_decay.md`

**Step 1: Walk-forward windows**
- Weekly and rolling 14d/21d windows from Jan 22 to now.
- Evaluate each config+rule on forward-only slices.

**Step 2: Decay metrics**
- Compute slope of accuracy over time, rolling support/day, max loss streak.
- Flag unstable rules (accuracy decay, support collapse, or high variance).

**Step 3: Choppy-market stress**
- Isolate low-trend/high-whipsaw windows; re-score all rules.
- Keep only rules that remain >=60% in at least one explicit regime and do not catastrophically fail in chop.

---

### Task 5: Production architecture update for regime-aware ruleing

**Files:**
- Create migration: `supabase/migrations/20260211_18xxxx_add_regime_gating_to_codex_rules.sql`
- Modify: `supabase/migrations/20260211_172000_create_codex_signal_functions.sql` (or additive replacement migration)
- Create: `supabase/migrations/20260211_18xxxx_create_codex_signal_performance_tables.sql`

**Step 1: Extend rules metadata**
- Add columns (or companion table) for:
  - `regime_key`, `regime_operator`, `regime_threshold_low`, `regime_threshold_high`
  - `min_accuracy_gate`, `min_support_gate`, `priority_weight`
  - `valid_from`, `valid_to`, `deactivation_reason`

**Step 2: Runtime evaluation logic**
- Evaluate base threshold + regime constraint.
- If multiple rules pass, keep all rows in `codex_signals` and rank by:
  - expected edge score (base_accuracy * regime_confidence * support_weight).

**Step 3: Health-based auto-suspend (soft guardrail)**
- If rolling 7d live accuracy < 60% with sufficient support, mark rule inactive and log reason.

---

### Task 6: Testing strategy (designing-tests)

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_regime_gated_rule_eval.py`
- Create: `scripts/synthetic_indicators/tests/test_signal_decay_metrics.py`
- Create: `scripts/synthetic_indicators/tests/test_research_dataset_contract.py`

**Step 1: Unit tests (fast)**
- Rule threshold operators, regime bucket assignment, ranking score deterministic behavior.

**Step 2: Integration tests (DB-backed)**
- Synthetic compute -> rule eval -> codex_signals rows.
- Verify no duplicate leakage rows and correct quarter-hour event mapping.

**Step 3: Backtest acceptance tests**
- Run end-to-end replay over Jan 22..now for BTC/ETH.
- Acceptance gates:
  - each active production rule >= 60% out-of-sample
  - minimum support floor met
  - no leakage violations

---

### Task 7: Rollout and operational strategy

**Files:**
- Create: `scripts/synthetic_indicators/run_signal_integrity_pipeline.py`
- Create: `docs/discoveries/signal_integrity_release_report.md`

**Step 1: Dry-run mode**
- Produce recommendations without mutating active rules.

**Step 2: Controlled activation**
- Activate only approved BTC/ETH rule-regime rows.
- Keep legacy rules marked with explicit status for rollback.

**Step 3: Daily monitor job**
- Recompute rolling integrity metrics, emit summary report, and suggest promotions/demotions.

---

## Architecture Decision Record (summary)

### Decision
Use additive, regime-aware rule gating on top of existing codex signal pipeline, with strict integrity validation before activation changes.

### Options considered
1. Keep simple static thresholds only.
2. Full ML model replacement.
3. Hybrid rule engine with integrity/regime gating (chosen).

### Trade-offs
- Chosen approach keeps current production stable while adding measurable controls.
- Slightly more SQL/function complexity, but auditable and fast to iterate.
- Avoids premature model complexity while preserving edge discovery workflow.

---

## Success Criteria
- We can answer, for each synthetic signal, exactly where it works and where it breaks.
- No future leakage or timing violations pass CI.
- Only BTC/ETH rules with >=60% validated performance remain active.
- `codex_signals` reflects regime-aware decisions in realtime without breaking current pipelines.

## Execution Order
1. Task 1 + Task 2 (blocker gates)
2. Task 3 + Task 4 (selection evidence)
3. Task 5 (schema/function updates)
4. Task 6 (test hardening)
5. Task 7 (rollout)
