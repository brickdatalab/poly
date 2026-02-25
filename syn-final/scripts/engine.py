#!/usr/bin/env python3
"""Compatibility wrapper for the canonical runtime synthetic engine.

Canonical source:
  /Users/vitolo/Desktop/projects/poly/runtime/synthetic/engine.py
"""
from __future__ import annotations

import importlib.util
import runpy
from pathlib import Path
from types import ModuleType

_RUNTIME_ENGINE = Path(__file__).resolve().parents[2] / "runtime" / "synthetic" / "engine.py"


def _load_runtime_module() -> ModuleType:
    spec = importlib.util.spec_from_file_location("runtime_synthetic_engine", _RUNTIME_ENGINE)
    if spec is None or spec.loader is None:
        raise ImportError(f"Unable to load runtime engine at {_RUNTIME_ENGINE}")
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


_runtime = _load_runtime_module()

# Re-export public symbols for import compatibility.
for _name in dir(_runtime):
    if _name.startswith("_"):
        continue
    globals()[_name] = getattr(_runtime, _name)


def __getattr__(name: str):
    return getattr(_runtime, name)


def __dir__() -> list[str]:
    return sorted(set(globals()) | set(dir(_runtime)))


if __name__ == "__main__":
    runpy.run_path(str(_RUNTIME_ENGINE), run_name="__main__")
