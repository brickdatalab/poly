# Crypto + Market Context Streamers Zero-Downtime Migration and OHLCV Backfill Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Keep ingestion live 24/7 while migrating websocket ingestion architecture in GCP, then backfill missing `ohlcv_1m` minutes and downstream rollups with production-equivalent semantics.

**Architecture:** Use a phased event-driven dual-run migration. Keep `n8n-production` untouched as current producer while a parallel hardened streamer stack is deployed in GCP, validated in shadow mode, and cut over with immediate rollback. Backfill is split into two tracks: reconstruct missing trade-level input first (preferred), then recompute OHLCV and rollups with existing DB logic.

**Tech Stack:** GCP Compute Engine, Cloud Run, Pub/Sub, Cloud Monitoring, Supabase Postgres, Python 3.11 scripts, Playwright for console execution/verification.

## Confirmed Constraints and Evidence

- `n8n-production` VM must never be stopped.
- Missing window is identical for all three pairs: `2026-02-07T04:54:00Z` to `2026-02-07T23:59:00Z` (1146 missing minutes per pair).
- Current high-water mark in `indicators.ohlcv_1m` and `public.ohlcv_1m` is `2026-02-07 04:53:00+00` for BTC/ETH/SOL.
- `public.raw_trades` has no rows in the missing window, so DB-only backfill from existing raw trades cannot fill the gap.
- Trigger path is active on `public.raw_trades*` partitions via `indicators.fn_process_new_trade`.

## Backfill Source Priority (Locked)

1. **Primary (required):** `public.raw_trades` (existing rows) -> aggregate with same logic as `indicators.fn_process_new_trade` / `indicators.fn_backfill_ohlcv`.
2. **Secondary (required for this outage):** Coinbase historical trades API (trade-level ticks with side/price/size/time) -> insert into staging -> merge into `public.raw_trades`.
3. **Tertiary (only if explicitly approved):** Coinbase candles fallback for minutes with unrecoverable trade gaps. This does not preserve true `buy_volume`, `sell_volume`, and exact `trade_count`.

For this outage, source #2 is expected to be used because source #1 has zero rows for the window.

---

### Task 1: Baseline Snapshot and Guardrails

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/ops_snapshot_ohlcv_state.py`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/output/` (reports)
- Modify: `/Users/vitolo/Desktop/projects/poly/base-project-analysis-2-6-2026.md` (append run log only if approved for docs updates)
- Create: `/Users/vitolo/Desktop/projects/poly/README.md` (schema change table, if missing and approved)
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/output/pre_migration_snapshot_*.json`

**Step 1: Write the failing test**

```python
def test_snapshot_contains_required_sections():
    payload = run_snapshot()
    assert "ohlcv_1m_max_by_pair" in payload
    assert "missing_minutes_by_pair" in payload
    assert "stream_health" in payload
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_ops_snapshot_ohlcv_state.py -v`
Expected: FAIL (script/test not present yet)

**Step 3: Write minimal implementation**

- Query and persist:
  - max bucket per pair across `public.ohlcv_1m` and `indicators.ohlcv_1m`
  - missing-minute counts for target window
  - `websocket_heartbeat` latest row
  - latest `raw_trades` timestamps per pair

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_ops_snapshot_ohlcv_state.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/scripts/ops_snapshot_ohlcv_state.py /Users/vitolo/Desktop/projects/poly/scripts/tests/test_ops_snapshot_ohlcv_state.py
git commit -m "chore: add OHLCV state snapshot and guardrail report"
```

---

### Task 2: Deploy Parallel Streamer Backbone in GCP (No Cutover Yet)

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-streamer-shadow-deploy.md`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/gcp_validate_shadow_stream.py`
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/output/gcp_shadow_validation_*.json`

**Step 1: Write the failing test**

```python
def test_shadow_validator_detects_no_live_messages():
    result = validate_shadow_window(minutes=2)
    assert result["messages_seen"] > 0
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_gcp_validate_shadow_stream.py -v`
Expected: FAIL before deployment and subscriptions exist

**Step 3: Write minimal implementation**

- Provision (in GCP) a shadow ingestion path:
  - `crypto-streamer-shadow` service
  - `market-context-streamer-shadow` service
  - Pub/Sub topics/subscriptions for each stream
- Keep current `n8n-production` live and unchanged.
- No writes to production OHLCV tables from shadow path yet.

**Step 4: Run test to verify it passes**

Run: `python3 /Users/vitolo/Desktop/projects/poly/scripts/gcp_validate_shadow_stream.py --minutes 5`
Expected: non-zero messages for all configured pairs/streams.

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-streamer-shadow-deploy.md /Users/vitolo/Desktop/projects/poly/scripts/gcp_validate_shadow_stream.py
git commit -m "ops: add shadow streamer deploy and validation runbook"
```

