# Ticket: Indicator Compute Latency SLOs (Close-to-Populate) + Fast-Path Hardening

## ID
`OPS-IND-LAT-2026-02-25-001`

## Status
`OPEN`

## Priority
`P0`

## Summary
Define, measure, enforce, and alert on indicator compute latency so technical indicators are populated as fast as possible after candle close, without sacrificing correctness.

This ticket introduces a formal close-to-populate latency contract and operational controls to keep latency low and stable during normal operation and recovery windows.

## Why This Exists
Business requirement is explicit:
1. Data must be accurate and fresh.
2. Indicators must work with zero silent degradation.
3. Time from candle close to indicator availability must be minimized.

Today we have freshness checks, but we do not yet have a dedicated production SLO for *compute latency from close -> indicator row available*.

## Problem Statement
We currently detect stale datasets and missing data, but we lack a first-class latency guarantee that answers:
1. How fast do indicators appear after their source candle closes?
2. Which configs/timeframes are consistently slow?
3. Is delay caused by queue backlog, worker throughput, source delay, or DB write contention?

Without this, indicators can be "fresh enough" while still too slow for real-time decisioning.

## Scope
In scope:
1. Latency SLO definition for technical indicators in `indicators.indicator_values`.
2. SQL functions/log tables for latency snapshot + trend history.
3. Utility checker script and JSON output contract for AI agents/dashboard.
4. Alerting/escalation policy for sustained latency breaches.
5. Backlog/worker tuning guidance and safe remediation decision tree.

Out of scope:
1. Any websocket ingestion path changes on GCP VM.
2. Synthetic indicator formula changes.
3. Historical research optimization outside production runtime.

## Critical Definitions
### Indicator Close-to-Populate Latency
For an indicator value row in `indicators.indicator_values`:
1. `bucket_time` = source candle bucket start (existing convention).
2. `bucket_close_time` = `bucket_time + timeframe_interval`.
3. `populate_time` = `created_at` on `indicator_values` row.
4. `compute_latency_seconds` = `populate_time - bucket_close_time`.

If `compute_latency_seconds < 0`, clamp to `0` for reporting (clock/order artifacts).

### SLO Measurement Window
Rolling lookback default: 24h, grouped by:
1. `pair`
2. `timeframe`
3. `config_id`

### Primary KPIs
1. `p50_latency_seconds`
2. `p95_latency_seconds`
3. `p99_latency_seconds`
4. `max_latency_seconds`
5. `breach_rate_pct` (rows over threshold / total rows)

## Target SLOs (Initial)
These are starting production targets and can be tightened after 7-day baseline:
1. `1m` indicators: `p95 <= 15s`, `p99 <= 30s`
2. `5m` indicators: `p95 <= 30s`, `p99 <= 60s`
3. `10m/15m` indicators: `p95 <= 45s`, `p99 <= 90s`
4. `30m+` indicators: `p95 <= 90s`, `p99 <= 180s`

Hard-fail threshold:
1. Any `p99 > 300s` for two consecutive windows => incident.

## Current Runtime Context (for implementing agent)
Relevant tables/functions in current repo/system:
1. `indicators.indicator_configs` (technical indicator catalog)
2. `indicators.indicator_values` (computed outputs, includes `created_at`)
3. `indicators.job_queue` / `indicators.computation_log` (compute path state)
4. `ops.pipeline_slo_config` and `ops.fn_pipeline_health_snapshot` (existing reliability control plane)
5. Existing source-health scripts under `utility-scripts/*`

Related open issues:
1. `#1` Open interest freshness upgrade to 5-minute cadence
2. `#2` Master indicator registry + unified indicator health light
3. `#3` OHLCV missing values remediation

This latency ticket is complementary and should integrate with `#2` outputs.

## Deliverables
### 1) Supabase Control-Plane Additions
Create/extend:
1. `ops.indicator_latency_slo_config`
- `timeframe`
- `p95_target_seconds`
- `p99_target_seconds`
- `hard_fail_seconds`
- `enabled`
- audit columns

2. `ops.indicator_latency_log`
- timestamped snapshot rows by `pair/timeframe/config_id`
- computed p50/p95/p99/max, sample size, breach flags

3. `ops.fn_indicator_compute_latency_snapshot(p_pairs text[], p_lookback interval)` returns jsonb
- machine-readable summary + rows
- includes worst offenders and reason attribution hints

4. Optional helper:
- `ops.fn_indicator_latency_watchdog()` for periodic logging/incident trigger

### 2) Utility Script
Create:
1. `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/check_indicator_compute_latency.py`
2. `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/output/.gitkeep`
3. Update `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/README.md`

