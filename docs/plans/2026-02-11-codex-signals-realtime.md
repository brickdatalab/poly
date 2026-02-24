# Codex Signals Realtime Emission Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Create `indicators.codex_signals` and emit realtime prediction rows at `:02/:17/:32/:47` using only forward data from synthetic indicators and the fixed 60%+ threshold rules.

**Architecture:** Add a parallel, non-breaking signal-emission subsystem in `indicators` schema: a static rule catalog (`codex_signal_rules`), an append-only emitted signal table (`codex_signals`), and a small queue (`codex_signal_job_queue`) with SQL producer/consumer functions. Runtime flow is: scheduler tick -> enqueue current quarter-hour event bucket -> process jobs -> evaluate all rules against already-computed synthetic `v1` values -> insert fired signals idempotently.

**Tech Stack:** Supabase Postgres SQL migrations/functions, Python 3.11 runner script, pytest (SQL-shape + live integration checks), psql.

---

## Architecture Decision Summary

### Option A (Selected): Rule Catalog + Emitted Signal Log + Queue
- `indicators.codex_signal_rules`: one row per live rule (pair + config + operator + threshold + direction + base_accuracy).
- `indicators.codex_signals`: one row per fired rule event (pair + bucket_time + prediction + base_accuracy + source value).
- `indicators.codex_signal_job_queue`: forward-only queue keyed by `(pair, bucket_time)`.
- SQL functions for enqueue/process/evaluate; Python runner triggers them.

### Why Option A
- Isolated from existing indicator/synthetic pipelines.
- Easy to map and audit exactly which rule fired each prediction.
- Idempotent and replay-safe (`ON CONFLICT DO NOTHING/UPDATE`).
- Future-proof: new rules are inserts/updates to catalog, not code changes.

### Rejected Option B: Hardcode rules directly in one compute function
- Faster initial coding, but poor traceability and difficult to maintain.
- Higher risk of silent drift when thresholds are updated.

---

### Task 1: Freeze Rule Set Into Source-Controlled Spec

**Files:**
- Create: `docs/discoveries/codex_signal_rules_v1.md`
- Test: `scripts/synthetic_indicators/tests/test_codex_signal_rules_spec.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_codex_signal_rules_spec_contains_all_pairs_and_rules():
    text = Path("docs/discoveries/codex_signal_rules_v1.md").read_text()
    for s in [
        "BTC-USD", "ETH-USD", "SOL-USD",
        "syn_early_momentum_divergence_tplus1",
        "syn_rsi_velocity_5m_3bar_z20",
        "syn_oi_funding_impulse_tplus2",
        "base_accuracy",
    ]:
        assert s in text
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_rules_spec.py -v`
Expected: FAIL (file missing).

**Step 3: Write minimal implementation**
- Add markdown table listing each 60%+ rule exactly:
  - pair
  - synthetic `config_id`
  - operator (`>=`/`<=`)
  - threshold
  - prediction (`up`/`down`)
  - base accuracy
  - support metadata

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_rules_spec.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add docs/discoveries/codex_signal_rules_v1.md scripts/synthetic_indicators/tests/test_codex_signal_rules_spec.py
git commit -m "docs: freeze codex signal rule catalog v1"
```

---

### Task 2: Create Codex Signals Schema (Tables + Comments)

**Files:**
- Create: `supabase/migrations/20260211_160000_create_codex_signals_tables.sql`
- Test: `scripts/synthetic_indicators/tests/test_codex_signals_migration_shape.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_codex_signals_migration_has_required_tables_and_uniques():
    sql = Path("supabase/migrations/20260211_160000_create_codex_signals_tables.sql").read_text().lower()
    required = [
        "create table if not exists indicators.codex_signal_rules",
        "create table if not exists indicators.codex_signals",
        "create table if not exists indicators.codex_signal_job_queue",
        "unique (pair, bucket_time, rule_id)",
        "comment on table indicators.codex_signals",
    ]
    for r in required:
        assert r in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signals_migration_shape.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- `indicators.codex_signal_rules` columns:
  - `rule_id text primary key`
  - `pair text not null`
  - `config_id text not null references indicators.synthetic_indicator_configs(config_id)`
  - `operator text check (operator in ('>=','<='))`
  - `threshold numeric not null`
  - `prediction text check (prediction in ('up','down'))`
  - `base_accuracy numeric not null`
  - `support_n integer not null`
  - `support_pct numeric not null`
  - `is_active boolean not null default true`
  - `created_at timestamptz not null default now()`
- `indicators.codex_signals` columns:
  - `id bigint identity primary key`
  - `pair text not null`
  - `bucket_time timestamptz not null`
  - `rule_id text not null references indicators.codex_signal_rules(rule_id)`
  - `prediction text not null`
  - `signals_passed integer not null default 1`
  - `base_accuracy numeric not null`
  - `indicator_value numeric not null`
  - `config_id text not null`
  - `fired_at timestamptz not null default now()`
  - `decision_minute timestamptz not null default now()`
  - unique `(pair, bucket_time, rule_id)`
