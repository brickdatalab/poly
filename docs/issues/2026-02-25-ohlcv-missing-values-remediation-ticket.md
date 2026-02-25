# Ticket: OHLCV Missing Values Remediation

## ID
`OPS-OHLCV-2026-02-25-001`

## Status
`IMPLEMENTED`

## Priority
`P0`

## Summary
Sequential completeness audit found missing candles and continuity breaks in OHLCV tables over the last 5 days. This ticket tracks root-cause validation, deterministic backfill, and post-fix re-audit.

## Scope
Schema: `indicators`  
Pairs: `BTC-USD`, `ETH-USD`, `SOL-USD`  
Timeframes impacted: `1m`, `5m`, `10m`, `15m`

## Evidence
Audit command:
`python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr`

Report file:
`/Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/output/ohlcv_sequential_audit_5d_20260225T065000Z.json`

Observed failures per pair:
1. `1m`: missing `56`, gap violations `2`, duplicate rows `1440`, misaligned rows `1440`
2. `5m`: missing `10`, gap violations `1`
3. `10m`: missing `4`, gap violations `1`
4. `15m`: missing `2`, gap violations `1`

Primary missing window concentration:
`2026-02-23 03:00:00+00` to `2026-02-23 03:55:00+00`

## Definition of Done
1. `python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr` returns exit code `0`.
2. For all three pairs and all timeframes `1m..12h`:
- `missing_rows = 0`
- `gap_violations = 0`
- `duplicate_rows = 0`
- `misaligned_rows = 0`
3. Backfill and remediation steps are documented in incident changelog and runbook.
4. No websocket ingestion behavior changes are introduced.

## Remediation Checklist
- [x] Validate whether `1m` duplicate/misaligned rows are true data defects vs expected bucket-time convention.
- [x] Rebuild/fix impacted `1m` buckets for the incident window using approved recovery path.
- [x] Recompute rollups (`5m`, `10m`, `15m`) after `1m` correction.
- [x] Re-run sequential completeness audit for 5 days and 7 days.
- [x] Record final evidence in changelog and close ticket.

## 2026-02-25 Execution Update
1. Root-cause validation:
- `1m` duplicate/misaligned rows were fractional-second placeholder candles (`bucket_time` like `...00.239748+00`, `volume=0`, `trade_count=0`) inserted by a prior continuity patch run.
- These rows are data defects (not expected bucket-time convention).
2. Migration added:
- `supabase/migrations/20260225_110000_ohlcv_fractional_placeholder_cleanup.sql`
- New functions:
  - `ops.fn_cleanup_ohlcv_1m_fractional_placeholders(...)`
  - `ops.fn_repair_ohlcv_issue3(...)`
3. Dry-run baseline before execution:
- fractional placeholder rows: `1440` per pair (`BTC-USD`, `ETH-USD`, `SOL-USD`), total `4320`.
4. Bounded execution:
- SQL run:
  - `select ops.fn_repair_ohlcv_issue3(array['BTC-USD','ETH-USD','SOL-USD'], now()-interval '7 days', now(), interval '7 days');`
- Result highlights:
  - `cleanup.deleted_rows = 4320`
  - `cleanup.deleted_by_pair = {BTC-USD: 1440, ETH-USD: 1440, SOL-USD: 1440}`
  - `repair_chain.continuity_rows_inserted = 171`
  - rollup backfill rows emitted for `1m..12h`
5. Post-fix verification:
- Artifact: `scripts/output/ohlcv_issue3_repair_20260225.json`
- Script SQL builder audit (same contract as utility script) shows:
  - `5d`: `non_pass_count = 0`
  - `7d`: `non_pass_count = 0`
  - `remaining_fractional_rows = []`
6. Constraint confirmation:
- No websocket ingestion behavior changes were made.

## Owner
`ops-reliability`
