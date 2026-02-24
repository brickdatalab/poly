# Signal Pipeline Stability Recovery Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Restore reliable real-time signal generation and prevent silent data-stall failures from stopping codex signals.

**Architecture:** Add explicit runtime observability and deterministic fallback recovery around the existing `raw_trades -> ohlcv -> indicator_values -> synthetic_indicator_values -> codex_signals` chain. Keep current signal logic, but add guardrails that detect stale upstream inputs, record why a window emitted zero signals, and auto-heal by backfilling only missing intervals.

**Tech Stack:** PostgreSQL (Supabase), pg_cron, PL/pgSQL, Python 3, psql, existing scripts under `scripts/synthetic_indicators`.

---

### Task 1: Establish Incident Baseline (Root Cause Evidence)

**Files:**
- Create: `scripts/synthetic_indicators/debug_snapshot_pipeline_state.py`
- Create: `scripts/output/signal_pipeline_incident/` (runtime artifacts)
- Test: `scripts/synthetic_indicators/tests/test_debug_snapshot_pipeline_state.py`

**Step 1: Write the failing test**

```python
# test should fail until script writes required keys
required_keys = {
  "captured_at_utc", "raw_trades_max", "ohlcv_1m_max", "ohlcv_15m_max",
  "indicator_values_max", "synthetic_values_max", "codex_signals_max",
  "cron_jobs", "cron_recent_runs"
}
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_debug_snapshot_pipeline_state.py -v`
Expected: FAIL (script missing)

**Step 3: Write minimal implementation**
- Script dumps a single JSON snapshot with:
  - freshness per layer per pair
  - active cron jobs
  - last N cron run statuses
  - queue pending counts

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_debug_snapshot_pipeline_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/debug_snapshot_pipeline_state.py scripts/synthetic_indicators/tests/test_debug_snapshot_pipeline_state.py
git commit -m "chore: add reproducible pipeline debug snapshot"
```

---

### Task 2: Add “No Silent Failure” Audit Table for Every Decision Bucket

**Files:**
- Create: `supabase/migrations/20260211_210000_create_codex_signal_runtime_audit.sql`
- Test: `scripts/synthetic_indicators/tests/test_codex_signal_runtime_audit_sql.py`

**Step 1: Write the failing test**

```python
# migration must create table + unique key + indexes + comments
assert "create table if not exists indicators.codex_signal_runtime_audit" in sql
assert "unique (pair, bucket_time)" in sql
assert "missing_inputs" in sql
assert "evaluation_status" in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_runtime_audit_sql.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Add table:
  - `pair`, `bucket_time`
  - `evaluation_status` (`emitted`, `no_signal`, `stale_inputs`, `error`)
  - `active_rules`, `rules_with_inputs`, `rules_passed`
  - `missing_inputs` JSONB (`config_id -> missing_reason`)
  - `evaluated_at`
- Add index on `(bucket_time desc, pair)`

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_codex_signal_runtime_audit_sql.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_210000_create_codex_signal_runtime_audit.sql scripts/synthetic_indicators/tests/test_codex_signal_runtime_audit_sql.py
git commit -m "feat: add runtime audit table for per-window signal evaluation"
```

---

### Task 3: Instrument Emit Function to Always Write Audit Rows

**Files:**
- Modify: `supabase/migrations/20260211_182000_add_codex_signal_outcome_columns.sql` (or new follow-up migration replacing function)
- Test: `scripts/synthetic_indicators/tests/test_emit_function_audit_contract.py`

**Step 1: Write the failing test**

```python
# function must upsert audit row even when zero signals pass
assert "insert into indicators.codex_signal_runtime_audit" in sql
assert "on conflict (pair, bucket_time)" in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_emit_function_audit_contract.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- In `fn_emit_codex_signals_for_bucket`:
  - compute per-rule availability + pass/fail
  - when zero passes, still write audit row with reason:
    - `stale_inputs` if missing required synthetic values
    - else `no_signal`
  - keep existing codex signal emission unchanged

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_emit_function_audit_contract.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add supabase/migrations/<new-migration>.sql scripts/synthetic_indicators/tests/test_emit_function_audit_contract.py
git commit -m "feat: log no-signal and stale-input outcomes per bucket"
```

---

### Task 4: Add Automated Stale-Feed Recovery Worker (Host-Side)

**Files:**
- Create: `scripts/synthetic_indicators/recover_realtime_gap.py`
- Create: `scripts/synthetic_indicators/recover_realtime_gap.sh`
- Create: `scripts/synthetic_indicators/tests/test_recover_realtime_gap_args.py`
- Create: `docs/runbooks/realtime_recovery.md`

**Step 1: Write the failing test**

```python
# parser and dry-run output contract
assert "--max-lag-seconds" in help_text
assert "--pairs" in help_text
assert "--dry-run" in help_text
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_recover_realtime_gap_args.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Script flow:
  1. Read max `raw_trades.executed_at` per pair
  2. If lag > threshold (e.g. 90s), backfill missing window via Coinbase script
  3. Run `fn_backfill_ohlcv(interval '2 hours')`
  4. Recompute `indicator_values` for missing minute range only
  5. Run `fn_run_realtime_signal_tick(interval '90 minutes', ...)`
  6. Write JSON run report
