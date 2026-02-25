# Order Book Utility Runbook (AI Agent)

## Canonical Script
`/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/check_order_book_snapshots_health.py`

## Primary Purpose
Verify `public.order_book_snapshots` is fresh per pair and has continuous minute-level coverage in a rolling UTC window.

## How To Run

1. Standard TLDR audit:
```bash
cd /Users/vitolo/Desktop/projects/poly
python3 utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 180 --tldr
```

2. Full detail audit:
```bash
python3 utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 180
```

3. Custom pair set:
```bash
python3 utility-scripts/order_book/check_order_book_snapshots_health.py --pairs BTC-USD,ETH-USD --lookback-minutes 180 --tldr
```

## Verification (Required)

1. Contract tests:
```bash
pytest -q tests/ops/test_source_health_utilities_contract.py
```

2. Runtime smoke test:
```bash
python3 utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 60 --tldr
```

## Output Artifacts

All run outputs are written to:
`/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/output/`

File pattern:
`order_book_snapshots_health_<N>m_<UTCSTAMP>.json`

## Exit Code Contract

1. `0` = no failing checks (`WARN` allowed, `FAIL` absent).
2. `1` = one or more failing checks.
3. non-`0` with traceback = execution/config/runtime issue.

## Assumptions

1. `SUPABASE_DB_URL` exists in environment or `/Users/vitolo/Desktop/projects/poly/.env`.
2. `SUPABASE_DB_PASSWORD` exists in environment or `.env` for authenticated `psql` access.
3. Freshness threshold comes from `ops.pipeline_slo_config` (`source='order_book_snapshots'`), with fallback default of 120 seconds.

## Tradeoffs

1. Script is read-only (detects, does not repair).
2. Minute coverage gaps are reported as `WARN` unless freshness/availability also fails.
3. Faster ingestion rates only increase rows-per-minute metrics; thresholds remain SLO-driven.

## Required Agent Response Format

When reporting results from this utility, include:
1. `Run commands`
2. `Verification commands`
3. `Output files`
4. `Assumptions/tradeoffs`
5. `Findings` (by pair, with freshness + minute continuity)

