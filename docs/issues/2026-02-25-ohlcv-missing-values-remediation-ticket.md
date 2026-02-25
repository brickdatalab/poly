# Ticket: OHLCV Missing Values Remediation

## ID
`OPS-OHLCV-2026-02-25-001`

## Status
`OPEN`

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
- [ ] Validate whether `1m` duplicate/misaligned rows are true data defects vs expected bucket-time convention.
- [ ] Rebuild/fix impacted `1m` buckets for the incident window using approved recovery path.
- [ ] Recompute rollups (`5m`, `10m`, `15m`) after `1m` correction.
- [ ] Re-run sequential completeness audit for 5 days and 7 days.
- [ ] Record final evidence in changelog and close ticket.

## Owner
`ops-reliability`
