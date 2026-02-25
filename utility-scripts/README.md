# Utility Scripts

This directory contains reusable operational utilities intended to be run by AI agents.

## AI Operator Contract

For each utility execution, the agent must report:
1. Run command(s) executed.
2. Verification command(s) executed.
3. Output artifact path(s) produced.
4. Assumptions/tradeoffs used for that run.
5. Exit code and pass/fail interpretation.

## Current Utility Modules

1. `ohlcv/`
- OHLCV sequential completeness and gap integrity utilities.