- Shell wrapper for one-command execution

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_recover_realtime_gap_args.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/recover_realtime_gap.py scripts/synthetic_indicators/recover_realtime_gap.sh scripts/synthetic_indicators/tests/test_recover_realtime_gap_args.py docs/runbooks/realtime_recovery.md
git commit -m "feat: add automated stale-feed recovery worker"
```

---

### Task 5: Wire Recovery Worker to Guaranteed Schedule

**Files:**
- Create: `supabase/migrations/20260211_211000_add_recovery_health_jobs.sql`
- Test: `scripts/synthetic_indicators/tests/test_recovery_health_jobs_sql.py`

**Step 1: Write the failing test**

```python
assert "codex-signal-watchdog" in sql
assert "raw-trades-freshness-watchdog" in sql
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_recovery_health_jobs_sql.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Add/replace cron checks that:
  - verify freshness thresholds for `raw_trades`, `ohlcv_1m`, `indicator_values`
  - log heartbeat status
  - optionally call lightweight reconcile function
- Keep existing `codex-signal-tick-*` jobs intact

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_recovery_health_jobs_sql.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add supabase/migrations/20260211_211000_add_recovery_health_jobs.sql scripts/synthetic_indicators/tests/test_recovery_health_jobs_sql.py
git commit -m "feat: enforce freshness watchdog and health jobs"
```

---

### Task 6: Add End-to-End Failure Injection Test (Critical)

**Files:**
- Create: `scripts/synthetic_indicators/tests/test_realtime_pipeline_failure_injection.py`

**Step 1: Write the failing test**

```python
# scenario: stale raw_trades -> recovery script -> signals/audit recovered
assert result["recovered"] is True
assert result["post_recovery_lag_seconds"] <= 120
assert result["audit_rows_written"] > 0
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_realtime_pipeline_failure_injection.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Integration test in safe sandbox mode:
  - simulate stale condition by reading old window and skipping live ingestion
  - run recovery script
  - assert restored freshness and audit coverage

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_realtime_pipeline_failure_injection.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/tests/test_realtime_pipeline_failure_injection.py
git commit -m "test: add failure-injection coverage for stale feed recovery"
```

---

### Task 7: Backfill Audit Rows for Recent Windows (Operational Clarity)

**Files:**
- Create: `scripts/synthetic_indicators/backfill_signal_runtime_audit.py`
- Test: `scripts/synthetic_indicators/tests/test_backfill_signal_runtime_audit.py`

**Step 1: Write the failing test**

```python
assert "--from" in help_text and "--to" in help_text
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_backfill_signal_runtime_audit.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- For each pair and 15m bucket in range:
  - call `fn_emit_codex_signals_for_bucket` in dry audit mode or evaluation mode
  - ensure audit row exists with reasoned status

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_backfill_signal_runtime_audit.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/backfill_signal_runtime_audit.py scripts/synthetic_indicators/tests/test_backfill_signal_runtime_audit.py
git commit -m "feat: backfill per-window runtime audit rows"
```

---

### Task 8: Verification Gate Before Declaring Fixed

**Files:**
- Create: `scripts/synthetic_indicators/verify_realtime_stability_gate.py`
- Modify: `scripts/synthetic_indicators/verify_realtime_signal_pipeline.py`

**Step 1: Write the failing test**

```python
# must fail if any freshness lag exceeds SLO or missing audit rows
assert exit_code == 1
```

**Step 2: Run test to verify it fails**

Run: `pytest scripts/synthetic_indicators/tests/test_verify_realtime_stability_gate.py -v`
Expected: FAIL

**Step 3: Write minimal implementation**
- Gate checks:
  - freshness SLO: `raw_trades <= 90s`, `ohlcv_1m <= 120s`, `indicator_values <= 180s`
  - every 15m window in last 2 hours has either:
    - `codex_signals` row(s), or
    - `codex_signal_runtime_audit` row explaining no-signal
  - zero failed cron runs for critical jobs in last hour

**Step 4: Run test to verify it passes**

Run: `pytest scripts/synthetic_indicators/tests/test_verify_realtime_stability_gate.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add scripts/synthetic_indicators/verify_realtime_stability_gate.py scripts/synthetic_indicators/verify_realtime_signal_pipeline.py scripts/synthetic_indicators/tests/test_verify_realtime_stability_gate.py
git commit -m "feat: add realtime stability verification gate"
```

---

### Task 9: Controlled Rollout + Live Window Validation

**Files:**
- Modify: `docs/runbooks/realtime_recovery.md`
- Create: `scripts/output/signal_pipeline_incident/validation_<timestamp>.md`

**Step 1: Dry run verification**

Run:
- `python3 scripts/synthetic_indicators/debug_snapshot_pipeline_state.py`
- `python3 scripts/synthetic_indicators/verify_realtime_stability_gate.py`
Expected: PASS with all freshness SLOs met

**Step 2: Validate next 4 windows**
- At `:02`, `:17`, `:32`, `:47`:
  - confirm signals OR explicit audit rows per pair
  - confirm no silent gaps

**Step 3: Record proof**
- Save a concise validation report with timestamps and outcomes.

**Step 4: Commit runbook updates**

```bash
git add docs/runbooks/realtime_recovery.md scripts/output/signal_pipeline_incident/validation_<timestamp>.md
git commit -m "docs: add validated realtime recovery runbook and acceptance evidence"
```

---

## Acceptance Criteria (Must All Pass)

1. No silent windows: each pair/window gets either signal rows or audited no-signal reason.
2. Freshness SLOs continuously hold for 2 hours.
3. Recovery script closes a forced stale gap within 2 minutes.
4. `20:47`-style incident is reproducible in test and auto-healed by design.
5. No changes to existing signal math/rule thresholds unless explicitly approved.

## Rollback Plan

1. Disable new watchdog/recovery jobs only.
2. Keep existing `codex-signal-tick-main/retry/watchdog` intact.
3. Retain audit tables (read-only impact) even if recovery worker is disabled.

