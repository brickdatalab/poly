# Reliability Issues #1-#4 Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Close active reliability/data-quality issues #1, #2, #3, #4 with minimal, reversible migrations/scripts/tests, while preserving websocket ingestion behavior unchanged.

**Architecture:** Use migration-first control-plane additions in `ops` schema, utility-script contracts under `utility-scripts/`, and targeted bounded data repair SQL for OHLCV anomalies. Validate each issue with deterministic SQL evidence and test contracts, then update changelog + issue progress.

**Tech Stack:** Supabase Postgres (migrations, pg_cron, SQL functions), Python 3.11 utilities, pytest contract tests, GitHub issue docs/comments.

---

### Task 1: Baseline + Scope Lock

**Files:**
- Modify: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`
- Create: `scripts/output/reliability_issue_2026_02_25_baseline.json`

**Step 1: Capture read-only baseline evidence (failing state expected)**

Run SQL evidence queries for:
1. OHLCV 5d missing/gap/duplicate/misaligned for `1m/5m/10m/15m`
2. OI cron schedules and latest OI/OI-features lag
3. Existing absence of issue #2/#4 control-plane objects

**Step 2: Persist baseline artifact**

Write baseline JSON under `scripts/output/` with UTC timestamp and query outputs.

**Step 3: Record baseline in changelog**

Append short checkpoint note with factual counts.

**Step 4: Commit**

```bash
git add docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md scripts/output/reliability_issue_2026_02_25_baseline.json
git commit -m "docs: capture reliability issues #1-#4 baseline evidence"
```

---

### Task 2: Issue #3 (OHLCV remediation) TDD + Migration + Bounded Repair

**Files:**
- Create: `supabase/migrations/20260225_110000_ohlcv_fractional_placeholder_cleanup.sql`
- Create: `tests/ops/test_ohlcv_fractional_placeholder_cleanup_sql_shape.py`
- Modify: `docs/issues/2026-02-25-ohlcv-missing-values-remediation-ticket.md`
- Modify: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`
- Create: `scripts/output/ohlcv_issue3_repair_20260225.json`

**Step 1: Write failing test first**

Add migration-shape test asserting cleanup function exists and only targets fractional-second placeholder rows (`volume=0`, `trade_count=0`, non-minute-aligned `bucket_time`) plus deterministic return payload.

**Step 2: Run failing test**

```bash
pytest -q tests/ops/test_ohlcv_fractional_placeholder_cleanup_sql_shape.py
```
Expected: FAIL (migration file missing).

**Step 3: Implement migration (minimal)**

Create cleanup + orchestrator function(s) that:
1. remove fractional placeholder 1m rows safely
2. run existing rollup/backfill path for bounded window
3. return machine-readable action summary

**Step 4: Run test to green**

```bash
pytest -q tests/ops/test_ohlcv_fractional_placeholder_cleanup_sql_shape.py
```
Expected: PASS.

**Step 5: Apply migration + execute bounded repair**

1. Dry-run counts (rows to delete/fix)
2. Execute cleanup and repair in bounded window
3. Re-check 5d and 7d OHLCV integrity with SQL evidence

**Step 6: Update docs/ticket status**

Mark checklist progress and append executed SQL evidence.

**Step 7: Commit**

```bash
git add supabase/migrations/20260225_110000_ohlcv_fractional_placeholder_cleanup.sql \
  tests/ops/test_ohlcv_fractional_placeholder_cleanup_sql_shape.py \
  docs/issues/2026-02-25-ohlcv-missing-values-remediation-ticket.md \
  docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md \
  scripts/output/ohlcv_issue3_repair_20260225.json
git commit -m "fix(ohlcv): repair fractional placeholders and close issue #3"
```

---

### Task 3: Issue #1 (OI 5-minute cadence) TDD + Scheduler/SLO Update

**Files:**
- Create: `supabase/migrations/20260225_120000_open_interest_5m_cadence.sql`
- Create: `tests/ops/test_open_interest_5m_cadence_sql_shape.py`
- Modify: `utility-scripts/open_interest/README.md`
- Modify: `docs/issues/2026-02-25-open-interest-5m-freshness-ticket.md`
- Modify: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`
- Create: `scripts/output/open_interest_issue1_rollout_20260225.json`

**Step 1: Write failing test first**

Assert migration updates:
1. cron schedules to 5-minute cadence (main + retry offset)
2. SLO thresholds for `open_interest` and `oi_features` suitable for 5m cadence

**Step 2: Run failing test**

```bash
pytest -q tests/ops/test_open_interest_5m_cadence_sql_shape.py
```
Expected: FAIL.

**Step 3: Implement migration**

Use `cron.unschedule` + `cron.schedule` replacement and table-driven SLO updates with conservative values.

**Step 4: Run test to green**

```bash
pytest -q tests/ops/test_open_interest_5m_cadence_sql_shape.py
```
Expected: PASS.

**Step 5: Apply migration + verify runtime**

1. Verify cron schedule in `cron.job`
2. Verify OI and OI feature freshness post-change
3. Verify no duplicate/misaligned OI buckets in lookback window

**Step 6: Update docs/ticket status**

Capture exact schedule values and validation metrics.

**Step 7: Commit**

```bash
git add supabase/migrations/20260225_120000_open_interest_5m_cadence.sql \
  tests/ops/test_open_interest_5m_cadence_sql_shape.py \
  utility-scripts/open_interest/README.md \
  docs/issues/2026-02-25-open-interest-5m-freshness-ticket.md \
  docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md \
  scripts/output/open_interest_issue1_rollout_20260225.json