---

### Task 3: Implement High-Availability Runtime Controls

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-ha-controls.md`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/check_ingestion_slo.py`
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/output/ingestion_slo_*.json`

**Step 1: Write the failing test**

```python
def test_slo_check_fails_if_gap_exceeds_threshold():
    report = run_slo_check(max_gap_seconds=90)
    assert report["status"] == "PASS"
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_check_ingestion_slo.py -v`
Expected: FAIL before alerting and checks are wired

**Step 3: Write minimal implementation**

- Define SLO:
  - no pair older than 90 seconds from current UTC for latest `ohlcv_1m` bucket
  - heartbeat freshness <= 60 seconds
- Add health checks and restart policy for stream containers/services.
- Add alert routes for gap breaches.

**Step 4: Run test to verify it passes**

Run: `python3 /Users/vitolo/Desktop/projects/poly/scripts/check_ingestion_slo.py --max-gap-seconds 90`
Expected: PASS in healthy state, FAIL when intentionally simulated stale condition.

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-ha-controls.md /Users/vitolo/Desktop/projects/poly/scripts/check_ingestion_slo.py
git commit -m "ops: add ingestion SLO checks and HA control runbook"
```

---

### Task 4: Controlled Cutover With Rollback

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-cutover-and-rollback.md`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/verify_post_cutover_continuity.py`
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/output/post_cutover_validation_*.json`

**Step 1: Write the failing test**

```python
def test_continuity_check_requires_all_three_pairs():
    result = continuity_check(window_minutes=30)
    assert result["pairs_ok"] == ["BTC-USD", "ETH-USD", "SOL-USD"]
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_verify_post_cutover_continuity.py -v`
Expected: FAIL before script implementation

**Step 3: Write minimal implementation**

- Cutover sequence:
  - keep `n8n-production` running
  - switch writer authority to shadow stack for crypto + market context
  - monitor 30 minutes for continuity and lag
- Rollback sequence:
  - revert writer authority to previous path immediately on any SLO breach
  - preserve incoming message queue backlog

**Step 4: Run test to verify it passes**

Run: `python3 /Users/vitolo/Desktop/projects/poly/scripts/verify_post_cutover_continuity.py --window-minutes 30`
Expected: PASS when all pairs have continuous minute buckets.

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/gcp-cutover-and-rollback.md /Users/vitolo/Desktop/projects/poly/scripts/verify_post_cutover_continuity.py
git commit -m "ops: add cutover rollback playbook and continuity verifier"
```

---

### Task 5: Trade-Level Backfill (Primary Recovery Path)

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/backfill_raw_trades_from_coinbase.py`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/rebuild_ohlcv_from_raw_trades_window.py`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/output/backfill_raw_trades_*.json`
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/tests/test_backfill_raw_trades_from_coinbase.py`

**Step 1: Write the failing test**

```python
def test_backfill_builds_raw_trade_rows_with_required_fields():
    rows = fetch_coinbase_trades_window("BTC-USD", start, end)
    assert {"pair", "trade_id", "price", "size", "side", "executed_at"} <= set(rows[0].keys())
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_backfill_raw_trades_from_coinbase.py -v`
Expected: FAIL before implementation

**Step 3: Write minimal implementation**

- Pull trade-level history per pair and outage window from Coinbase.
- Insert into staging table first.
- Merge into `public.raw_trades` with idempotent conflict handling.
- Recompute `indicators.ohlcv_1m` for window using the same aggregation semantics as `indicators.fn_backfill_ohlcv`.

**Step 4: Run test to verify it passes**

