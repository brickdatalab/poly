# Synthetic Indicators Pipeline Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add six synthetic indicators to `indicators` schema in a config+values architecture, with safe backfill to 2026-01-22 and forward generation, without breaking existing indicator workflows.

**Architecture:** Implement a parallel synthetic subsystem: `synthetic_indicator_configs` + `synthetic_indicator_values` + dedicated compute/backfill functions + dedicated synthetic queue runner. Existing `indicator_configs`, `indicator_values`, `job_queue`, and compute functions remain untouched. Expose a serving view for easy signal-script mapping and keep all rules/config as metadata.

**Tech Stack:** Postgres (Supabase), SQL functions, Python 3.11 runner scripts, pytest, psql-based integration checks, markdown/OpenAPI docs.

---

## Architecture Decision Summary

### Option A (Selected): Parallel Long-Table Subsystem
- Add new tables under `indicators`:
  - `synthetic_indicator_configs`
  - `synthetic_indicator_values`
  - `synthetic_job_queue`
- Add synthetic-only compute/backfill functions.
- Add synthetic serving view for signal filters.

### Why Option A
- Zero-risk isolation from current indicator workflows.
- Clean metadata-driven expansion for new synthetic variants.
- Natural mapping to existing signal scripts (`config_id` + `v1..v5`).
- Safe idempotent backfills with `(pair, bucket_time, config_id)` uniqueness.

---

### Task 1: Create Synthetic Indicator Specification and Source Mapping

**Files:**
- Create: `docs/discoveries/synthetic_indicators_spec.md`
- Modify: `docs/discoveries/synthetic_indicators.txt`
- Test: `scripts/synthetic_indicators/tests/test_spec_integrity.py`

**Step 1: Write the failing test**

```python
# scripts/synthetic_indicators/tests/test_spec_integrity.py
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
    ]:
        assert required in text
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_spec_integrity.py -v`
Expected: FAIL (spec file missing).

**Step 3: Write minimal implementation**
- Create `synthetic_indicators_spec.md` with all six indicators and exact fields:
  - config id
  - decision phase (`t_plus_1m` or `t_plus_2m`)
  - source dependencies
  - formula components
  - output column semantics (`v1..v5`)
  - intended use in filter logic.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_spec_integrity.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/discoveries/synthetic_indicators_spec.md docs/discoveries/synthetic_indicators.txt scripts/synthetic_indicators/tests/test_spec_integrity.py
git commit -m "docs: add formal spec for six synthetic indicators"
```

---

### Task 2: Add Schema Migration for Synthetic Tables (Non-Breaking)

**Files:**
- Create: `supabase/migrations/20260211_150000_create_synthetic_indicator_tables.sql`
- Test: `scripts/synthetic_indicators/tests/test_migration_sql_shape.py`

**Step 1: Write the failing test**

```python
# scripts/synthetic_indicators/tests/test_migration_sql_shape.py
from pathlib import Path

def test_migration_contains_required_tables_and_comments():
    sql = Path("supabase/migrations/20260211_150000_create_synthetic_indicator_tables.sql").read_text()
    required = [
        "create table if not exists indicators.synthetic_indicator_configs",
        "create table if not exists indicators.synthetic_indicator_values",
        "create table if not exists indicators.synthetic_job_queue",
        "comment on table indicators.synthetic_indicator_configs",
        "comment on table indicators.synthetic_indicator_values",
        "comment on column indicators.synthetic_indicator_values.v1",
        "unique (pair, bucket_time, config_id)",
    ]
    for r in required:
        assert r.lower() in sql.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_migration_sql_shape.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Create migration with:
  - `synthetic_indicator_configs` (config metadata like existing configs)
  - `synthetic_indicator_values` (long table with `v1..v5`, `source_time`, `computed_at`, `quality_flags`)
  - `synthetic_job_queue` (separate queue)
  - indexes and uniqueness
  - `COMMENT ON TABLE/COLUMN/FUNCTION` statements for all columns.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_migration_sql_shape.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_150000_create_synthetic_indicator_tables.sql scripts/synthetic_indicators/tests/test_migration_sql_shape.py
