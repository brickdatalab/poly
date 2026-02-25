# Source Health Traffic-Light Utilities Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add reusable utility scripts for `market_context`, `order_book_snapshots`, and `open_interest` that produce dashboard-friendly PASS/FAIL traffic-light health outputs with config-driven freshness thresholds.

**Architecture:** Introduce one shared source-health module under `utility-scripts/source_health/` for DB/env/query/output behavior. Keep dataset checks as separate scripts so operators can run each source independently. Read freshness thresholds from `ops.pipeline_slo_config` first, with safe defaults only as fallback.

**Tech Stack:** Python 3.11+, `psql` CLI, Supabase Postgres, `pytest`.

---

### Task 1: Add Failing Contract Tests

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/tests/ops/test_source_health_utilities_contract.py`

**Step 1: Write failing tests**
- Assert new shared module can build config-driven freshness SQL.
- Assert open-interest continuity SQL includes 15m alignment + gap checks.
- Assert each utility script target path exists.

**Step 2: Run test to verify it fails**

Run:
```bash
cd /Users/vitolo/Desktop/projects/poly
pytest -q tests/ops/test_source_health_utilities_contract.py
```

Expected: FAIL (new module/scripts not present yet).

### Task 2: Implement Shared Source-Health Module

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/source_health/__init__.py`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/source_health/common.py`

**Step 1: Minimal implementation**
- Shared env loading, `psql` JSON execution, pair parsing/validation.
- Freshness SQL builder using `ops.pipeline_slo_config`.
- High-frequency source query builder (`market_context`, `order_book_snapshots`) with minute coverage + volume profile.
- Open-interest query builder with 15m expected-series continuity checks.
- Output payload/traffic-light summary helpers.

**Step 2: Run test**

Run:
```bash
pytest -q tests/ops/test_source_health_utilities_contract.py
```

Expected: PASS for SQL/contract checks.

### Task 3: Implement Dataset Utility Scripts

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/market_context/check_market_context_health.py`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/check_order_book_snapshots_health.py`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/check_open_interest_health.py`

**Step 1: Minimal implementation**
- Standard CLI flags (`--pairs`, `--lookback-minutes`, `--tldr`, `--schema`, source-specific defaults).
- Reuse shared module.
- Emit JSON artifacts into source-specific `output/` folder.
- Return exit code `1` on any failed pair check.

**Step 2: Run contract test**

Run:
```bash
pytest -q tests/ops/test_source_health_utilities_contract.py
```

Expected: PASS.

### Task 4: Add AI Operator Runbooks

**Files:**
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/market_context/README.md`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/README.md`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/README.md`
- Modify: `/Users/vitolo/Desktop/projects/poly/utility-scripts/README.md`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/market_context/output/.gitkeep`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/order_book/output/.gitkeep`
- Create: `/Users/vitolo/Desktop/projects/poly/utility-scripts/open_interest/output/.gitkeep`

**Step 1: Document run + verify contract**
- Include command, verification command, output file location, assumptions/tradeoffs.

### Task 5: Verification Run

**Files:**
- N/A

**Step 1: Execute verification commands**

Run:
```bash
cd /Users/vitolo/Desktop/projects/poly
pytest -q tests/ops/test_source_health_utilities_contract.py
python3 utility-scripts/market_context/check_market_context_health.py --lookback-minutes 180 --tldr
python3 utility-scripts/order_book/check_order_book_snapshots_health.py --lookback-minutes 180 --tldr
python3 utility-scripts/open_interest/check_open_interest_health.py --lookback-hours 72 --tldr
```

Expected:
- Contract tests pass.
- Utilities execute and produce JSON artifacts.
- Exit code semantics follow PASS/FAIL contract.
