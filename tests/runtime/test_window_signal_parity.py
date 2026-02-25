from __future__ import annotations

from pathlib import Path

import pytest


REPO_ROOT = Path(__file__).resolve().parents[2]
WINDOW_DIR = REPO_ROOT / "runtime" / "synthetic" / "window"
MONKEY_ROOT = Path("/Users/vitolo/Desktop/projects/monkey")

WINDOW_FILES = {
    "up": "t2_window_up_signal.py",
    "down": "t2_window_down_signal.py",
}


def _normalize_monkey_window_source(source: str) -> str:
    return source.replace(
        'Path("/Users/vitolo/Desktop/projects/monkey")',
        "Path(__file__).resolve().parents[3]",
    )


@pytest.mark.parametrize("side", ["up", "down"])
def test_window_scripts_use_repo_relative_project_root(side: str) -> None:
    content = (WINDOW_DIR / WINDOW_FILES[side]).read_text()
    assert "Path(__file__).resolve().parents[3]" in content
    assert "/Users/vitolo/Desktop/projects/monkey" not in content


@pytest.mark.parametrize("side", ["up", "down"])
def test_window_scripts_match_monkey_logic_when_available(side: str) -> None:
    monkey_path = MONKEY_ROOT / f"t2_window_{side}_signal.py"
    if not monkey_path.exists():
        pytest.skip("Local monkey window script not present")

    monkey_source = _normalize_monkey_window_source(monkey_path.read_text())
    poly_source = (WINDOW_DIR / WINDOW_FILES[side]).read_text()
    assert monkey_source == poly_source