git commit -m "feat: add synthetic indicator schema tables with full comments"
```

---

### Task 3: Seed Six Synthetic Config Rows with Full Metadata

**Files:**
- Create: `supabase/migrations/20260211_151000_seed_synthetic_indicator_configs.sql`
- Test: `scripts/synthetic_indicators/tests/test_config_seed_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_seed_sql_includes_all_six_config_ids():
    sql = Path("supabase/migrations/20260211_151000_seed_synthetic_indicator_configs.sql").read_text()
    expected = [
        "syn_mtf_signed_efficiency_ratio_5m12_15m8",
        "syn_rsi_velocity_5m_3bar_z20",
        "syn_early_impulse_liq_align_tplus2",
        "syn_oi_funding_impulse_tplus2",
        "syn_early_momentum_divergence_tplus1",
        "syn_order_flow_accel_regime_tplus2",
    ]
    for e in expected:
        assert e in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_config_seed_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Seed six rows into `synthetic_indicator_configs` with:
  - category (`synthetic_mtf`, `synthetic_momentum`, etc.)
  - decision phase
  - params JSONB (lookbacks, constants, sigma ladder)
  - output columns map (`v1` main score, `v2..v5` components)
  - rich descriptions.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_config_seed_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_151000_seed_synthetic_indicator_configs.sql scripts/synthetic_indicators/tests/test_config_seed_sql.py
git commit -m "feat: seed six synthetic indicator configs with metadata"
```

---

### Task 4: Implement SQL Compute Functions for All Six Synthetics

**Files:**
- Create: `supabase/migrations/20260211_152000_create_synthetic_compute_functions.sql`
- Test: `scripts/synthetic_indicators/tests/test_compute_functions_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_compute_functions_defined_and_commented():
    sql = Path("supabase/migrations/20260211_152000_create_synthetic_compute_functions.sql").read_text().lower()
    required = [
        "create or replace function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio",
        "create or replace function indicators.fn_compute_synthetic_rsi_velocity_5m",
        "create or replace function indicators.fn_compute_synthetic_early_impulse_liq_align_2m",
        "create or replace function indicators.fn_compute_synthetic_oi_funding_impulse_2m",
        "create or replace function indicators.fn_compute_synthetic_early_momentum_divergence",
        "create or replace function indicators.fn_compute_synthetic_order_flow_accel_regime",
        "comment on function indicators.fn_compute_synthetic_mtf_signed_efficiency_ratio",
    ]
    for r in required:
        assert r in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_compute_functions_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Add one function per synthetic indicator.
- Add dispatcher:
  - `fn_compute_synthetic_for_bucket(p_pair, p_bucket_time, p_config_id)`
  - `fn_compute_all_synthetic_for_bucket(p_pair, p_bucket_time)`
- All functions:
  - are idempotent (`INSERT ... ON CONFLICT DO UPDATE`)
  - use only current historical data (no leakage)
  - include fallback behavior (`NULL`/flag) when required upstream data missing
  - include `COMMENT ON FUNCTION`.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_compute_functions_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_152000_create_synthetic_compute_functions.sql scripts/synthetic_indicators/tests/test_compute_functions_sql.py
git commit -m "feat: add compute functions for six synthetic indicators"
```

---

### Task 5: Add Backfill Function and Forward Queue Functions

**Files:**
- Create: `supabase/migrations/20260211_153000_create_synthetic_backfill_and_queue_functions.sql`
- Test: `scripts/synthetic_indicators/tests/test_backfill_queue_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_backfill_and_queue_functions_exist():
    sql = Path("supabase/migrations/20260211_153000_create_synthetic_backfill_and_queue_functions.sql").read_text().lower()
    for name in [
        "fn_backfill_synthetic_indicators",
        "fn_enqueue_synthetic_jobs",
        "fn_process_synthetic_jobs",
    ]:
        assert name in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_backfill_queue_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- `fn_backfill_synthetic_indicators(p_from, p_to, p_pairs text[])`
  - chunk by 15m buckets
  - compute all six configs
  - start default at `2026-01-22 07:15:00+00`
- `fn_enqueue_synthetic_jobs()`
  - enqueue only finalized bucket times where required t+1/t+2 inputs exist.
