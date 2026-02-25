# Trade Flow Snapshots Production Recovery And Hardening Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Recover `public.trade_flow_snapshots` to real-time freshness, backfill all missing minutes, and harden runtime so this outage class cannot silently recur.

**Architecture:** Keep ingestion unchanged (`GCP VM -> public.raw_trades`). Fix the failure in Supabase by replacing unbounded catch-up with bounded, idempotent minute-window processing. Add explicit freshness/error SLO checks and watchdog guardrails for `trade_flow_snapshots`, integrated into existing health/ops controls.

**Tech Stack:** Supabase Postgres (`plpgsql`, `pg_cron`), SQL migrations in `supabase/migrations`, Python health tooling in `scripts/healthcheck_all.py`, existing `ops` control-plane checks.

---

## Brainstorming Output (Options + Decision)

## Option A: Keep current function, just increase statement timeout
- Pros:
  - minimal change
  - fastest to apply
- Cons:
  - still unbounded work per tick
  - backlog can reappear and timeout again under heavier volume
  - violates reliability requirement for deterministic recovery

## Option B: One-time massive backfill + restore current cron
- Pros:
  - can clear immediate backlog
  - modest code change
- Cons:
  - same function design still fails after future outages
  - no bounded recovery mechanics
  - not “never happens again” grade

## Option C (Recommended): Bounded incremental tick + deterministic backfill + watchdog rails
- Pros:
  - prevents timeout loop even with large backlog
  - deterministic idempotent backfill and catch-up
  - aligns with GitOps + production hardening goals
- Cons:
  - requires new SQL functions + health checks + cron command update

### Decision
Choose **Option C**. It is the only option that both recovers now and addresses recurrence risk structurally.

---

## Architecture Design Progress
- [x] Step 1: Understand requirements and constraints
- [x] Step 2: Assess project size and team capabilities
- [x] Step 3: Select architecture pattern
- [x] Step 4: Define directory structure
- [x] Step 5: Document trade-offs and decision
- [x] Step 6: Validate against decision framework

## Constraints
1. Do not change websocket ingestion behavior or write-path on GCP VM.
2. Do not fabricate market data.
3. All DDL/runtime function changes ship via `supabase/migrations`.
4. Backfill must be chunked and idempotent.

---

### Task 1: Create Bounded Snapshot Build Primitives

**Files:**
- Create: `supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql`

**Step 1: Add canonical pair set helper**
- Add a stable source list (`BTC-USD`, `ETH-USD`, `SOL-USD`) used consistently by backfill/tick.

**Step 2: Add window upsert function**
- Create `public.fn_upsert_trade_flow_snapshots_window(p_start timestamptz, p_end timestamptz)`.
- Behavior:
  - process `[p_start, p_end)` in minute resolution.
  - compute:
    - latest price before minute boundary
    - 5m buy/sell, ratio, imbalance, cvd
    - 1m buy/sell and `cvd_delta_1m`
  - derive `cvd_cumulative` using prior anchor + cumulative minute deltas.
  - `ON CONFLICT (pair, snapshot_time)` upsert.

**Step 3: Add bounded tick function**
- Create `public.capture_trade_flow_snapshots_tick(p_as_of timestamptz default date_trunc('minute', now()), p_max_catchup_minutes int default 15)`.
- Behavior:
  - determine earliest missing minute across target pairs.
  - process at most `p_max_catchup_minutes` per tick.
  - no-op when already current.

**Step 4: Keep compatibility wrapper**
- Replace old `public.capture_trade_flow_snapshots()` body to delegate to bounded tick to preserve existing callers.

**Step 5: Commit**
```bash
git -C /Users/vitolo/Desktop/projects/poly add supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql
git -C /Users/vitolo/Desktop/projects/poly commit -m "fix: add bounded trade_flow snapshot tick and window upsert"
```

---

### Task 2: Add Deterministic Backfill Entry Point

**Files:**
- Modify: `supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql`

**Step 1: Add backfill orchestrator**
- Create `public.fn_backfill_trade_flow_snapshots(p_start timestamptz, p_end timestamptz, p_chunk_minutes int default 120)`.
- Behavior:
  - loop over chunks.
  - call `fn_upsert_trade_flow_snapshots_window` per chunk.
  - enforce bounds and positive chunk size.

**Step 2: Add safe execution notes in function comments**
- Include expected chunk sizing and idempotency semantics.

**Step 3: Commit**
```bash
git -C /Users/vitolo/Desktop/projects/poly add supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql
git -C /Users/vitolo/Desktop/projects/poly commit -m "feat: add chunked trade_flow snapshot backfill function"
```

---

### Task 3: Move Cron To Bounded Tick