Run: `python3 /Users/vitolo/Desktop/projects/poly/scripts/backfill_raw_trades_from_coinbase.py --start '2026-02-07T04:54:00Z' --end '2026-02-08T00:00:00Z' --pairs BTC-USD,ETH-USD,SOL-USD --dry-run`
Expected: PASS with deterministic row counts and preview output.

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/scripts/backfill_raw_trades_from_coinbase.py /Users/vitolo/Desktop/projects/poly/scripts/rebuild_ohlcv_from_raw_trades_window.py /Users/vitolo/Desktop/projects/poly/scripts/tests/test_backfill_raw_trades_from_coinbase.py
git commit -m "feat: add trade-level outage backfill and ohlcv rebuild scripts"
```

---

### Task 6: Rollup Rebuild and Gap Verification

**Files:**
- Reuse: `/Users/vitolo/Desktop/projects/poly/scripts/scripts_past/backfill_rollups_missing_only.py`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/verify_no_gaps_all_timeframes.py`
- Create: `/Users/vitolo/Desktop/projects/poly/scripts/output/rollup_gap_verification_*.json`
- Test: `/Users/vitolo/Desktop/projects/poly/scripts/tests/test_verify_no_gaps_all_timeframes.py`

**Step 1: Write the failing test**

```python
def test_gap_verifier_reports_zero_missing_for_all_pairs_and_timeframes():
    report = verify_no_gaps(start, end, pairs=["BTC-USD", "ETH-USD", "SOL-USD"])
    assert report["missing_total"] == 0
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_verify_no_gaps_all_timeframes.py -v`
Expected: FAIL before script implementation

**Step 3: Write minimal implementation**

- Backfill missing rollups (5m, 10m, 15m, 30m, 45m, 1h, 2h, 6h, 12h) from `indicators.ohlcv_1m`.
- Verify no missing buckets for all 3 pairs in target window.
- Validate bucket alignment and latest freshness.

**Step 4: Run test to verify it passes**

Run: `python3 /Users/vitolo/Desktop/projects/poly/scripts/verify_no_gaps_all_timeframes.py --start '2026-02-07T04:54:00Z' --end '2026-02-08T00:00:00Z' --pairs BTC-USD,ETH-USD,SOL-USD`
Expected: PASS with zero missing rows and aligned buckets.

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/scripts/verify_no_gaps_all_timeframes.py /Users/vitolo/Desktop/projects/poly/scripts/tests/test_verify_no_gaps_all_timeframes.py
git commit -m "feat: add full OHLCV gap verifier for 1m and rollups"
```

---

### Task 7: Documentation and Change Log Discipline

**Files:**
- Create or modify: `/Users/vitolo/Desktop/projects/poly/README.md`
- Modify: `/Users/vitolo/Desktop/projects/poly/base-project-analysis-2-6-2026.md`
- Create: `/Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/schema-change-log-template.md`

**Step 1: Write the failing test**

```python
def test_schema_change_log_has_latest_migration_entry():
    log = load_schema_change_log()
    assert "OHLCV outage backfill" in log[-1]["change"]
```

**Step 2: Run test to verify it fails**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_schema_change_log.py -v`
Expected: FAIL before schema log format is introduced

**Step 3: Write minimal implementation**

- Add/maintain README table with columns:
  - UTC timestamp
  - environment
  - object changed
  - reason
  - rollback note
  - operator
- Require one log row per schema mutation.

**Step 4: Run test to verify it passes**

Run: `python3 -m pytest /Users/vitolo/Desktop/projects/poly/scripts/tests/test_schema_change_log.py -v`
Expected: PASS

**Step 5: Commit**

```bash
git add /Users/vitolo/Desktop/projects/poly/README.md /Users/vitolo/Desktop/projects/poly/base-project-analysis-2-6-2026.md /Users/vitolo/Desktop/projects/poly/docs/plans/runbooks/schema-change-log-template.md
git commit -m "docs: add required schema change log workflow"
```

---

## Phased Migration Sequencing (Live Ingestion Preserved)

1. Baseline + guardrails (read-only checks only).
2. Shadow deployment for both streamers in GCP.
3. HA controls + alerting in place.
4. Controlled cutover with rollback hot path.
5. Trade-level outage backfill for missing window.
6. Rollup refill + gap verification across all timeframes.
7. Documentation updates for every schema change.

## Validation Checklist for Final Acceptance

- `n8n-production` remained running during entire migration.
- `indicators.ohlcv_1m` has continuous minute coverage for BTC/ETH/SOL in outage window.
- No gaps in `ohlcv_5m`, `ohlcv_10m`, `ohlcv_15m`, `ohlcv_30m`, `ohlcv_45m`, `ohlcv_1h`, `ohlcv_2h`, `ohlcv_6h`, `ohlcv_12h`.
- `websocket_heartbeat` freshness remains inside SLO.
- Alerting catches stalled ingestion within target threshold.
- README schema-change table updated for every mutation.