- `fn_process_synthetic_jobs(batch_size)`
  - independent from existing `job_queue`.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_backfill_queue_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_153000_create_synthetic_backfill_and_queue_functions.sql scripts/synthetic_indicators/tests/test_backfill_queue_sql.py
git commit -m "feat: add synthetic backfill and queue processing functions"
```

---

### Task 6: Add Python Runner for Safe Backfill + Incremental Forward Fill

**Files:**
- Create: `scripts/synthetic_indicators/run_synthetic_pipeline.py`
- Create: `scripts/synthetic_indicators/tests/test_runner_args.py`
- Create: `scripts/synthetic_indicators/tests/test_runner_sql_contracts.py`

**Step 1: Write the failing tests**

```python
# test_runner_args.py
def test_runner_accepts_backfill_and_incremental_modes():
    from scripts.synthetic_indicators.run_synthetic_pipeline import parse_args
    args = parse_args(["--mode", "backfill", "--from", "2026-01-22T07:15:00Z", "--to", "2026-02-11T00:00:00Z"])
    assert args.mode == "backfill"

# test_runner_sql_contracts.py
def test_runner_references_synthetic_functions_only():
    from pathlib import Path
    text = Path("scripts/synthetic_indicators/run_synthetic_pipeline.py").read_text()
    assert "fn_backfill_synthetic_indicators" in text
    assert "indicators.job_queue" not in text
```

**Step 2: Run tests to verify they fail**

Run: `pytest scripts/synthetic_indicators/tests/test_runner_args.py scripts/synthetic_indicators/tests/test_runner_sql_contracts.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Implement runner modes:
  - `backfill`
  - `incremental`
  - `healthcheck`
- Add parallel chunk execution for backfill (pair/day chunks).
- Add run reports to `scripts/output/synthetic_indicators/<UTC>/`.

**Step 4: Run tests to verify they pass**

Run: `pytest scripts/synthetic_indicators/tests/test_runner_args.py scripts/synthetic_indicators/tests/test_runner_sql_contracts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/run_synthetic_pipeline.py scripts/synthetic_indicators/tests/test_runner_args.py scripts/synthetic_indicators/tests/test_runner_sql_contracts.py
git commit -m "feat: add synthetic pipeline runner for backfill and incremental compute"
```

---

### Task 7: Add Serving View for Easy Signal-Script Mapping

**Files:**
- Create: `supabase/migrations/20260211_154000_create_v_synthetic_signal_inputs.sql`
- Test: `scripts/synthetic_indicators/tests/test_serving_view_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_serving_view_contains_all_six_signals():
    sql = Path("supabase/migrations/20260211_154000_create_v_synthetic_signal_inputs.sql").read_text()
    for col in [
        "syn_mtf_signed_efficiency_ratio",
        "syn_rsi_velocity_5m",
        "syn_early_impulse_liq_align_2m",
        "syn_oi_funding_impulse_2m",
        "syn_early_momentum_divergence",
        "syn_order_flow_accel_regime",
    ]:
        assert col in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_serving_view_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Create `indicators.v_synthetic_signal_inputs` keyed by `(pair, bucket_time)`.
- Include one column per synthetic score plus optional component columns.
- Include `decision_phase` and freshness fields.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_serving_view_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_154000_create_v_synthetic_signal_inputs.sql scripts/synthetic_indicators/tests/test_serving_view_sql.py
git commit -m "feat: add synthetic serving view for signal filter mapping"
```

---

### Task 8: Documentation and Column/Function Descriptions

**Files:**
- Create: `docs/SYNTHETIC_INDICATORS_SCHEMA.md`
- Modify: `docs/api/indicators.openapi.yaml`
- Modify: `INDICATORS_SCHEMA.md`
- Test: `scripts/synthetic_indicators/tests/test_docs_reference_synthetics.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_docs_include_synthetic_tables_functions_and_fields():
    text = Path("docs/SYNTHETIC_INDICATORS_SCHEMA.md").read_text()
    for token in [
        "synthetic_indicator_configs",
        "synthetic_indicator_values",
        "synthetic_job_queue",
        "v_synthetic_signal_inputs",
        "fn_backfill_synthetic_indicators",
    ]:
        assert token in text
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_docs_reference_synthetics.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Document each synthetic indicator’s purpose, inputs, formulas, decision phase, and output semantics.
- Document every new column and function.
- Add OpenAPI sections for new tables/view endpoints.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_docs_reference_synthetics.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/SYNTHETIC_INDICATORS_SCHEMA.md docs/api/indicators.openapi.yaml INDICATORS_SCHEMA.md scripts/synthetic_indicators/tests/test_docs_reference_synthetics.py
git commit -m "docs: add full synthetic indicator schema and API documentation"
```

