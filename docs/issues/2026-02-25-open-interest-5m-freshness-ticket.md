# Ticket: Open Interest Freshness Upgrade to 5-Minute Cadence

## ID
`OPS-OI-2026-02-25-001`

## Status
`MONITORING`

## Priority
`P1`

## Summary
Open interest is currently fresh enough for the existing SLO, but cadence should be upgraded so data is pulled every 5 minutes for tighter freshness. This ticket tracks design, safe rollout, and validation for the cadence change.

## Scope
Source table: `indicators.open_interest`  
Pairs: `BTC-USD`, `ETH-USD`, `SOL-USD`  
Downstream dependency: `indicators.oi_features` and any consumer reading OI/OI-derived fields.

## Evidence (2026-02-25 UTC)
Verification query showed last-hour data exists for all tracked pairs, with latest bucket around `07:00:00+00` and `rows_last_hour=3` per pair at check time.

## Target State
1. OI ingest cadence runs every 5 minutes.
2. Freshness objective updated to match new cadence.
3. OI and OI-derived computations remain correct under the faster schedule.
4. No regressions in existing reliability controls (cron, supervisor, health checks, alerting).

## Definition of Done
1. OI ingest schedule is 5-minute cadence in production.
2. Freshness checks/reporting reflect the new cadence and pass continuously.
3. `open_interest` and `oi_features` remain green for 30 continuous minutes after rollout.
4. Backfill/reconcile path documented for any missed windows.
5. Change is runbooked and linked in incident changelog.

## Planning and Implementation Checklist
- [x] Map current OI ingestion path end-to-end (cron, edge function, retries, cooldowns).
- [x] Define new SLO and alert thresholds for 5-minute cadence.
- [x] Validate write-volume and query-cost impact under 5-minute schedule.
- [x] Update scheduler/configuration for 5-minute execution.
- [x] Verify no duplicate/misaligned OI buckets from increased cadence.
- [x] Verify `oi_features` recompute path aligns with new OI arrival pattern.
- [x] Run staged canary verification before full rollout.
- [x] Record final evidence and close ticket.

## Constraints
1. Keep websocket ingestion behavior unchanged (not part of this change).
2. No fabricated OI values; gaps must be explicit and recoverable via backfill/reconcile.
3. Any rollout must be reversible with documented rollback steps.

## Owner
`ops-reliability`

## 2026-02-25 Execution Update
1. Migration added and applied:
- `supabase/migrations/20260225_120000_open_interest_5m_cadence.sql`
2. Scheduler changes:
- `oi-ingest-main`: `*/5 * * * *`
- `oi-ingest-retry`: `2-59/5 * * * *`
- `oi-reconcile`: unchanged (`7 * * * *`)
3. SLO updates:
- `ops.pipeline_slo_config` now sets `max_lag=1200s` for `open_interest` and `oi_features`.
- utility fallback updated to `1200s` in:
  - `utility-scripts/open_interest/check_open_interest_health.py`
  - `utility-scripts/open_interest/README.md`
4. Canary evidence:
- Manual ingest invocation request: `304712`
- `net._http_response` status: `200`, `timed_out=false`
- latest `open_interest.ingested_at` lag observed: ~`34-36s` across tracked pairs.
5. Data-quality checks:
- 24h OI continuity check: `missing_buckets=0`, `gap_violations=0`, `duplicate_rows=0`, `misaligned_rows=0` for `BTC-USD`, `ETH-USD`, `SOL-USD`.
6. Evidence artifact:
- `scripts/output/open_interest_issue1_rollout_20260225.json`
7. Constraint confirmation:
- no websocket ingestion architecture/behavior changes were made.