git commit -m "feat(oi): move ingest cadence to 5-minute schedule for issue #1"
```

---

### Task 4: Issues #2 and #4 (Master indicator health + compute latency) TDD + Contracts + Utility

**Files:**
- Create: `supabase/migrations/20260225_130000_indicator_master_health_and_latency.sql`
- Create: `utility-scripts/indicators/check_indicator_master_health.py`
- Create: `utility-scripts/indicators/check_indicator_compute_latency.py`
- Create: `utility-scripts/indicators/README.md`
- Create: `utility-scripts/indicators/output/.gitkeep`
- Create: `contracts/openai/master_indicator_registry.schema.json`
- Create: `contracts/openai/indicator_health_check_input.schema.json`
- Create: `contracts/openai/indicator_health_report.schema.json`
- Create: `contracts/openai/indicator_compute_latency_report.schema.json`
- Create: `tests/ops/test_indicator_master_health_contracts.py`
- Create: `tests/ops/test_indicator_latency_contracts.py`
- Modify: `utility-scripts/README.md`
- Modify: `docs/operations/ops-catalog.md`
- Modify: `docs/issues/2026-02-25-master-indicator-health-contract-ticket.md`
- Modify: `docs/issues/2026-02-25-indicator-compute-latency-slo-ticket.md`
- Modify: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`
- Create: `scripts/output/indicator_master_latency_issue2_4_20260225.json`

**Step 1: Write failing tests first**

1. SQL migration shape tests for required tables/functions/reason codes
2. JSON schema strict wrapper tests (`strict: true`, `additionalProperties: false`)
3. Utility script contract tests for deterministic key output shape

**Step 2: Run tests (expect fail)**

```bash
pytest -q tests/ops/test_indicator_master_health_contracts.py tests/ops/test_indicator_latency_contracts.py
```

**Step 3: Implement minimal migration + scripts + schemas**

1. `ops.master_indicator_registry` (no `active` column)
2. registry sync function
3. `ops.fn_indicator_master_health_snapshot(...)`
4. `ops.indicator_latency_slo_config`, `ops.indicator_latency_log`
5. `ops.fn_indicator_compute_latency_snapshot(...)`
6. optional latency watchdog helper
7. utility scripts and runbook docs
8. strict OpenAI contract schemas

**Step 4: Re-run tests to green**

```bash
pytest -q tests/ops/test_indicator_master_health_contracts.py tests/ops/test_indicator_latency_contracts.py
```

**Step 5: Apply migration + run utility validations**

1. verify snapshot functions return structured rows + summary lights
2. verify no missing mandatory fields/reason codes in outputs
3. capture sample outputs in artifact JSON

**Step 6: Update docs/tickets**

Mark checklist progress and include residual risks.

**Step 7: Commit**

```bash
git add supabase/migrations/20260225_130000_indicator_master_health_and_latency.sql \
  utility-scripts/indicators contracts/openai tests/ops/test_indicator_master_health_contracts.py \
  tests/ops/test_indicator_latency_contracts.py utility-scripts/README.md docs/operations/ops-catalog.md \
  docs/issues/2026-02-25-master-indicator-health-contract-ticket.md \
  docs/issues/2026-02-25-indicator-compute-latency-slo-ticket.md \
  docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md \
  scripts/output/indicator_master_latency_issue2_4_20260225.json
git commit -m "feat(ops): add indicator master health and latency controls for issues #2/#4"
```

---

### Task 5: End-to-End Verification + GitHub Issue Updates + Push

**Files:**
- Modify: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`

**Step 1: Run verification suite**

```bash
pytest -q tests/ops/test_ohlcv_fractional_placeholder_cleanup_sql_shape.py \
  tests/ops/test_open_interest_5m_cadence_sql_shape.py \
  tests/ops/test_indicator_master_health_contracts.py \
  tests/ops/test_indicator_latency_contracts.py \
  tests/ops/test_source_health_utilities_contract.py \
  tests/ops/test_ops_pipeline_supervisor_sql_shape.py \
  tests/ops/test_oi_edge_functions_contract.py
```

Also run read-only SQL validations for:
1. OHLCV 5d/7d integrity
2. OI/OI-features freshness + schedule
3. indicator master and latency function outputs

**Step 2: Verify no ingestion-path modifications**

Confirm no edits to websocket ingestion VM architecture path.

**Step 3: Update GitHub issues with completion evidence**

For each issue: changes, validation evidence, residual risk, next actions.

**Step 4: Push commits**

```bash
git push origin codex/supabase-reliability-autofix
```

**Step 5: Final changelog checkpoint**

Append final UTC completion checkpoint + links to evidence artifacts.

