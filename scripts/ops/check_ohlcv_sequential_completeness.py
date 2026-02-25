#!/usr/bin/env python3
"""Compatibility wrapper for utility-scripts OHLCV sequential audit.

Canonical source:
  /Users/vitolo/Desktop/projects/poly/utility-scripts/ohlcv/check_ohlcv_sequential_completeness.py
"""
from __future__ import annotations

import importlib.util
import runpy
import sys
from pathlib import Path
from types import ModuleType

_CANONICAL = (
    Path(__file__).resolve().parents[2]
    / "utility-scripts"
    / "ohlcv"
    / "check_ohlcv_sequential_completeness.py"
)


def _load_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("utility_ohlcv_completeness", _CANONICAL)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load canonical utility at {_CANONICAL}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


_utility = _load_module()

for _name in dir(_utility):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_utility, _name)


def __getattr__(name: str):
    return getattr(_utility, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_utility)))


if __name__ == "__main__":
    runpy.run_path(str(_CANONICAL), run_name="__main__")
