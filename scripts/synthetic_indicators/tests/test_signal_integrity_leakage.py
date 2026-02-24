import json
import subprocess
from pathlib import Path

import pytest


def _has_db() -> bool:
    p = Path(".env")
    if not p.exists():
        return False
    for line in p.read_text().splitlines():
        s = line.strip()
        if s.startswith("SUPABASE_DB_URL=") and s.split("=", 1)[1].strip():
            return True
    return False


@pytest.mark.integration
def test_signal_integrity_leakage_smoke():
    if not _has_db():
        pytest.skip("No SUPABASE_DB_URL configured")

    run_dir = subprocess.check_output(
        [
            "python",
            "scripts/synthetic_indicators/run_signal_integrity_pipeline.py",
            "--start",
            "2026-02-09T00:00:00Z",
            "--end",
            "now",
            "--pairs",
            "BTC-USD,ETH-USD",
        ],
        text=True,
    ).strip().splitlines()[-1]

    summary_path = Path(run_dir) / "summary.json"
    assert summary_path.exists()
    summary = json.loads(summary_path.read_text())

    assert summary["rules_total"] >= 1
    assert "leakage_dir" in summary
    assert Path(summary["leakage_dir"]).exists()