- `indicators.codex_signal_job_queue` columns:
  - `(pair, bucket_time, status, attempts, error_message, created_at, started_at, completed_at)`
  - unique `(pair, bucket_time)`
- Add indexes + complete `COMMENT ON TABLE/COLUMN` coverage.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signals_migration_shape.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_160000_create_codex_signals_tables.sql scripts/synthetic_indicators/tests/test_codex_signals_migration_shape.py
git commit -m "feat: add codex signals schema tables and queue"
```

---

### Task 3: Seed Rule Catalog With Current 60%+ Threshold Rules

**Files:**
- Create: `supabase/migrations/20260211_161000_seed_codex_signal_rules_v1.sql`
- Test: `scripts/synthetic_indicators/tests/test_codex_signal_rules_seed_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_codex_signal_rules_seed_contains_expected_rule_ids():
    sql = Path("supabase/migrations/20260211_161000_seed_codex_signal_rules_v1.sql").read_text()
    for rid in [
        "btc_syn_rsi_velocity_up_ge_1_489539",
        "eth_syn_emd_down_ge_0_366086",
        "sol_syn_oi_funding_down_ge_1_606966",
    ]:
        assert rid in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_rules_seed_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Insert/Upsert all current 60%+ rules (all three pairs).
- Store exact threshold, direction, base accuracy, support_n, support_pct.
- Set `is_active=true`.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_rules_seed_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_161000_seed_codex_signal_rules_v1.sql scripts/synthetic_indicators/tests/test_codex_signal_rules_seed_sql.py
git commit -m "feat: seed codex signal rules v1"
```

---

### Task 4: Implement SQL Evaluate Function (Single Bucket)

**Files:**
- Create: `supabase/migrations/20260211_162000_create_codex_signal_functions.sql`
- Test: `scripts/synthetic_indicators/tests/test_codex_signal_functions_sql.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_codex_signal_functions_exist_in_sql():
    sql = Path("supabase/migrations/20260211_162000_create_codex_signal_functions.sql").read_text().lower()
    for fn in [
        "fn_emit_codex_signals_for_bucket",
        "fn_enqueue_codex_signal_jobs",
        "fn_process_codex_signal_jobs",
    ]:
        assert fn in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_functions_sql.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- `fn_emit_codex_signals_for_bucket(p_pair text, p_bucket_time timestamptz)`:
  - join `codex_signal_rules` to `synthetic_indicator_values` (`v1`) by `pair/config_id/bucket_time`.
  - evaluate operator condition:
    - `>= threshold`
    - `<= threshold`
  - insert fired rows into `codex_signals` with `prediction`, `base_accuracy`, `indicator_value`.
  - idempotent via `ON CONFLICT (pair,bucket_time,rule_id) DO UPDATE`.
  - after insert/upsert, set `signals_passed` for each fired row as:
    - `count(*)` over `(pair, bucket_time, prediction)` for all fired rules in that same decision window.
  - result: if 2 or 3 rules align on the same direction for that pair/window, each emitted row carries `signals_passed=2` or `3`.
- `fn_enqueue_codex_signal_jobs(p_lookback interval default interval '30 minutes')`:
  - derive quarter-hour `bucket_time` candidates in recent window.
  - enqueue `(pair,bucket_time)` for BTC/ETH/SOL.
  - forward operation only (no historical sweep).
- `fn_process_codex_signal_jobs(p_batch_size int default 200)`:
  - claim pending jobs with `FOR UPDATE SKIP LOCKED`.
  - call `fn_emit_codex_signals_for_bucket`.
  - mark done/failed with retry-safe status updates.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_functions_sql.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_162000_create_codex_signal_functions.sql scripts/synthetic_indicators/tests/test_codex_signal_functions_sql.py
git commit -m "feat: add codex signal emit/enqueue/process functions"
```

---

### Task 5: Add Realtime Runner Script (Forward-Only)

**Files:**
- Create: `scripts/synthetic_indicators/run_codex_signals.py`
- Test: `scripts/synthetic_indicators/tests/test_codex_signals_runner_contracts.py`

**Step 1: Write the failing test**

```python
from pathlib import Path

def test_runner_calls_codex_queue_functions_only():
    text = Path("scripts/synthetic_indicators/run_codex_signals.py").read_text()
    assert "fn_enqueue_codex_signal_jobs" in text
    assert "fn_process_codex_signal_jobs" in text
    assert "fn_backfill" not in text.lower()
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signals_runner_contracts.py -v`
Expected: FAIL.

**Step 3: Write minimal implementation**
- Runner modes:
  - `incremental` (default): enqueue + process
  - `healthcheck`: queue status + latest signal times
- Output artifacts:
  - `scripts/output/codex_signals/<run_id>/result.json`
  - `REPORT.md`
- Keep runtime stateless and idempotent.

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signals_runner_contracts.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/run_codex_signals.py scripts/synthetic_indicators/tests/test_codex_signals_runner_contracts.py
git commit -m "feat: add codex signals realtime runner"
```

---

