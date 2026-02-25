# Incident Changelog / Ticket: `OPS-2026-02-24-TRF-001`

## 2026-02-25 Update (Reliability Issues #1-#4 Baseline)
1. Captured baseline evidence artifact:
   - `scripts/output/reliability_issue_2026_02_25_baseline.json`
2. Issue #3 OHLCV baseline (5d):
   - `ohlcv_1m` for `BTC-USD/ETH-USD/SOL-USD`: `missing=56`, `gap_violations=2`, `duplicate_rows=1440`, `misaligned_rows=1440`
   - `ohlcv_5m`: `missing=11`, `gap_violations=1` (all three pairs)
   - `ohlcv_10m`: `missing=5`, `gap_violations=1` (all three pairs)
   - `ohlcv_15m`: `missing=3`, `gap_violations=1` (all three pairs)
3. Issue #1 OI baseline:
   - cron schedules currently: `oi-ingest-main=1,16,31,46 * * * *`, `oi-ingest-retry=4,19,34,49 * * * *`, `oi-reconcile=7 * * * *`
   - OI and OI-features lag observed around `~1031s` at baseline checkpoint.
4. Issues #2/#4 baseline:
   - missing objects confirmed (`ops.master_indicator_registry`, `ops.indicator_latency_slo_config`, `ops.indicator_latency_log`, and snapshot functions not yet present).
5. Environment note:
   - local `psql` client currently aborts due Homebrew `krb5` dylib signature policy; read-only DB baseline queries were executed through Supabase integration as a temporary verification path.

## 2026-02-25 Update (Issue #3 OHLCV Remediation Executed)
1. Added migration:
   - `supabase/migrations/20260225_110000_ohlcv_fractional_placeholder_cleanup.sql`
2. Root cause confirmed:
   - `ohlcv_1m` duplicate/misaligned rows were fractional-second zero-volume placeholders from a prior continuity patch (`bucket_time` with `.239748` fractional seconds).
3. Bounded repair SQL executed:
   - `select ops.fn_repair_ohlcv_issue3(array['BTC-USD','ETH-USD','SOL-USD'], now()-interval '7 days', now(), interval '7 days');`
4. Execution result highlights:
   - deleted fractional placeholders: `4320` total (`1440` per pair)
   - continuity rows inserted: `171`
   - rollup backfill emitted rows for `1m..12h`
5. Post-remediation verification artifact:
   - `scripts/output/ohlcv_issue3_repair_20260225.json`
   - audit summary: `5d non_pass_count=0`, `7d non_pass_count=0`, `remaining_fractional_rows=[]`
6. No websocket ingestion behavior changes were made.

## 2026-02-25 Update (Issue #1 OI 5-Minute Cadence Rollout)
1. Added migration:
   - `supabase/migrations/20260225_120000_open_interest_5m_cadence.sql`
2. Applied scheduler changes:
   - `oi-ingest-main`: `*/5 * * * *`
   - `oi-ingest-retry`: `2-59/5 * * * *`
   - `oi-reconcile`: unchanged (`7 * * * *`)
3. Applied SLO changes:
   - `ops.pipeline_slo_config` max lag for `open_interest` and `oi_features` set to `900s`.
4. Canary/checkpoint evidence:
   - manual ingest invoke request id: `304712`
   - `net._http_response` status: `200` (`timed_out=false`)
   - latest ingest recency observed via `open_interest.ingested_at`: `~34-36s` lag
   - 24h continuity check: no missing/gap/duplicate/misaligned buckets for `BTC-USD/ETH-USD/SOL-USD`
5. Artifact:
   - `scripts/output/open_interest_issue1_rollout_20260225.json`
6. No websocket ingestion behavior changes were made.

## 2026-02-25 Update (Archive Prune + Source Checker Checkpoint)
1. Pruned archive-only legacy script trees from active repo:
   - removed `syn/scripts` (17 files)
   - removed `scripts/scripts_past` (21 files + legacy tests + legacy ops shell wrappers)
