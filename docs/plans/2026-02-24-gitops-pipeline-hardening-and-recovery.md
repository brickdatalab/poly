# GitOps Pipeline Hardening And Recovery Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Recover the broken indicator/OHLCV/OI pipeline and harden it with GitOps controls so this outage class cannot silently recur.

**Architecture:** Keep the existing ingestion topology (GCP VM -> `public.raw_trades`) unchanged. Apply reliability changes in three layers: (1) source control + deployment governance, (2) compute pipeline recovery and safety rails, (3) consumer freshness fail-closed behavior. Production mutations must be migration-backed or runbook-scripted.

**Tech Stack:** Supabase Postgres/pg_cron/Edge Functions, Python 3.11 scripts, GitHub repo/PR checks, existing `monkey` signal engine.

---

## Guardrails

1. Do not modify the GCP VM websocket ingestion behavior or trade-write path.
2. Do not delete production data.
3. Every DB change must exist as SQL in `supabase/migrations`.
4. Every manual production action must be captured in runbook notes.

## Task 1: Bootstrap GitOps Repository

**Files:**
- Create: `.gitignore`
- Create: `.github/pull_request_template.md`
- Create: `.github/workflows/ci.yml`
- Create: `.github/workflows/supabase-preview-watch.yml`
- Create: `docs/runbooks/gitops-operating-model.md`
- Modify/ensure: `supabase/**` committed

**Steps:**
1. Initialize git in `/Users/vitolo/Desktop/projects/poly` and set `origin` to `https://github.com/brickdatalab/poly.git`.
2. Add ignore rules for secrets and local artifacts (`.env`, `gcp_credentials.json`, script outputs, caches).
3. Add baseline workflows and PR template.
4. Commit and push baseline.

## Task 2: Add Critical Recovery SQL Artifacts

**Files:**
- Create: `supabase/migrations/20260224_*.sql` (runtime guards/recovery primitives)
- Create: `docs/runbooks/indicator-pipeline-recovery.md`
- Create: `scripts/ops/recovery_snapshot.py`

**Steps:**
1. Add migration(s) for stale-running reclaim and operational checks.
2. Add SQL snippets for queue visibility and freshness validation.
3. Add runbook with ordered execution.

## Task 3: Execute Production Recovery

**Files:**
- Modify: `docs/runbooks/indicator-pipeline-recovery.md` (fill execution record)

**Steps:**
1. Restore worker schema path (`pgrst.db_schemas` includes `indicators`).
2. Reclaim stale `running` jobs.
3. Verify worker processes jobs and backlog starts draining.
4. Backfill missing raw-trade windows externally (if needed), then run `fn_backfill_ohlcv(...)`.
5. Recompute/drain indicators and verify freshness.
6. Resolve OI timeout behavior and backfill OI features.

## Task 4: Fail-Closed Freshness In Monkey Engine

**Files:**
- Modify: `/Users/vitolo/Desktop/projects/monkey/syn-final/scripts/engine.py`
- Modify: `/Users/vitolo/Desktop/projects/monkey/server.py`
- Create/modify: tests under `/Users/vitolo/Desktop/projects/monkey/syn-final/tests/`

**Steps:**
1. Add max-age checks in fetch helpers.
2. Treat stale inputs as missing (`not_ready`/`stale_inputs`).
3. Add pre-fire health gate to avoid stale “ready” emissions.
4. Add tests for exact-time and stale-series behavior.

## Task 5: Monitoring, Drift Detection, And Backstop

**Files:**
- Create: `supabase/migrations/20260224_*_monitoring.sql`
- Create: `scripts/ops/check_postgrest_required_schemas.py`
- Modify: `scripts/healthcheck_all.py` (critical thresholds)
- Create: `docs/runbooks/incident-response-slo.md`

**Steps:**
1. Add/verify pg_cron backstop for worker invocation.
2. Add regular schema-config drift check (`pgrst.db_schemas` requirements).
3. Tighten health checks so stale indicator freshness fails hard.
4. Document alert thresholds and escalation flow.

## Verification Gates

1. `indicator-worker` invoke returns 200 and processes jobs.
2. `indicators.job_queue` pending decreases over time; stale `running` goes to 0.
3. `ohlcv_1m`, `ohlcv_5m`, `ohlcv_15m`, `indicator_values`, `oi_features` freshness in SLA.
4. `monkey` engine returns no stale “ready” outcomes on forced stale fixtures.
5. GitHub PR checks pass and Supabase preview checks are required before merge.
