import tempfile
import unittest
from pathlib import Path
import sys

# Ensure `scripts/` is on sys.path so `import training_schema_review` works.
SCRIPTS_DIR = Path(__file__).resolve().parents[2]
if str(SCRIPTS_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPTS_DIR))


class TestRunnerSmoke(unittest.TestCase):
    def test_dry_run_creates_report(self) -> None:
        with tempfile.TemporaryDirectory() as td:
            out_root = Path(td)
            # Import as module to avoid spawning subprocesses.
            from training_schema_review import run_all

            old_argv = sys.argv
            try:
                sys.argv = ["run_all.py", "--out-root", str(out_root), "--dry-run"]
                run_all.main()
            finally:
                sys.argv = old_argv

            # Find REPORT.md
            reports = list(out_root.glob("*/md/REPORT.md"))
            self.assertTrue(reports, "Expected md/REPORT.md under a timestamped run dir")


if __name__ == "__main__":
    unittest.main()