### Task 6: Integration Tests (Realtime Behavior + Correctness)

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_integration_codex_signals.py`

**Step 1: Write the failing integration tests**

```python
@pytest.mark.integration
def test_codex_signal_emit_writes_rows_when_rules_match():
    # call process function, assert new rows in indicators.codex_signals for recent buckets

@pytest.mark.integration
def test_codex_signal_rows_have_expected_columns_and_predictions():
    # verify pair,bucket_time,rule_id,prediction,base_accuracy,indicator_value populated
    # verify signals_passed exists and is >= 1

@pytest.mark.integration
def test_codex_signal_signals_passed_matches_directional_group_count():
    # for each (pair, bucket_time, prediction), assert:
    # signals_passed == count(rows in that same group)

@pytest.mark.integration
def test_codex_signal_process_is_idempotent():
    # run process twice, assert no duplicate (pair,bucket_time,rule_id)
```

**Step 2: Run tests to verify failures before implementation**

Run: `pytest scripts/synthetic_indicators/tests/test_integration_codex_signals.py -v`
Expected: FAIL/skip before migration apply.

**Step 3: Implement DB checks in tests**
- Skip safely if `SUPABASE_DB_URL` absent.
- Skip if codex functions are not yet applied.
- Validate job transitions and inserted row counts in recent 30m.

**Step 4: Run integration tests after migrations**

Run: `pytest scripts/synthetic_indicators/tests/test_integration_codex_signals.py -v`
Expected: PASS.

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/tests/test_integration_codex_signals.py
git commit -m "test: add codex signals integration and idempotency coverage"
```

---

### Task 7: Non-Regression Tests for Existing Pipelines

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_non_regression_codex_signals.py`

**Step 1: Write failing non-regression test**

```python
@pytest.mark.integration
def test_codex_signal_run_does_not_change_indicator_values_count():
    # count indicators.indicator_values in recent window before/after
    # run codex process
    # assert counts unchanged
```

**Step 2: Run test to verify behavior**

Run: `pytest scripts/synthetic_indicators/tests/test_non_regression_codex_signals.py -v`
Expected: PASS after implementation.

**Step 3: Commit**

```bash
git add scripts/synthetic_indicators/tests/test_non_regression_codex_signals.py
git commit -m "test: verify codex signals pipeline is non-breaking"
```

---

### Task 8: Documentation + Operational Runbook

**Files:**
- Modify: `docs/SYNTHETIC_INDICATORS_SCHEMA.md`
- Modify: `INDICATORS_SCHEMA.md`
- Create: `docs/discoveries/codex_signals_v1_runbook.md`
- (Optional) Modify: `docs/api/indicators.openapi.yaml`

**Step 1: Add schema docs**
- Describe each new table and function purpose.
- Document rule lifecycle (v1 static set, future versioning).

**Step 2: Add runtime schedule docs**
- Required external cadence: run incremental at `:02/:17/:32/:47` UTC.
- Clarify data readiness assumptions (`t_plus_1m`/`t_plus_2m` already computed).

**Step 3: Add troubleshooting section**
- queue stuck in `failed`
- missing synthetic values -> no signal rows
- duplicate guard behavior

**Step 4: Commit**

```bash
git add docs/SYNTHETIC_INDICATORS_SCHEMA.md INDICATORS_SCHEMA.md docs/discoveries/codex_signals_v1_runbook.md docs/api/indicators.openapi.yaml
git commit -m "docs: add codex signals schema and realtime runbook"
```

---

## Verification Before Completion

Run in this order:

1. `pytest -q scripts/synthetic_indicators/tests/test_codex_signal_rules_spec.py`
2. `pytest -q scripts/synthetic_indicators/tests/test_codex_signals_migration_shape.py`
3. `pytest -q scripts/synthetic_indicators/tests/test_codex_signal_rules_seed_sql.py`
4. `pytest -q scripts/synthetic_indicators/tests/test_codex_signal_functions_sql.py`
5. `pytest -q scripts/synthetic_indicators/tests/test_codex_signals_runner_contracts.py`
6. Apply migrations in order (`160000`, `161000`, `162000`).
7. `python3 scripts/synthetic_indicators/run_codex_signals.py --mode incremental --batch-size 300 --rounds 2`
8. `pytest -q scripts/synthetic_indicators/tests/test_integration_codex_signals.py`
9. `pytest -q scripts/synthetic_indicators/tests/test_non_regression_codex_signals.py`
10. `pytest -q scripts/synthetic_indicators/tests`

Expected success criteria:
- `codex_signals` rows appear only when rules are satisfied.
- rows include correct `pair`, `bucket_time`, `prediction`, `base_accuracy`, `indicator_value`.
- no duplicates for same `(pair,bucket_time,rule_id)`.
- existing indicator/synthetic pipelines remain unchanged.

---

## Operational Contract (Post-Deploy)

- Scheduler invokes incremental runner at UTC `:02/:17/:32/:47`.
- Each run enqueues recent buckets and processes jobs idempotently.
- Consumer/UI can read `indicators.codex_signals` directly.
- Optional convenience view in later phase: best signal per pair/bucket (highest `base_accuracy`).
