# Incident Response SLOs

## Scope

Applies to data products that feed signal decisions:

- `public.raw_trades`
- `public.trade_flow_snapshots`
- `indicators.ohlcv_*`
- `indicators.order_book_indicators`
- `indicators.open_interest`
- `indicators.oi_features`
- `indicators.indicator_values`

## Severity Model

- `SEV-1`: stale/incorrect data can produce wrong customer-facing signals now.
- `SEV-2`: partial degradation (single source stale, fallbacks still safe).
- `SEV-3`: non-production or no customer impact.

## Freshness SLOs (Per Pair)

- `raw_trades`: <= 90 seconds
- `trade_flow_snapshots`: <= 120 seconds
- `order_book_indicators`: <= 120 seconds
- `ohlcv_1m`: <= 120 seconds
- `ohlcv_5m`: <= 30 minutes
- `ohlcv_15m`: <= 45 minutes
- `indicator_values`: <= 45 minutes
- `open_interest`: <= 45 minutes
- `oi_features`: <= 45 minutes

## Continuity SLOs

- `ohlcv_1m` missing minutes in rolling 24h: `0` (BTC/ETH/SOL)
- `trade_flow_snapshots` cron failures in rolling 15m: `< 3` and at least one success
- stale `running` jobs older than 10 minutes: `0`

## Detection Targets

- automated check interval: 5 minutes
- alert fanout latency: <= 2 minutes from violation

## Response Targets

- acknowledge `SEV-1`: <= 5 minutes
- start mitigation `SEV-1`: <= 10 minutes
- customer-safe mode active (fail-closed): <= 15 minutes
- full recovery target `SEV-1`: <= 60 minutes

## Required Actions For `SEV-1`

1. execute `docs/runbooks/indicator-pipeline-recovery.md`
2. block stale-ready emissions (engine freshness gates must be ON)
3. capture snapshot + timeline
4. verify green healthcheck before closure

## Closure Criteria

All must hold for 30 consecutive minutes:

1. all freshness SLOs PASS
2. continuity checks PASS
3. no backlog growth trend
4. no recurring watchdog failures

## Postmortem Requirements

For each `SEV-1`:

1. root cause with concrete timestamps
2. blast radius and customer impact
3. corrective and preventive actions with owners
4. proof of guardrail added in git history