---

### Task 9: Integration and Non-Regression Validation

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_integration_synthetic_pipeline.py`
- Create: `scripts/synthetic_indicators/tests/test_non_regression_existing_indicator_pipeline.py`
- Create: `scripts/output/synthetic_indicators/<run_id>/validation_report.md` (generated)

**Step 1: Write the failing tests**

```python
# test_integration_synthetic_pipeline.py
def test_synthetic_backfill_produces_rows_for_all_pairs_and_configs():
    # call SQL function on short window, assert rows exist for 6 config_ids x 3 pairs x buckets
    assert True  # placeholder failing first

# test_non_regression_existing_indicator_pipeline.py
def test_existing_indicator_counts_unchanged_after_synthetic_run():
    # compare pre/post counts in indicators.indicator_values for control window
    assert True  # placeholder failing first
```

**Step 2: Run tests to verify they fail**

Run: `pytest scripts/synthetic_indicators/tests/test_integration_synthetic_pipeline.py scripts/synthetic_indicators/tests/test_non_regression_existing_indicator_pipeline.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Implement integration tests with setup/teardown transaction or isolated time window.
- Add assertions:
  - synthetic rows exist and are fresh
  - no writes to `indicators.indicator_values` from synthetic runner
  - queue isolation (`synthetic_job_queue` only).

**Step 4: Run tests to verify they pass**

Run:
- `pytest scripts/synthetic_indicators/tests -v`
- `python scripts/synthetic_indicators/run_synthetic_pipeline.py --mode backfill --from 2026-01-22T07:15:00Z --to now --pairs BTC-USD,ETH-USD,SOL-USD`
- `python scripts/synthetic_indicators/run_synthetic_pipeline.py --mode healthcheck`

Expected:
- PASS tests
- backfill report shows no missing buckets after completion
- existing indicator pipeline metrics unchanged.

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/tests/test_integration_synthetic_pipeline.py scripts/synthetic_indicators/tests/test_non_regression_existing_indicator_pipeline.py
git commit -m "test: add integration and non-regression checks for synthetic pipeline"
```

---

## Testing Strategy (Designing Tests Skill Applied)

### Unit Tests (70%)
- Formula kernels and edge handling:
  - divide-by-zero safeguards
  - rolling z-score floors
  - decision phase gating (`t+1m`, `t+2m`)
  - sign handling for conflict/alignment indicators.

### Integration Tests (20%)
- SQL function execution against real schema:
  - per-bucket compute inserts/upserts
  - backfill range processing and idempotency
  - serving view returns complete six-signal row set.

### E2E/Operational Tests (10%)
- End-to-end backfill from `2026-01-22` to latest closed bucket.
- Incremental mode execution for most recent 4 buckets.
- Healthcheck verifies freshness and missing-rate thresholds.

### Success Criteria
- All six synthetic configs have values for each pair for all eligible buckets.
- No regressions in existing indicator tables/functions/jobs.
- Full comments/descriptions exist for tables, columns, functions, and indicators.
- Signal script can query one mapping view (`v_synthetic_signal_inputs`) with no custom joins.

---

## Rollout / Safety

1. Apply migrations in order in a non-production branch DB first.
2. Run integration + non-regression tests.
3. Run limited backfill (24h) and validate row counts.
4. Run full backfill from `2026-01-22 07:15:00+00`.
5. Enable incremental runner schedule.
6. Monitor synthetic freshness and queue lag for 24h before relying on filters.

---

Plan complete and saved to `docs/plans/2026-02-11-synthetic-indicators-pipeline-implementation.md`. Two execution options:

1. Subagent-Driven (this session) - I dispatch fresh subagent per task, review between tasks, fast iteration

2. Parallel Session (separate) - Open new session with executing-plans, batch execution with checkpoints

Which approach?