Script contract:
1. Read env from repo `.env`.
2. Run snapshot SQL.
3. Print TL;DR non-pass latency rows.
4. Write JSON artifact with strict, deterministic shape.
5. Exit code policy:
- `0` no latency hard failures
- `1` one or more hard failures

### 3) OpenAI JSON Schema Contract
Create:
1. `/Users/vitolo/Desktop/projects/poly/contracts/openai/indicator_compute_latency_report.schema.json`

Schema must include:
1. `generated_at_utc`
2. `window`
3. `summary` (`PASS|WARN|FAIL`, traffic light)
4. `rows[]` with
- `pair`, `timeframe`, `config_id`
- `samples`
- `p50_latency_seconds`, `p95_latency_seconds`, `p99_latency_seconds`, `max_latency_seconds`
- `target_p95_seconds`, `target_p99_seconds`, `hard_fail_seconds`
- `status`
- `reason_code`
- `reason_detail`

Use OpenAI strict wrapper (`name`, `strict: true`, `schema`, `additionalProperties: false`).

### 4) Alerting and Remediation Decision Tree
On sustained breach:
1. Check queue health (`pending`, `running`, stale-running reclaim).
2. Trigger worker backstop.
3. Verify recent OHLCV close availability for affected timeframe.
4. If source fresh + queue healthy but latency high, escalate DB/compute throughput investigation.
5. Log incident with exact offender list.

## Reason Codes (Latency)
Required reason codes for this ticket:
1. `LATENCY_P95_BREACH`
2. `LATENCY_P99_BREACH`
3. `LATENCY_HARD_FAIL`
4. `INSUFFICIENT_SAMPLES`
5. `UPSTREAM_CLOSE_DELAY`
6. `QUEUE_BACKLOG_PRESSURE`
7. `WORKER_STALL`
8. `QUERY_ERROR`

## Test Plan
### Unit/Contract
1. SQL-shape tests verify latency formula and percentile fields are present.
2. JSON schema validation tests for report contract.
3. Script output contract test ensures stable keys/types.

### Integration (Read-Only Safe)
1. 24h snapshot run returns structured summary + rows.
2. If no data for pair/timeframe, row marked `INSUFFICIENT_SAMPLES` (`WARN`, not silent pass).
3. Injected stale backlog scenario maps to proper reason code.
4. Re-run after backlog drain shows improved latency and reduced breach count.

## Acceptance Criteria
1. A single command can report close-to-populate latency health for all technical indicators.
2. Output identifies exactly which indicators/timeframes breach targets and by how much.
3. SLO thresholds are table-driven (configurable without code edits).
4. Alert path exists for sustained hard failures.
5. No websocket ingestion behavior changes are introduced.

## Rollout Plan
1. Deploy schema/functions in passive observe-only mode.
2. Collect baseline for 24-72h.
3. Tune thresholds if baseline reveals unrealistic targets.
4. Enable watchdog alerts.
5. Integrate latency status into unified indicator master checker (`#2`).

## Risks and Mitigations
1. Risk: false positives during backfill windows.
- Mitigation: include maintenance-window suppression or annotated mode.
2. Risk: over-tight initial SLOs create noise.
- Mitigation: staged threshold tightening after baseline.
3. Risk: hidden queue bottlenecks remain unidentified.
- Mitigation: require queue attribution fields in report output.

## Dependencies
1. `#2` Master indicator registry/health checker for final dashboard integration.
2. Existing ops control-plane (`ops.pipeline_slo_config`, supervisor/watchdog).
3. Existing reliability scripts under `utility-scripts` patterns.

## Owner
`ops-reliability`

## Verification Commands (for future implementation)
1. `pytest -q tests/ops/test_indicator_latency_contracts.py`
2. `python3 utility-scripts/indicators/check_indicator_compute_latency.py --lookback-hours 24 --tldr`
3. `python3 utility-scripts/indicators/check_indicator_compute_latency.py --lookback-hours 24`

## Links
1. Related issue docs:
- `/Users/vitolo/Desktop/projects/poly/docs/issues/2026-02-25-open-interest-5m-freshness-ticket.md`
- `/Users/vitolo/Desktop/projects/poly/docs/issues/2026-02-25-master-indicator-health-contract-ticket.md`
- `/Users/vitolo/Desktop/projects/poly/docs/issues/2026-02-25-ohlcv-missing-values-remediation-ticket.md`
2. Related plan docs:
- `/Users/vitolo/Desktop/projects/poly/docs/plans/2026-02-24-gitops-pipeline-hardening-and-recovery.md`
- `/Users/vitolo/Desktop/projects/poly/docs/plans/2026-02-25-source-health-traffic-lights-utilities.md`
