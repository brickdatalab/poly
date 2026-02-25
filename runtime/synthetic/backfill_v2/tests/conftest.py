"""
Pytest configuration for backfill_v2 tests.
Adds the scripts/ directory to sys.path so both `engine` and `backfill_v2` are importable.
"""
import sys
from pathlib import Path

# scripts/ dir (parent of backfill_v2/)
SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))
