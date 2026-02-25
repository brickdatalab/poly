# OHLCV Utility Runbook (AI Agent)

## Canonical Script
`/Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py`

## Compatibility Wrapper
`/Users/vitolo/Desktop/projects/poly/scripts/ops/check_ohlcv_sequential_completeness.py`

## Primary Purpose
Verify OHLCV tables (`1m,5m,10m,15m,30m,45m,1h,2h,6h,12h`) are sequential and complete for a rolling UTC window.

## How To Run

1. Standard TLDR audit:
```bash
cd /Users/vitolo/Desktop/projects/poly
python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --tldr
```

2. Full detail audit:
```bash
python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5
```

3. Custom pair set:
```bash
python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 5 --pairs BTC-USD,ETH-USD
```

## Verification (Required)

1. Utility contract test:
```bash
pytest -q tests/ops/test_ohlcv_sequential_completeness_contract.py
```

2. Wrapper compatibility check:
```bash
python3 scripts/ops/check_ohlcv_sequential_completeness.py --days 1 --tldr
```

3. Canonical path check:
```bash
python3 utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py --days 1 --tldr
```

## Output Artifacts

All run outputs are written to:
`/Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/output/`

File pattern:
`ohlcv_sequential_audit_<N>d_<UTCSTAMP>.json`

## Exit Code Contract

1. `0` = all timeframe/pair checks pass.
2. `1` = one or more failures detected (expected for incident detection runs).
3. non-`0` with traceback = execution failure (connection/config/runtime issue).

## Assumptions

1. `SUPABASE_DB_URL` exists in environment or `/Users/vitolo/Desktop/projects/poly/.env`.
2. `SUPABASE_DB_PASSWORD` exists in environment or `.env` for authenticated psql access.
3. Candle integrity is evaluated in UTC rolling windows.
4. No websocket ingestion behavior changes are made by this utility.

## Tradeoffs

1. Rolling `N`-day window can cut through day boundaries (not full-day-only mode).
2. Misalignment detection flags non-step-aligned timestamps even if aligned buckets can be reconstructed.
3. Duplicate detection is based on aligned bucket collisions, which surfaces idempotency issues.
4. Utility is read-only and does not remediate; remediation is tracked separately in ticket docs.

## Required Agent Response Format

When reporting results from this utility, include:
1. `Run commands`
2. `Verification commands`
3. `Output files`
4. `Assumptions/tradeoffs`
5. `Findings` (by timeframe/pair)
