# Ticket: Master Indicator Registry + Unified Indicator Health Light (AI-Only JSON Schema)

## ID
`OPS-IND-2026-02-25-001`

## Status
`IMPLEMENTED`

## Priority
`P0`

## Summary
Create a centralized indicator registry and a single blanket health checker that evaluates all technical indicator domains and returns one dashboard-grade traffic light (`GREEN|YELLOW|RED`) plus per-indicator diagnostics.

This is AI-first and contract-driven. Deliverables are OpenAI strict JSON schema contracts, SQL control-plane objects, and a utility script with machine-readable outputs.

Important constraint: **do not include an `active` column** in the master registry. Indicators are treated as expected/required by default.

## Problem Statement
Current checks are split by ingestion source (`ohlcv`, `market_context`, `order_book_snapshots`, `open_interest`) and do not provide a single indicator-wide readiness verdict.

Operational gap:
1. We can see source freshness.
2. We cannot centrally assert that all indicators are available, current, and usable.
3. We need immediate diagnostics for exactly which indicators are degraded and why.

## Scope
In scope:
1. Registry of all indicator entities across these domains:
- OHLCV-derived technical indicators (`indicators.indicator_configs` -> `indicators.indicator_values`)
- Order book derived fields (`indicators.order_book_indicators`)
- Open interest core metrics (`indicators.open_interest`)
- OI derived features (`indicators.oi_features`)
2. One consolidated indicator health snapshot function in Supabase.
3. One utility checker script in repo for AI agents and dashboard integration.
4. OpenAI strict JSON schema files for inputs/outputs/contracts.
5. Runbook-grade diagnostics fields explaining each `WARN`/`FAIL`.

Out of scope:
1. Any change to websocket ingestion behavior on GCP VM.
2. Synthetic-indicator compute logic changes (this ticket checks upstream technical readiness).
3. Backfill implementation itself (only health contract and detector framework in this ticket).

## Target State
One execution (SQL function call or utility script run) returns:
1. Global indicator health light for dashboard:
- `GREEN` when all checks pass
- `YELLOW` when warnings exist without failures
- `RED` when any hard failure exists
2. Per-indicator status records with exact reason codes and evidence.
3. Clear remediation class per failure (freshness, missing bucket, gap, dependency stale, config mismatch, etc.).

## Source-of-Truth Mapping
### OHLCV-Derived Indicators
Source catalog:
- `indicators.indicator_configs`
Values:
- `indicators.indicator_values`
Dependency:
- `indicators.ohlcv_<timeframe>`

### Order Book Indicators
Table:
- `indicators.order_book_indicators`
Fields:
- `mid_price`, `spread_pct`, `depth_ratio`, `imbalance`
- `bid_depth_10bps`, `ask_depth_10bps`
- `bid_depth_25bps`, `ask_depth_25bps`
- `bid_depth_50bps`, `ask_depth_50bps`
- `bid_slope`, `ask_slope`
- `slippage_buy_100`, `slippage_sell_100`
- `slippage_buy_1000`, `slippage_sell_1000`

### Open Interest Core
Table:
- `indicators.open_interest`
Fields:
- `open_interest`, `oi_change`, `oi_change_pct`, `price_change_pct`
- `oi_volume_ratio`, `oi_divergence`, `weak_rally`, `weak_selloff`
- `mark_price`, `open_interest_notional`, `funding_rate`, `funding_rate_8h_avg`

### OI Derived Features
Table:
- `indicators.oi_features`
Fields:
- `divergence_1h`, `divergence_4h`, `funding_oi_pressure`, `funding_oi_pressure_1h`, `basis_pct`
- `oi_roc_1h`, `oi_roc_4h`, `oi_roc_24h`, `oi_acceleration`
- `weak_rally_streak`, `weak_selloff_streak`
- `oi_ema_8`, `oi_ema_24`, `oi_ema_dev_8`, `oi_ema_dev_24`
- `price_oi_corr_16`, `price_oi_corr_24`
- `oi_change_vol_pctile_24h`, `turnover_1h`, `turnover_4h`

## Proposed Data Model (No Active Column)
Create:
- `ops.master_indicator_registry`

