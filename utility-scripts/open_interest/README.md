# Open Interest Utility Runbook (AI Agent)

## Canonical Script
`/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/check_open_interest_health.py`

## Primary Purpose
Verify `indicators.open_interest` freshness and 15-minute bucket continuity in a rolling UTC window.

## How To Run

1. Standard TLDR audit:
```bash
cd /Users/vitolo/Desktop/projects/poly
python3 utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 72 --tldr
```

2. Full detail audit:
```bash
python3 utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 72
```

3. Custom pair set and step:
```bash
python3 utility-scripts/open_interest/check_open_interest_health.py --pairs BTC-USD,ETH-USD --lookback-hours 72 --step-seconds 900 --tldr
```

## Verification (Required)

1. Contract tests:
```bash
pytest -q tests/ops/test_source_health_utilities_contract.py
```

2. Runtime smoke test:
```bash
python3 utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 24 --tldr
```

## Output Artifacts

All run outputs are written to:
`/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/output/`

File pattern:
`open_interest_health_<N>h_<UTCSTAMP>.json`

## Exit Code Contract

1. `0` = no failing checks (`WARN` allowed, `FAIL` absent).
2. `1` = one or more failing checks.
3. non-`0` with traceback = execution/config/runtime issue.

## Assumptions

1. `SUPABASE_DB_URL` exists in environment or `/Users/vitolo/Desktop/projects/poly/.env`.
2. `SUPABASE_DB_PASSWORD` exists in environment or `.env` for authenticated `psql` access.
3. Freshness threshold comes from `ops.pipeline_slo_config` (`source='open_interest'`), with fallback default of 1200 seconds.
4. Open interest is expected to align to a 15-minute cadence (`--step-seconds 900` by default).

## Tradeoffs

1. Script is read-only (detects, does not repair).
2. Structural continuity problems (`missing_buckets`, `duplicate_rows`, `misaligned_rows`, `gap_violations`) are reported as `WARN` unless freshness/availability fails.
3. Cadence changes can be handled by `--step-seconds` without code edits.

## Required Agent Response Format

When reporting results from this utility, include:
1. `Run commands`
2. `Verification commands`
3. `Output files`
4. `Assumptions/tradeoffs`
5. `Findings` (by pair, with freshness + continuity)