**Files:**
- Modify: `supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql`

**Step 1: Update pg_cron command**
- Replace job command from:
  - `select public.capture_trade_flow_snapshots();`
- To:
  - `select public.capture_trade_flow_snapshots_tick();`

**Step 2: Ensure idempotent schedule management**
- Use `cron.job` lookup/update with guard conditions (no duplicate jobs).

**Step 3: Commit**
```bash
git -C /Users/vitolo/Desktop/projects/poly add supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql
git -C /Users/vitolo/Desktop/projects/poly commit -m "ops: switch trade_flow cron to bounded tick"
```

---

### Task 4: Apply Migration And Backfill Production

**Files:**
- Runbook record: `docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md`

**Step 1: Apply migration to production**
Run:
```sql
-- via Supabase migration apply path
```
Expected: migration succeeds without changing ingestion path.

**Step 2: Run one-time catch-up backfill**
Run:
```sql
select public.fn_backfill_trade_flow_snapshots(
  (select coalesce(max(snapshot_time), now() - interval '14 days') + interval '1 minute' from public.trade_flow_snapshots),
  date_trunc('minute', now()),
  120
);
```
Expected: missing window filled; no timeout loop.

**Step 3: Verify bounded tick picks up live cadence**
Run:
```sql
select public.capture_trade_flow_snapshots_tick();
```
Expected: near-real-time inserts continue each minute.

**Step 4: Commit runbook evidence update**
```bash
git -C /Users/vitolo/Desktop/projects/poly add docs/reports/2026-02-24-trade-flow-snapshots-incident-changelog.md
git -C /Users/vitolo/Desktop/projects/poly commit -m "docs: record production trade_flow snapshot recovery execution"
```

---

### Task 5: Add Hard Guardrails So Recurrence Is Visible And Actionable

**Files:**
- Modify: `scripts/healthcheck_all.py`
- Create: `supabase/migrations/20260224_204000_trade_flow_snapshot_watchdog.sql`
- Modify: `docs/runbooks/incident-response-slo.md`

**Step 1: Add dedicated `trade_flow_snapshots_freshness` check**
- Per pair freshness thresholds:
  - PASS <= 120s
  - WARN <= 300s
  - FAIL > 300s

**Step 2: Add `trade_flow_snapshot_cron_health` check**
- Track failures/successes for `trade_flow_snapshots_every_minute` in last 15m/60m.
- Fail criteria:
  - zero successes in 15m OR
  - >= 3 failures in 15m.

**Step 3: Add watchdog function + cron**
- Function behavior:
  - detect stale snapshot + repeated cron failures.
  - write incident row into `ops.pipeline_incident_log`.
  - optionally pause faulty job after retry budget exceeded.

**Step 4: Update SLO doc to include trade_flow snapshots**
- Add freshness objective and incident response requirement.

**Step 5: Commit**
```bash
git -C /Users/vitolo/Desktop/projects/poly add scripts/healthcheck_all.py supabase/migrations/20260224_204000_trade_flow_snapshot_watchdog.sql docs/runbooks/incident-response-slo.md
git -C /Users/vitolo/Desktop/projects/poly commit -m "hardening: add trade_flow snapshot health checks and watchdog"
```

---

### Task 6: Verification And Release Gates

**Files:**
- Test: `tests/ops/` (add or extend SQL/integration checks)

**Step 1: SQL correctness checks**
- Validate for each pair:
  - no missing minute in backfilled incident window
  - `cvd_cumulative` monotonic relation to `cvd_delta_1m` sum consistency
  - non-null required fields for last 60 minutes

**Step 2: Runtime checks**
- `trade_flow_snapshots` max age <= 120s across pairs for 30 consecutive minutes.
- cron last 60m: failures = 0, successes >= 55.
- full `healthcheck_all.py` remains green/warn only for acknowledged non-critical signals.

**Step 3: Regression checks**
- confirm no regressions to:
  - `raw_trades` freshness
  - `ohlcv_*`
  - `indicator_values`
  - `open_interest`
  - `oi_features`

---

## Rollback Plan
1. Re-point cron command back to prior function wrapper (if needed).
2. Keep new functions; disable new watchdog if it causes false positives.
3. Preserve backfilled snapshot rows (data is additive/idempotent and should not be rolled back).

## Acceptance Criteria
1. `trade_flow_snapshots` freshness: PASS for all required pairs over 30 continuous minutes.
2. Backfilled gap between prior max snapshot and now has no missing minutes.
3. `trade_flow_snapshots_every_minute` no timeout failures in steady state.
4. Healthcheck includes explicit trade_flow checks and catches future regressions.
5. Ingestion behavior from GCP remains unchanged.
