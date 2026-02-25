# OHLCV Sequential Completeness Audit Utility Implementation Plan

> **For Claude:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task.

**Goal:** Add a reusable ops utility that verifies OHLCV tables are complete and sequential (no skipped candles) across `1m..12h` for a configurable last `N` days window.

**Architecture:** Implement a read-only Python CLI under `scripts/ops/` that runs per-timeframe SQL checks for expected buckets vs actual buckets, plus duplicate/misalignment/gap diagnostics. Persist JSON report to `scripts/output/ohlcv_audits/`.

**Tech Stack:** Python 3.11, `psql` subprocess, pytest contract test.

---

### Task 1: Add utility script

**Files:**
- Create: `scripts/ops/check_ohlcv_sequential_completeness.py`

**Step 1: Implement CLI options**
- `--days` (default 5), `--pairs`, `--schema`, `--tldr`.

**Step 2: Implement read-only SQL checks**
- For each timeframe table:
  - expected bucket series
  - missing buckets
  - duplicate rows
  - misaligned rows
  - gap violations

**Step 3: Implement stdout + JSON output**
- Human-readable summary.
- JSON report under `scripts/output/ohlcv_audits/`.

### Task 2: Add test coverage for utility contract

**Files:**
- Create: `tests/ops/test_ohlcv_sequential_completeness_contract.py`

**Step 1: Add test for timeframe coverage**
- Assert `12h` timeframe exists in the utility map.

**Step 2: Add SQL-shape assertions**
- Assert generated SQL includes `generate_series`, missing anti-join, duplicate and gap checks.

### Task 3: Verify + run current audit

**Step 1: Run tests**
- `pytest -q tests/ops/test_ohlcv_sequential_completeness_contract.py`

**Step 2: Run utility for requested window**
- `python3 scripts/ops/check_ohlcv_sequential_completeness.py --days 5 --tldr`

**Step 3: Save and report output path + findings**