2. Added OI cadence follow-up ticket:
   - repo ticket: `docs/issues/2026-02-25-open-interest-5m-freshness-ticket.md`
   - GitHub issue: [#1](https://github.com/brickdatalab/poly/issues/1)
3. Utility checker status checkpoint (UTC):
   - `utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr` => `FAIL` (known OHLCV gaps/misalignment window remains)
   - `utility-scripts/market_context/check_market_context_health.py --lookback-minutes 180 --tldr` => `PASS` (`GREEN`)
   - `utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 180 --tldr` => `PASS` (`GREEN`)
   - `utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 24 --tldr` => `PASS` (`GREEN`)
4. Clarification:
   - OI is currently green under existing SLO.
   - cadence/freshness tightening to 5-minute pulls is tracked separately in `OPS-OI-2026-02-25-001`.

## 2026-02-25 Update (Source Health Traffic-Light Utilities)
1. Added shared source-health utility core:
   - `utility-scripts/source_health/common.py`
2. Added new source utilities:
   - `utility-scripts/market_context/check_market_context_health.py`
   - `utility-scripts/order_book/check_order_book_snapshots_health.py`
   - `utility-scripts/open_interest/check_open_interest_health.py`
3. Added contract tests:
   - `tests/ops/test_source_health_utilities_contract.py`
4. Added AI operator runbooks:
   - `utility-scripts/market_context/README.md`
   - `utility-scripts/order_book/README.md`
   - `utility-scripts/open_interest/README.md`
5. Updated utility index/catalog:
   - `utility-scripts/README.md`
   - `docs/operations/ops-catalog.md`
6. Design rule enforced:
   - freshness thresholds are read from `ops.pipeline_slo_config` with defaults only as fallback
   - faster ingestion rates only change observed `rows_per_minute` metrics (no code changes needed)

## 2026-02-25 Update (OHLCV Sequential Completeness Audit, 5d)
1. Added reusable utility:
   - canonical: `utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py`
   - compatibility wrapper: `scripts/ops/check_ohlcv_sequential_completeness.py`
2. Added contract test:
   - `tests/ops/test_ohlcv_sequential_completeness_contract.py`
3. Executed live audit:
   - command: `python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr`
   - report: `utility-scripts/ohlcv/output/ohlcv_sequential_audit_5d_20260225T065000Z.json`
4. Findings (BTC/ETH/SOL, same pattern on all three pairs):
   - `1m`: missing `56`, gap violations `2`, duplicate rows `1440`, misaligned rows `1440`
   - `5m`: missing `10`, gap violations `1`
   - `10m`: missing `4`, gap violations `1`
   - `15m`: missing `2`, gap violations `1`
   - `30m,45m,1h,2h,6h,12h`: no failures in this 5-day window
5. Incident window concentration:
   - missing buckets cluster around `2026-02-23 03:00:00+00` to `2026-02-23 03:55:00+00` on lower timeframes.
6. Open remediation ticket created:
   - `docs/issues/2026-02-25-ohlcv-missing-values-remediation-ticket.md`
7. Added AI-agent execution runbook for this utility:
   - `utility-scripts/ohlcv/README.md`

## 2026-02-25 Update (GitHub Push + Current Checkpoint)
1. Changelog synchronized to current UTC checkpoint:
   - checkpoint time: `2026-02-25 06:37:56Z`
2. Latest local commits before push:
   - `8b7fc4e` — `chore: checkpoint phase1 reliability hardening and repo organization`
   - `c67ce93` — `docs: add phase2 tdd implementation plan and checkpoint update`
3. Branch for push:
   - `codex/supabase-reliability-autofix`
4. Remote target:
   - `origin https://github.com/brickdatalab/poly.git`
5. Websocket ingestion behavior remains unchanged.

## 2026-02-25 Update (Post-Phase-1 Checkpoint)
1. Current branch state was committed as a checkpoint:
   - commit: `8b7fc4e`
   - message: `chore: checkpoint phase1 reliability hardening and repo organization`
2. Phase 1 artifacts now include:
   - canonical runtime lane under `runtime/`
   - runtime parity tests under `tests/runtime/`
   - ops contract tests under `tests/ops/`
   - classification/categorization docs under `docs/architecture`, `docs/operations`, and `docs/research`
3. Phase 2 execution plan created:
   - `docs/plans/2026-02-25-phase2-product-structure-tdd-implementation.md`
4. No websocket ingestion changes were made in this checkpoint.

## Summary
- Status: `MONITORING` (recovery complete; hardening deployed; watch window active)
- Severity: `SEV-2` (historical stale snapshot incident; mitigated and under monitoring)
- Scope: `public.trade_flow_snapshots` recovery and hardening
- Constraint: do **not** change websocket ingestion behavior from GCP VM into `public.raw_trades`
- Last verified (UTC): `2026-02-24 21:04`

## Current State (Evidence)
1. Healthcheck overall is `WARN`, not `FAIL`.
2. Core datasets are fresh (`raw_trades`, `ohlcv_*`, `indicator_values`, `open_interest`, `oi_features`).
3. `public.trade_flow_snapshots` is now fresh:
   - latest snapshot (all pairs): `2026-02-24T21:04:00+00:00`
   - age at verification: `~5s`
4. Source data is live:
   - latest `public.raw_trades`: near-real-time (seconds old at verification)
5. Scheduler path is healthy:
   - job: `trade_flow_snapshots_every_minute`
   - command: `select public.capture_trade_flow_snapshots_tick();`
   - last 15m: successes observed, failures `0` at verification
6. New watchdog is active:
   - job: `trade-flow-snapshot-watchdog`
   - command: `select ops.fn_trade_flow_snapshot_watchdog();`
   - schedule: every 2 minutes

## Impacted Consumers
Directly impacted metrics (sourced from `trade_flow_snapshots`):
- `current_price`
- `cvd_cumulative`
- `cvd_value`
- `trade_flow_imbalance`
- `trade_flow_ratio`

Current active rule consumers:
1. `public.smash` active rules using impacted metrics: `122, 230, 231, 235, 236, 238, 321, 322, 915`
2. `public.smash_sfm` active rules using impacted metrics: `35`

Not impacted:
1. `indicators.indicator_values` compute path (including `cvd_*` config IDs) does not depend on `trade_flow_snapshots`.
2. OHLCV and indicator freshness SLOs currently remain green.

## Root Cause (Systematic Debugging Conclusion)
Primary root cause:
1. `public.capture_trade_flow_snapshots()` computes `delta_since_prev` from `raw_trades` starting at the **previous snapshot** time.
2. With snapshots stale by ~8 days, each cron tick scans a very large `raw_trades` window.
3. Query exceeds statement timeout, fails, and never advances snapshot watermark.
4. Cron retries every minute against the same giant window, creating a permanent timeout loop.

Secondary operational gap:
1. No bounded catch-up window or checkpoint cursor for this path.
2. No dedicated freshness watchdog for `trade_flow_snapshots`.

## Fix Plan (No Ingestion Changes)
### Phase A: Stop the timeout loop safely
1. Pause `trade_flow_snapshots_every_minute` cron job.
2. Keep all other jobs running.

### Phase B: Backfill snapshots in bounded windows
1. Add a backfill function that processes `[start_ts, end_ts)` in small chunks (e.g., 60-120 minutes per chunk):
   - `public.fn_backfill_trade_flow_snapshots(p_start timestamptz, p_end timestamptz, p_chunk_minutes int default 120)`
2. For each chunk:
   - compute per-minute 1m and 5m trade-flow aggregates from `public.raw_trades`
   - compute `cvd_cumulative` using prior cumulative anchor + chunk delta
   - `UPSERT` into `public.trade_flow_snapshots` by `(pair, snapshot_time)`
3. Run until `max(snapshot_time)` reaches current minute minus 1 minute.

### Phase C: Replace fragile minute job with bounded tick
1. Replace runtime function with bounded catch-up logic:
   - `public.capture_trade_flow_snapshots_tick(p_as_of timestamptz default date_trunc('minute', now()), p_max_catchup_minutes int default 15)`
2. Each run handles only a small bounded window and advances watermark incrementally.
3. If backlog remains, next cron tick continues from last watermark.
4. Resume cron: `select public.capture_trade_flow_snapshots_tick();`

### Phase D: Add hard reliability rails
1. Add health checks:
   - `trade_flow_snapshots` freshness per pair (SLO <= 120s)
   - cron failure budget (e.g., fail if >3 failures in 15m)
2. Add watchdog action:
   - if stale + repeated failures, auto-pause job and create incident row
3. Add explicit observability:
   - log rows written, runtime ms, window start/end for each tick.

## Execution Log (Completed)
1. Applied migration:
   - `supabase/migrations/20260224_203000_trade_flow_snapshots_bounded_recovery.sql`
2. Backfilled stale window:
   - call: `public.fn_backfill_trade_flow_snapshots(...)`
   - result: `windows=100`, `rows_upserted=35802`
   - range: `2026-02-16T13:45:00+00:00` -> `2026-02-24T20:39:00+00:00`
3. Verified bounded tick runtime:
   - `public.capture_trade_flow_snapshots_tick()` returned success and wrote current window rows.
4. Applied watchdog migration:
   - `supabase/migrations/20260224_204000_trade_flow_snapshot_watchdog.sql`
5. Added health coverage in script:
   - `trade_flow_snapshots_freshness`
   - `trade_flow_snapshot_cron`
6. Updated SLO runbook to include `public.trade_flow_snapshots`.

## Acceptance Criteria
1. `max(snapshot_time)` age <= `120s` for `BTC-USD`, `ETH-USD`, `SOL-USD`.
2. `trade_flow_snapshots_every_minute` failures in last 60m = `0`.
3. Successes in last 60m >= `55`.
4. Impacted metrics (`cvd_value`, `trade_flow_ratio`, `trade_flow_imbalance`) are non-null for latest 30 minutes.
5. No regression in core healthcheck checks (`ohlcv_*`, `indicator_values`, `oi_features`, `open_interest` remain PASS).

## Implementation Checklist
- [x] Migration: add bounded tick function + backfill function
- [x] Migration: switch cron command to bounded tick function
- [x] Run one-time bounded backfill to close stale window
- [x] Add `trade_flow_snapshots` checks into `scripts/healthcheck_all.py`
- [x] Add incident watchdog for repeated cron failures
- [ ] Validate against acceptance criteria for 30 consecutive minutes (monitoring window still in progress)

## Risks / Notes
1. This fix intentionally keeps websocket ingestion untouched.
2. Backfill must be chunked to avoid long-running transactions.
3. Do not fabricate data; derive from `raw_trades` and minute buckets deterministically.
4. If backfill encounters long historical window pressure, reduce chunk size and continue.