Required columns (no `active`):
1. `indicator_key text primary key`
2. `domain text not null` (`ohlcv_derived|order_book|open_interest|oi_features`)
3. `storage_table text not null`
4. `storage_column text not null`
5. `pair_column text not null default 'pair'`
6. `time_column text not null`
7. `timeframe_seconds integer not null`
8. `freshness_slo_seconds integer not null`
9. `availability_mode text not null` (`exact_bucket_required|latest_required`)
10. `expected_granularity_seconds integer not null`
11. `reasoning_metadata jsonb not null default '{}'::jsonb`
12. `created_at timestamptz not null default now()`
13. `updated_at timestamptz not null default now()`

Notes:
1. Registry rows are always expected.
2. Decommissioning an indicator uses explicit migration/delete, not runtime toggles.
3. This avoids silent drift from disabled rows.

## Health Classification Contract
### Per-indicator status
`PASS|WARN|FAIL`

### Reason code taxonomy
Mandatory reason codes:
1. `NO_DATA_IN_WINDOW`
2. `LAG_EXCEEDED`
3. `MISSING_EXPECTED_BUCKET`
4. `GAP_VIOLATION`
5. `DUPLICATE_BUCKETS`
6. `MISALIGNED_BUCKETS`
7. `DEPENDENCY_STALE`
8. `CONFIG_COUNT_MISMATCH`
9. `REGISTRY_DRIFT`
10. `QUERY_ERROR`

### Severity policy
1. `FAIL`: data unavailable/stale beyond hard SLO or required exact bucket missing.
2. `WARN`: data present but structural quality issue (e.g., gap/misalignment) within tolerance.
3. `PASS`: freshness and completeness satisfied.

### Dashboard mapping
1. Any `FAIL` -> global `RED`
2. No `FAIL`, any `WARN` -> global `YELLOW`
3. All `PASS` -> global `GREEN`

## OpenAI Strict JSON Schema Deliverables
Create in repo:
1. `/Users/vitolo/Desktop/projects/poly/contracts/openai/master_indicator_registry.schema.json`
2. `/Users/vitolo/Desktop/projects/poly/contracts/openai/indicator_health_check_input.schema.json`
3. `/Users/vitolo/Desktop/projects/poly/contracts/openai/indicator_health_report.schema.json`

Contract requirements:
1. Use strict OpenAI schema wrapper:
```json
{
  "name": "indicator_health_report",
  "strict": true,
  "schema": { "type": "object", "additionalProperties": false, "...": "..." }
}
```
2. `indicator_health_report` must include:
- `generated_at_utc`
- `summary` with `total_checks`, `passed_checks`, `warn_checks`, `failed_checks`, `overall_status`, `traffic_light`
- `rows[]` with:
  - `indicator_key`
  - `domain`
  - `pair`
  - `status`
  - `traffic_light`
  - `reason_code`
  - `reason_detail`
  - `latest_ts`
  - `lag_seconds`
  - `slo_seconds`
  - `expected_bucket_time`
  - `observed_bucket_time`
  - `missing_count`
  - `gap_count`
  - `duplicate_count`
  - `misaligned_count`
  - `dependency_snapshot`
3. `additionalProperties` must be `false` for all object types.

## SQL/Runtime Deliverables
1. SQL migration creating `ops.master_indicator_registry`.
2. SQL function to seed/sync registry from `indicator_configs` + static non-OHLCV definitions.
3. SQL function:
- `ops.fn_indicator_master_health_snapshot(p_pairs text[], p_lookback interval)`
4. Optional SQL helper:
- `ops.fn_indicator_master_health_failures(...)` for fast dashboard drill-down.

## Utility Script Deliverables
Create:
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/check_indicator_master_health.py`
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/README.md`
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/indicators/output/.gitkeep`

Behavior:
1. Load env from repo `.env`.
2. Run snapshot SQL function.
3. Print concise TL;DR and non-pass rows.
4. Emit JSON artifact for dashboard/agents.
5. Exit code:
- `0` when no failures
- `1` when any failures

## Required Diagnostics in Output
For each non-pass row:
1. Exactly which indicator is impacted.
2. Which pair/time bucket is impacted.
3. Why it failed/warned (reason code + human-readable reason detail).
4. How stale it is (`lag_seconds` vs `slo_seconds`).
5. Whether root cause is dependency freshness vs local table continuity.
6. Recommended remediation class:
- `trigger_recompute`
- `run_backfill_window`
- `reclaim_stale_jobs`
- `escalate_source_ingestion`

## Testing Requirements
### Unit/contract tests
1. Schema validity tests for all OpenAI schema files.
2. SQL generation/shape tests for function dependencies and reason-code fields.
3. Utility script output contract test (`summary`, `rows`, `traffic_light`).

### Integration tests (staging/prod-safe read-only)
1. Healthy state run shows `GREEN`.
2. Forced stale window produces targeted `FAIL` rows with correct reason codes.
3. Gap/misalignment scenario produces `WARN`.
4. Mixed domain issues still provide one deterministic global light.

## Acceptance Criteria
1. Single command provides one indicator-wide traffic light and per-indicator diagnostics.
2. All diagnostics are machine-readable and OpenAI strict-schema compliant.
3. No `active` column exists in the master indicator registry.
4. Output identifies exact impacted indicators and precise reasons.
5. Compatible with existing dashboard and utility-script patterns.

## Rollout Plan
1. Deploy DB objects in read-only/passive mode.
2. Validate against current healthy data.
3. Integrate utility script into ops runbook.
4. Wire dashboard to the new `indicator_master` light.
5. Enable incident response hooks using reason-code mapping.

## Risks and Mitigations
1. Risk: schema drift between registry and source tables.
- Mitigation: nightly sync + `REGISTRY_DRIFT` reason code.
2. Risk: false greens from stale non-exact queries.
- Mitigation: explicit `availability_mode` logic with exact-bucket requirements.
3. Risk: noisy alerts.
- Mitigation: preserve PASS/WARN/FAIL thresholds and cooldown-aware escalation.

## Dependencies
1. Existing `ops.pipeline_slo_config` thresholds.
2. Existing source-health utility pattern under `utility-scripts/source_health`.
3. Existing pair allowlist conventions (`BTC-USD`, `ETH-USD`, `SOL-USD`).

## Owner
`ops-reliability`

## Links
1. Existing source utilities:
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/`
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/market_context/`
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/`
- `/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/`
2. Existing issue docs:
- `/Users/vitolo/Desktop/projects/poly/docs/issues/2026-02-25-ohlcv-missing-values-remediation-ticket.md`
- `/Users/vitolo/Desktop/projects/poly/docs/issues/2026-02-25-open-interest-5m-freshness-ticket.md`

## 2026-02-25 Execution Update
1. Migration added and executed:
- `supabase/migrations/20260225_130000_indicator_master_health_and_latency.sql`
2. Implemented control-plane objects:
- `ops.master_indicator_registry` (no `active` column)
- `ops.fn_sync_master_indicator_registry()`
- `ops.fn_indicator_master_health_snapshot(p_pairs text[], p_lookback interval)`
- `ops.fn_indicator_master_health_failures(...)`
3. Implemented utility surface:
- `utility-scripts/indicators/check_indicator_master_health.py`
- `utility-scripts/indicators/README.md`
- `utility-scripts/indicators/output/.gitkeep`
4. Implemented OpenAI strict schemas:
- `contracts/openai/master_indicator_registry.schema.json`
- `contracts/openai/indicator_health_check_input.schema.json`
- `contracts/openai/indicator_health_report.schema.json`
5. Validation evidence:
- object creation verified in DB (`to_regclass/to_regprocedure` checks)
- snapshot output summary present with deterministic contract fields
- failure drill-down helper (`ops.fn_indicator_master_health_failures`) operational
- evidence artifact: `scripts/output/indicator_master_latency_issue2_4_20260225.json`
6. Current state:
- framework is deployed and operational
- live master health currently reports `RED` (detected data/latency issues), which is expected for detector rollout and is tracked as residual remediation work.
7. Constraint confirmation:
- no websocket ingestion architecture/behavior changes were made.
